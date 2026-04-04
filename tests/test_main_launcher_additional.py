from __future__ import annotations

import argparse
import builtins
import io
import subprocess
import types

import pytest

import main


def test_print_banner_and_helpers(capsys: pytest.CaptureFixture[str]) -> None:
    main.print_banner()
    out = capsys.readouterr().out
    assert "SİDAR AKILLI BAŞLATICI" in out

    assert main._safe_choice(None, "full", {"full", "sandbox"}) == "full"
    assert main._safe_choice("  ", "full", {"full", "sandbox"}) == "full"
    assert main._safe_choice("sandbox", "full", {"full", "sandbox"}) == "sandbox"

    assert main._safe_text(None, "x") == "x"
    assert main._safe_text("  ", "x") == "x"

    assert main._safe_port("abc", "7860") == "7860"
    assert main._safe_port("70000", "7860") == "7860"
    assert main._safe_port("8080", "7860") == "8080"


def test_ask_choice_confirm_and_runtime_validation(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # ask_choice: invalid -> default
    answers = iter(["9", ""])
    monkeypatch.setattr(builtins, "input", lambda _="": next(answers))
    choice = main.ask_choice("Prompt", {"1": ("one", "ONE"), "2": ("two", "TWO")}, "1")
    assert choice == "ONE"
    assert "Geçersiz seçim" in capsys.readouterr().out

    # confirm branches
    answers2 = iter(["", "evet", "n"])
    monkeypatch.setattr(builtins, "input", lambda _="": next(answers2))
    assert main.confirm("ok?", default_yes=True) is True
    assert main.confirm("ok?", default_yes=False) is True
    assert main.confirm("ok?", default_yes=True) is False

    monkeypatch.setattr(main, "CONFIG_IMPORT_OK", True)
    assert main.validate_runtime_dependencies("web") == (True, None)
    monkeypatch.setattr(main, "CONFIG_IMPORT_OK", False)
    ok, err = main.validate_runtime_dependencies("cli")
    assert ok is False
    assert "cli.py" in (err or "")


def test_build_command_format_and_errors() -> None:
    cmd = main.build_command("cli", "ollama", "full", "info", {"model": "qwen"})
    assert cmd[1] == "cli.py"
    assert "--model" in cmd

    web_cmd = main.build_command("web", "gemini", "sandbox", "debug", {"host": "0.0.0.0", "port": "9000"})
    assert web_cmd[1] == "web_server.py"
    assert web_cmd[-2:] == ["--port", "9000"]
    assert "python" not in main._format_cmd(["echo", "a b"])  # quote behavior smoke test

    with pytest.raises(ValueError):
        main.build_command("bad", "ollama", "full", "info", {})
    with pytest.raises(ValueError):
        main.build_command("web", "bad", "full", "info", {})
    with pytest.raises(ValueError):
        main.build_command("web", "ollama", "bad", "info", {})
    with pytest.raises(ValueError):
        main.build_command("web", "ollama", "full", "bad", {})


def test_stream_pipe_writes_and_closes(capsys: pytest.CaptureFixture[str]) -> None:
    pipe = io.StringIO("line1\nline2\n")
    sink = io.StringIO()
    main._stream_pipe(pipe, sink, "[stdout]", main.CYAN, mirror=True)
    assert "line1" in capsys.readouterr().out
    assert "[stdout] line1\n" in sink.getvalue()


class _FakeProcess:
    def __init__(self, wait_rc: int = 0, wait_timeout_raises: bool = False) -> None:
        self.stdout = io.StringIO("out\n")
        self.stderr = io.StringIO("err\n")
        self._wait_rc = wait_rc
        self._wait_timeout_raises = wait_timeout_raises
        self.terminated = False
        self.killed = False
        self._running = True

    def wait(self, timeout: float | None = None) -> int:
        if timeout is not None and self._wait_timeout_raises:
            raise RuntimeError("timeout")
        if timeout is None:
            self._running = True
            return self._wait_rc
        self._running = False
        return self._wait_rc

    def poll(self):
        return None if self._running else self._wait_rc

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_run_with_streaming_log_and_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    proc = _FakeProcess(wait_rc=7, wait_timeout_raises=True)
    monkeypatch.setattr(main.subprocess, "Popen", lambda *a, **k: proc)

    log_file = tmp_path / "logs" / "child.log"
    rc = main._run_with_streaming(["python", "cli.py"], str(log_file))
    assert rc == 7
    assert proc.terminated is True
    assert proc.killed is True
    text = log_file.read_text(encoding="utf-8")
    assert "[exit_code]\n7" in text


def test_preflight_branches(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class _Cfg:
        BASE_DIR = str(tmp_path)
        GEMINI_API_KEY = ""
        OPENAI_API_KEY = ""
        ANTHROPIC_API_KEY = ""
        OLLAMA_URL = "http://localhost:11434/api"
        DATABASE_URL = "not-a-url"

    monkeypatch.setattr(main, "cfg", _Cfg())
    monkeypatch.setattr(main.sys, "version_info", (3, 9, 0))
    monkeypatch.setattr(main.sys, "version", "3.9.1 test")

    # No .env + gemini empty key + invalid DB URL
    main.preflight("gemini")

    # .env exists + openai/anthropic key warnings
    (tmp_path / ".env").write_text("X=1", encoding="utf-8")
    main.preflight("openai")
    main.preflight("anthropic")

    # ollama import error path
    import importlib

    real_import = importlib.import_module

    def _fake_import(name: str, package=None):
        if name == "httpx":
            raise ImportError("missing")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", _fake_import)
    # emulate by removing direct import fallback via __import__ hook
    real_builtin_import = builtins.__import__

    def _fake_builtin_import(name, *args, **kwargs):
        if name == "httpx":
            raise ImportError("missing")
        return real_builtin_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_builtin_import)
    main.preflight("ollama")

    # ollama non-200 path
    class _Resp:
        status_code = 503

    class _Client:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, _url: str):
            return _Resp()

    fake_httpx = types.SimpleNamespace(Client=_Client)
    monkeypatch.setitem(__import__("sys").modules, "httpx", fake_httpx)
    monkeypatch.setattr(builtins, "__import__", real_builtin_import)
    main.preflight("ollama")


def test_execute_command_and_main_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # execute_command: subprocess success
    called: dict[str, object] = {}
    monkeypatch.setattr(main.subprocess, "run", lambda cmd, check, cwd: called.update({"cmd": cmd, "cwd": cwd}))
    assert main.execute_command(["python", "cli.py"]) == 0
    assert called["cmd"] == ["python", "cli.py"]

    # execute_command: capture_output non-zero
    monkeypatch.setattr(main, "_run_with_streaming", lambda *_: 3)
    assert main.execute_command(["python", "cli.py"], capture_output=True) == 3

    # execute_command: called process error
    def _raise_called(*_a, **_k):
        raise subprocess.CalledProcessError(12, ["x"])

    monkeypatch.setattr(main.subprocess, "run", _raise_called)
    assert main.execute_command(["python", "x"]) == 12

    monkeypatch.setattr(main.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert main.execute_command(["python", "x"]) == 0

    monkeypatch.setattr(main.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert main.execute_command(["python", "x"]) == 1

    # main(): quick yok -> run_wizard
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda _self: argparse.Namespace(
            quick=None,
            provider=None,
            level=None,
            model=None,
            host=None,
            port=None,
            log="info",
            capture_output=False,
            child_log=None,
        ),
    )
    monkeypatch.setattr(main, "run_wizard", lambda: 5)
    monkeypatch.setattr(main.cfg, "validate_critical_settings", lambda: True, raising=False)
    monkeypatch.setattr(main.cfg, "init_telemetry", lambda service_name: None, raising=False)
    with pytest.raises(SystemExit) as exc1:
        main.main()
    assert exc1.value.code == 5

    # main(): quick var ama runtime blok
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda _self: argparse.Namespace(
            quick="web",
            provider=None,
            level=None,
            model=None,
            host=None,
            port="8080",
            log="info",
            capture_output=False,
            child_log=None,
        ),
    )
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (False, "blocked"))
    with pytest.raises(SystemExit) as exc2:
        main.main()
    assert exc2.value.code == 2
