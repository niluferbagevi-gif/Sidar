import importlib.util
import subprocess
import sys
import types
from pathlib import Path


def _load_main_module():
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        AI_PROVIDER = "ollama"
        ACCESS_LEVEL = "full"
        WEB_HOST = "0.0.0.0"
        WEB_PORT = 7860
        CODING_MODEL = "qwen"
        GEMINI_API_KEY = ""
        OLLAMA_URL = "http://localhost:11434/api"
        BASE_DIR = "."

        @staticmethod
        def initialize_directories():
            return None

    cfg_mod.Config = _Cfg
    sys.modules["config"] = cfg_mod

    spec = importlib.util.spec_from_file_location("main_under_test", Path("main.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


MAIN = _load_main_module()


def test_build_command_and_format_cmd():
    cmd_web = MAIN.build_command("web", "ollama", "full", "info", {"host": "127.0.0.1", "port": "7860"})
    assert "web_server.py" in cmd_web
    assert "--host" in cmd_web and "7860" in cmd_web

    cmd_cli = MAIN.build_command("cli", "ollama", "sandbox", "debug", {"model": "qwen2.5"})
    assert "cli.py" in cmd_cli
    assert "--model" in cmd_cli

    formatted = MAIN._format_cmd(["python", "a b.py", "--x", "1"])
    assert "'a b.py'" in formatted


def test_confirm_ask_text_and_ask_choice(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "")
    assert MAIN.confirm("devam?") is True

    monkeypatch.setattr("builtins.input", lambda _p: "n")
    assert MAIN.confirm("devam?") is False

    monkeypatch.setattr("builtins.input", lambda _p: "")
    assert MAIN.ask_text("Model", "qwen") == "qwen"

    seq = iter(["x", "", "2"])
    monkeypatch.setattr("builtins.input", lambda _p: next(seq))
    val = MAIN.ask_choice("Seç", {"1": ("A", "a"), "2": ("B", "b")}, "1")
    assert val in {"a", "b"}


def test_preflight_ollama_and_gemini_paths(monkeypatch, tmp_path):
    MAIN.cfg.BASE_DIR = str(tmp_path)

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, timeout=2):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            assert "tags" in url
            return _Resp()

    sys.modules["httpx"] = types.SimpleNamespace(Client=_Client)
    MAIN.preflight("ollama")

    MAIN.cfg.GEMINI_API_KEY = ""
    MAIN.preflight("gemini")


def test_run_with_streaming_and_execute_command(monkeypatch, tmp_path):
    class _Pipe:
        def __init__(self, lines):
            self._lines = iter(lines)

        def readline(self):
            return next(self._lines, "")

        def close(self):
            return None

    class _Proc:
        def __init__(self):
            self.stdout = _Pipe(["ok\n", ""])
            self.stderr = _Pipe(["warn\n", ""])

        def wait(self):
            return 0

    monkeypatch.setattr(MAIN.subprocess, "Popen", lambda *a, **k: _Proc())
    log_path = tmp_path / "child.log"
    rc = MAIN._run_with_streaming(["python", "x.py"], str(log_path))
    assert rc == 0
    assert log_path.exists()

    monkeypatch.setattr(MAIN.subprocess, "run", lambda *a, **k: None)
    assert MAIN.execute_command(["python", "x.py"]) == 0

    def _raise_called(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=7, cmd=args[0])

    monkeypatch.setattr(MAIN.subprocess, "run", _raise_called)
    assert MAIN.execute_command(["python", "x.py"]) == 7


def test_run_wizard_and_main_quick(monkeypatch):
    monkeypatch.setattr(MAIN, "print_banner", lambda: None)
    monkeypatch.setattr(MAIN, "ask_choice", lambda *a, **k: "web" if "arayüz" in a[0] else "ollama")

    def _ask_choice(prompt, *args, **kwargs):
        if "arayüz" in prompt:
            return "web"
        if "Sağlayıcısı" in prompt:
            return "ollama"
        if "Güvenlik" in prompt:
            return "full"
        return "info"

    monkeypatch.setattr(MAIN, "ask_choice", _ask_choice)
    monkeypatch.setattr(MAIN, "ask_text", lambda *a, **k: "7860" if "Port" in a[0] else "0.0.0.0")
    monkeypatch.setattr(MAIN, "preflight", lambda provider: None)
    monkeypatch.setattr(MAIN, "confirm", lambda *a, **k: False)
    assert MAIN.run_wizard() == 0

    monkeypatch.setattr(MAIN, "execute_command", lambda *a, **k: 0)
    monkeypatch.setattr(sys, "argv", ["main.py", "--quick", "cli", "--provider", "ollama", "--level", "full", "--log", "INFO"])
    try:
        MAIN.main()
    except SystemExit as exc:
        assert exc.code == 0