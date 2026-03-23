import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def _temporary_config_module(config_module):
    prev = sys.modules.get("config")
    sys.modules["config"] = config_module
    try:
        yield
    finally:
        if prev is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev


def _load_main_module():
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        AI_PROVIDER = "ollama"
        ACCESS_LEVEL = "full"
        WEB_HOST = "0.0.0.0"
        WEB_PORT = 7860
        CODING_MODEL = "qwen2.5-coder:7b"
        GEMINI_API_KEY = ""
        OLLAMA_URL = "http://localhost:11434/api"
        BASE_DIR = "."

        @staticmethod
        def initialize_directories():
            return None

    cfg_mod.Config = _Cfg
    with _temporary_config_module(cfg_mod):
        spec = importlib.util.spec_from_file_location("main_under_test_branch_gaps", Path("main.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod


def test_safe_choice_returns_default_for_blank_and_unknown_strings():
    main_mod = _load_main_module()

    allowed = {"ollama", "gemini"}

    assert main_mod._safe_choice("   ", "ollama", allowed) == "ollama"
    assert main_mod._safe_choice("anthropic", "ollama", allowed) == "ollama"


def test_build_command_cli_without_model_or_web_args():
    main_mod = _load_main_module()

    cmd = main_mod.build_command("cli", "openai", "sandbox", "warning", {})

    assert cmd == [
        sys.executable,
        "cli.py",
        "--provider",
        "openai",
        "--level",
        "sandbox",
        "--log",
        "warning",
    ]


def test_stream_pipe_without_log_file_or_mirroring_closes_pipe(capsys):
    main_mod = _load_main_module()

    class _Pipe:
        def __init__(self):
            self._lines = iter(["first\n", "second\n", ""])
            self.closed = False

        def readline(self):
            return next(self._lines)

        def close(self):
            self.closed = True

    pipe = _Pipe()
    main_mod._stream_pipe(pipe, None, "[stdout]", main_mod.CYAN, False)

    assert pipe.closed is True
    assert capsys.readouterr().out == ""


def test_run_with_streaming_kills_process_when_wait_after_terminate_fails(monkeypatch):
    main_mod = _load_main_module()

    class _Pipe:
        def readline(self):
            return ""

        def close(self):
            return None

    class _Proc:
        def __init__(self):
            self.stdout = _Pipe()
            self.stderr = _Pipe()
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = []

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            if timeout == 3:
                raise RuntimeError("timeout")
            return 0

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1

    proc = _Proc()
    monkeypatch.setattr(main_mod.subprocess, "Popen", lambda *args, **kwargs: proc)

    rc = main_mod._run_with_streaming([sys.executable, "cli.py"], None)

    assert rc == 0
    assert proc.terminate_calls == 1
    assert proc.kill_calls == 1
    assert proc.wait_calls == [None, 3]


def test_run_with_streaming_kills_process_after_terminate_timeout_when_poll_reports_running(monkeypatch):
    main_mod = _load_main_module()

    class _Pipe:
        def readline(self):
            return ""

        def close(self):
            return None

    class _Proc:
        def __init__(self):
            self.stdout = _Pipe()
            self.stderr = _Pipe()
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = []

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            if timeout == 3:
                raise TimeoutError("still hung")
            return 0

        def poll(self):
            return None

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1

    proc = _Proc()
    monkeypatch.setattr(main_mod.subprocess, "Popen", lambda *args, **kwargs: proc)

    rc = main_mod._run_with_streaming([sys.executable, "cli.py"], None)

    assert rc == 0
    assert proc.terminate_calls == 1
    assert proc.kill_calls == 1
    assert proc.wait_calls == [None, 3]


def test_run_wizard_cli_non_ollama_skips_extra_prompt_and_executes(monkeypatch):
    main_mod = _load_main_module()
    prompts = []
    captured = {}

    monkeypatch.setattr(main_mod, "print_banner", lambda: None)

    def _ask_choice(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        if "arayüz" in prompt:
            return "cli"
        if "Sağlayıcısı" in prompt:
            return "openai"
        if "Güvenlik" in prompt:
            return "full"
        return "info"

    def _unexpected_ask_text(*_args, **_kwargs):
        raise AssertionError("ask_text should not run for non-ollama CLI mode")

    monkeypatch.setattr(main_mod, "ask_choice", _ask_choice)
    monkeypatch.setattr(main_mod, "ask_text", _unexpected_ask_text)
    monkeypatch.setattr(main_mod, "preflight", lambda provider: captured.setdefault("provider", provider))
    monkeypatch.setattr(main_mod, "confirm", lambda *_args, **_kwargs: True)
    def _fake_execute(cmd):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(main_mod, "execute_command", _fake_execute)

    assert main_mod.run_wizard() == 0
    assert captured["provider"] == "openai"
    assert captured["cmd"] == [
        sys.executable,
        "cli.py",
        "--provider",
        "openai",
        "--level",
        "full",
        "--log",
        "info",
    ]
    assert not any("Host IP" in prompt or "Portu" in prompt for prompt in prompts)


def test_main_with_valid_port_and_no_quick_delegates_to_wizard(monkeypatch):
    main_mod = _load_main_module()
    monkeypatch.setattr(sys, "argv", ["main.py", "--port", "8080"])
    monkeypatch.setattr(main_mod, "run_wizard", lambda: 5)

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 5
