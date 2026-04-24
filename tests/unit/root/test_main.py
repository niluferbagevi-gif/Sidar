import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest

import main
from types import SimpleNamespace
import importlib
import types


class _LauncherCfg:
    AI_PROVIDER = "ollama"
    ACCESS_LEVEL = "full"
    CODING_MODEL = "qwen2.5-coder:7b"
    WEB_HOST = "0.0.0.0"
    WEB_PORT = 7860

    def validate_critical_settings(self):
        return True



def test_launcher_main_quick_cli_executes_command(monkeypatch):
    captured = {}

    monkeypatch.setattr(main, "cfg", _LauncherCfg())
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda mode: (True, None))

    def _fake_execute(cmd, capture_output=False, child_log_path=None):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["child_log_path"] = child_log_path
        return 0

    monkeypatch.setattr(main, "execute_command", _fake_execute)
    monkeypatch.setattr(
        main.sys,
        "argv",
        ["main.py", "--quick", "cli", "--provider", "ollama", "--level", "full", "--log", "info"],
    )

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
    assert captured["cmd"][1] == "cli.py"
    assert "--provider" in captured["cmd"]



def test_launcher_main_without_quick_runs_wizard(monkeypatch):
    monkeypatch.setattr(main, "cfg", _LauncherCfg())
    monkeypatch.setattr(main, "run_wizard", lambda: 0)
    monkeypatch.setattr(main.sys, "argv", ["main.py"])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0


def test_dummy_config_initialize_directories_noop():
    assert main.DummyConfig().initialize_directories() is None


def test_print_banner_and_prompt_helpers(monkeypatch, capsys):
    main.print_banner()
    out = capsys.readouterr().out
    assert "SİDAR AKILLI BAŞLATICI" in out

    options = {"1": ("A", "a"), "2": ("B", "b")}
    inputs = iter(["", "9", "2"])
    monkeypatch.setattr("builtins.input", lambda _p: next(inputs))
    assert main.ask_choice("Seç", options, "1") == "a"
    assert main.ask_choice("Seç", options, "1") == "b"

    monkeypatch.setattr("builtins.input", lambda _p: "")
    assert main.ask_text("Metin", "x") == "x"
    monkeypatch.setattr("builtins.input", lambda _p: "  y  ")
    assert main.ask_text("Metin", "x") == "y"

    monkeypatch.setattr("builtins.input", lambda _p: "")
    assert main.confirm("Onay?", True) is True
    monkeypatch.setattr("builtins.input", lambda _p: "n")
    assert main.confirm("Onay?", True) is False


def test_validate_runtime_dependencies_paths(monkeypatch):
    monkeypatch.setattr(main, "CONFIG_IMPORT_OK", True)
    assert main.validate_runtime_dependencies("web") == (True, None)
    monkeypatch.setattr(main, "CONFIG_IMPORT_OK", False)
    ok, msg = main.validate_runtime_dependencies("cli")
    assert ok is False
    assert "child process fail-fast" in msg


def test_safe_helpers_and_preflight_paths(monkeypatch, tmp_path, capsys):
    assert main._safe_choice(" FULL ", "x", {"full"}) == "full"
    assert main._safe_choice(None, "x", {"full"}) == "x"
    assert main._safe_choice("abc", "x", {"full"}) == "x"
    assert main._safe_text(None, "x") == "x"
    assert main._safe_port("abc", "7860") == "7860"
    assert main._safe_port("70000", "7860") == "7860"
    assert main._safe_port("9000", "7860") == "9000"

    monkeypatch.setattr(main.sys, "version_info", (3, 9, 0))
    monkeypatch.setattr(main.sys, "version", "3.9.0 test")
    monkeypatch.setattr(main, "cfg", SimpleNamespace(BASE_DIR=str(tmp_path), DATABASE_URL="no-schema", GEMINI_API_KEY="", OPENAI_API_KEY="", ANTHROPIC_API_KEY="", OLLAMA_URL="http://o/api"))
    main.preflight("gemini")
    main.preflight("openai")
    main.preflight("anthropic")
    out = capsys.readouterr().out
    assert "Python 3.10+ önerilir" in out


def test_preflight_ollama_httpx_branches(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main.sys, "version_info", (3, 11, 0))
    monkeypatch.setattr(main, "cfg", SimpleNamespace(BASE_DIR=str(tmp_path), DATABASE_URL="", OLLAMA_URL="http://o/api"))

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    class _Client:
        def __init__(self, timeout):
            _ = timeout
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, _u):
            return _Resp(503)

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(Client=_Client))
    main.preflight("ollama")
    assert "Ollama yanıt kodu" in capsys.readouterr().out


def test_build_command_and_format_and_stream_pipe(monkeypatch, tmp_path, capsys):
    cmd_cli = main.build_command("cli", "ollama", "full", "info", {"model": "m"})
    assert "--model" in cmd_cli
    cmd_web = main.build_command("web", "ollama", "full", "info", {"host": "0.0.0.0", "port": "9000"})
    assert cmd_web[-4:] == ["--host", "0.0.0.0", "--port", "9000"]
    assert "python" in main._format_cmd(["python", "a b.py"])

    class _Pipe:
        def __init__(self):
            self.lines = iter(["line1\n", ""])
        def readline(self):
            return next(self.lines)
        def close(self):
            return None

    log = []
    class _File:
        def write(self, text):
            log.append(text)
        def flush(self):
            return None

    main._stream_pipe(_Pipe(), _File(), "[stdout]", main.CYAN, True)
    assert any("line1" in x for x in log)
    assert "line1" in capsys.readouterr().out


def test_run_with_streaming_and_execute_command(monkeypatch, tmp_path):
    class _Proc:
        def __init__(self):
            self.stdout = SimpleNamespace(readline=lambda: "", close=lambda: None)
            self.stderr = SimpleNamespace(readline=lambda: "", close=lambda: None)
            self._code = 0
        def wait(self, timeout=None):
            _ = timeout
            return self._code
        def poll(self):
            return 0

    monkeypatch.setattr(main.subprocess, "Popen", lambda *a, **k: _Proc())
    code = main._run_with_streaming(["python", "x.py"], str(tmp_path / "child.log"))
    assert code == 0

    monkeypatch.setattr(main.subprocess, "run", lambda *a, **k: None)
    assert main.execute_command(["python", "x.py"], capture_output=False) == 0

    class _Called(main.subprocess.CalledProcessError):
        pass
    def _raise_called(*a, **k):
        raise main.subprocess.CalledProcessError(returncode=5, cmd="x")
    monkeypatch.setattr(main.subprocess, "run", _raise_called)
    assert main.execute_command(["python", "x.py"], capture_output=False) == 5


def test_execute_command_capture_and_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr(main, "_run_with_streaming", lambda *a, **k: 7)
    assert main.execute_command(["x"], capture_output=True) == 7

    def _raise_interrupt(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(main.subprocess, "run", _raise_interrupt)
    assert main.execute_command(["x"], capture_output=False) == 0


def test_run_wizard_and_main_quick_paths(monkeypatch):
    monkeypatch.setattr(main, "cfg", _LauncherCfg())
    monkeypatch.setattr(main, "print_banner", lambda: None)
    seq = iter(["web", "ollama", "full", "info", "0.0.0.0", "9000"])
    monkeypatch.setattr(main, "ask_choice", lambda *a, **k: next(seq))
    monkeypatch.setattr(main, "ask_text", lambda *a, **k: next(seq))
    monkeypatch.setattr(main, "preflight", lambda _p: None)
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _m: (True, None))
    monkeypatch.setattr(main, "confirm", lambda *a, **k: False)
    assert main.run_wizard() == 0

    seq2 = iter(["web", "ollama", "full", "info", "0.0.0.0", "9000"])
    monkeypatch.setattr(main, "ask_choice", lambda *a, **k: next(seq2))
    monkeypatch.setattr(main, "ask_text", lambda *a, **k: next(seq2))
    monkeypatch.setattr(main, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(main, "execute_command", lambda *a, **k: 3)
    assert main.run_wizard() == 3

    class _CfgBad(_LauncherCfg):
        def validate_critical_settings(self):
            return False

    monkeypatch.setattr(main, "cfg", _CfgBad())
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--quick", "cli"])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2

    monkeypatch.setattr(main, "cfg", _LauncherCfg())
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _m: (False, "x"))
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--quick", "cli"])
    with pytest.raises(SystemExit) as exc2:
        main.main()
    assert exc2.value.code == 2

    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _m: (True, None))
    monkeypatch.setattr(main, "execute_command", lambda *a, **k: 0)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--quick", "web", "--port", "9000"])
    with pytest.raises(SystemExit) as exc3:
        main.main()
    assert exc3.value.code == 0


def test_main_module_import_fallback_branch(monkeypatch):
    fake_config = types.ModuleType("config")
    class _BrokenConfig:
        def __init__(self):
            raise AttributeError("broken")
    fake_config.Config = _BrokenConfig
    monkeypatch.setitem(sys.modules, "config", fake_config)
    module = importlib.reload(main)
    assert hasattr(module, "cfg")
    assert module.CONFIG_IMPORT_OK is False
    monkeypatch.undo()
    importlib.reload(main)


def test_main_module_import_without_initialize_directories(monkeypatch):
    fake_config = types.ModuleType("config")
    class _CfgNoInit:
        pass
    fake_config.Config = _CfgNoInit
    monkeypatch.setitem(sys.modules, "config", fake_config)
    module = importlib.reload(main)
    assert module.CONFIG_IMPORT_OK is True
    monkeypatch.undo()
    importlib.reload(main)


def test_preflight_more_branches(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("X=1", encoding="utf-8")
    monkeypatch.setattr(main, "cfg", SimpleNamespace(BASE_DIR=str(tmp_path), DATABASE_URL="sqlite:///x", OLLAMA_URL="http://o/api"))

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, timeout):
            _ = timeout
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, _u):
            return _Resp()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(Client=_Client))
    main.preflight("ollama")
    out = capsys.readouterr().out
    assert ".env dosyası bulundu" in out
    assert "Ollama erişimi başarılı" in out

    monkeypatch.setitem(sys.modules, "httpx", None)
    main.preflight("ollama")
    assert "httpx" in capsys.readouterr().out

    class _BoomClient:
        def __init__(self, timeout):
            raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(Client=_BoomClient))
    main.preflight("ollama")
    assert "Ollama erişimi doğrulanamadı" in capsys.readouterr().out


def test_build_command_invalid_inputs_and_cli_non_ollama():
    with pytest.raises(ValueError):
        main.build_command("x", "ollama", "full", "info", {})
    with pytest.raises(ValueError):
        main.build_command("cli", "x", "full", "info", {})
    with pytest.raises(ValueError):
        main.build_command("cli", "ollama", "x", "info", {})
    with pytest.raises(ValueError):
        main.build_command("cli", "ollama", "full", "x", {})
    cmd = main.build_command("cli", "gemini", "full", "info", {"model": "ignored"})
    assert "--model" not in cmd


def test_stream_pipe_without_file_and_without_mirror(capsys):
    class _Pipe:
        def __init__(self):
            self.lines = iter(["line\n", ""])
        def readline(self):
            return next(self.lines)
        def close(self):
            return None
    main._stream_pipe(_Pipe(), None, "[x]", main.CYAN, False)
    assert capsys.readouterr().out == ""


def test_run_with_streaming_terminate_branch(monkeypatch):
    class _Proc:
        def __init__(self):
            self.stdout = SimpleNamespace(readline=lambda: "", close=lambda: None)
            self.stderr = SimpleNamespace(readline=lambda: "", close=lambda: None)
            self.terminated = False
            self.wait_calls = 0
        def wait(self, timeout=None):
            self.wait_calls += 1
            if timeout == 3:
                raise RuntimeError("still running")
            return 0
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
        def kill(self):
            self.terminated = True
    proc = _Proc()
    monkeypatch.setattr(main.subprocess, "Popen", lambda *a, **k: proc)
    assert main._run_with_streaming(["python", "x.py"], None) == 0
    assert proc.terminated is True


def test_run_wizard_runtime_not_ok_and_cli_model_branch(monkeypatch):
    monkeypatch.setattr(main, "cfg", _LauncherCfg())
    monkeypatch.setattr(main, "print_banner", lambda: None)
    seq = iter(["cli", "ollama", "full", "info", "model-x"])
    monkeypatch.setattr(main, "ask_choice", lambda *a, **k: next(seq))
    monkeypatch.setattr(main, "ask_text", lambda *a, **k: next(seq))
    monkeypatch.setattr(main, "preflight", lambda _p: None)
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _m: (False, "err"))
    assert main.run_wizard() == 2

    seq2 = iter(["cli", "gemini", "full", "info"])
    monkeypatch.setattr(main, "ask_choice", lambda *a, **k: next(seq2))
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _m: (True, None))
    monkeypatch.setattr(main, "confirm", lambda *a, **k: False)
    assert main.run_wizard() == 0


def test_execute_command_generic_exception_and_main_port_error(monkeypatch):
    def _raise_generic(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(main.subprocess, "run", _raise_generic)
    assert main.execute_command(["x"], capture_output=False) == 1

    monkeypatch.setattr(main, "cfg", _LauncherCfg())
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--quick", "web", "--port", "70000"])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2

    monkeypatch.setattr(main, "_run_with_streaming", lambda *a, **k: 0)
    assert main.execute_command(["x"], capture_output=True) == 0


def test_main_calls_init_telemetry(monkeypatch):
    calls = {"n": 0}
    class _Cfg(_LauncherCfg):
        def init_telemetry(self, service_name=None):
            calls["n"] += 1
    monkeypatch.setattr(main, "cfg", _Cfg())
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _m: (True, None))
    monkeypatch.setattr(main, "execute_command", lambda *a, **k: 0)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--quick", "cli"])
    with pytest.raises(SystemExit):
        main.main()
    assert calls["n"] == 1
