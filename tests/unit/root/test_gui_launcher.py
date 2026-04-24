import importlib
import runpy
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest

import gui_launcher


def test_normalize_selection_happy_path_defaults_and_trim():
    result = gui_launcher._normalize_selection(" WEB ", " OpenAI ", " Full ", None)
    assert result == {
        "mode": "web",
        "provider": "openai",
        "level": "full",
        "log_level": "info",
    }


@pytest.mark.parametrize(
    ("mode", "provider", "level", "log_level", "expected_message"),
    [
        ("bad", "openai", "full", "info", "Geçersiz mode: bad"),
        ("web", "bad", "full", "info", "Geçersiz provider: bad"),
        ("web", "openai", "bad", "info", "Geçersiz level: bad"),
        ("web", "openai", "full", "bad", "Geçersiz log_level: bad"),
    ],
)
def test_normalize_selection_invalid_values_raise(mode, provider, level, log_level, expected_message):
    with pytest.raises(ValueError, match=expected_message):
        gui_launcher._normalize_selection(mode, provider, level, log_level)


def test_extra_args_for_mode_web_and_cli():
    web_args = gui_launcher._extra_args_for_mode("web")
    assert web_args == gui_launcher.DEFAULT_WEB_ARGS
    assert web_args is not gui_launcher.DEFAULT_WEB_ARGS

    assert gui_launcher._extra_args_for_mode("cli") == {}


def test_launch_from_gui_success(monkeypatch):
    captured = {}

    def fake_preflight(provider):
        captured["provider"] = provider

    def fake_build_command(mode, provider, level, log_level, extra):
        captured["build"] = (mode, provider, level, log_level, extra)
        return ["python", "main.py"]

    def fake_execute_command(cmd):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(gui_launcher, "preflight", fake_preflight)
    monkeypatch.setattr(gui_launcher, "build_command", fake_build_command)
    monkeypatch.setattr(gui_launcher, "execute_command", fake_execute_command)

    result = gui_launcher.launch_from_gui("web", "openai", "sandbox", "debug")

    assert result == {
        "status": "success",
        "message": "Sidar başarıyla başlatıldı.",
        "return_code": 0,
    }
    assert captured["provider"] == "openai"
    assert captured["build"] == (
        "web",
        "openai",
        "sandbox",
        "debug",
        {"host": "0.0.0.0", "port": "7860"},
    )
    assert captured["cmd"] == ["python", "main.py"]


def test_launch_from_gui_nonzero_return(monkeypatch):
    monkeypatch.setattr(gui_launcher, "preflight", lambda provider: None)
    monkeypatch.setattr(gui_launcher, "build_command", lambda *args, **kwargs: ["cmd"])
    monkeypatch.setattr(gui_launcher, "execute_command", lambda cmd: 7)

    result = gui_launcher.launch_from_gui("cli", "gemini", "restricted", "warning")

    assert result["status"] == "error"
    assert result["return_code"] == 7
    assert "Sidar hata kodu ile sonlandı: 7" in result["message"]


def test_launch_from_gui_exception_path(monkeypatch):
    def fake_preflight(_provider):
        raise RuntimeError("preflight fail")

    monkeypatch.setattr(gui_launcher, "preflight", fake_preflight)

    result = gui_launcher.launch_from_gui("web", "openai", "full", "info")

    assert result == {"status": "error", "message": "preflight fail", "return_code": 1}


def test_start_sidar_delegates(monkeypatch):
    monkeypatch.setattr(
        gui_launcher,
        "launch_from_gui",
        lambda mode, provider, level, log_level: {
            "status": f"{mode}-{provider}-{level}-{log_level}"
        },
    )

    result = gui_launcher.start_sidar("cli", "ollama", "sandbox", "error")

    assert result == {"status": "cli-ollama-sandbox-error"}


def test_start_gui_import_error(monkeypatch):
    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "eel":
            raise ImportError("missing eel")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert __import__("math").__name__ == "math"

    with pytest.raises(RuntimeError, match="Eel kurulu değil"):
        gui_launcher.start_gui()


def test_start_gui_happy_path(monkeypatch):
    fake_eel = types.SimpleNamespace()
    calls = {}

    def fake_init(path):
        calls["init"] = path

    def fake_expose(fn):
        calls["expose"] = fn

    def fake_start(page, size, position):
        calls["start"] = (page, size, position)

    fake_eel.init = fake_init
    fake_eel.expose = fake_expose
    fake_eel.start = fake_start

    monkeypatch.setitem(sys.modules, "eel", fake_eel)

    module = importlib.reload(gui_launcher)
    module.start_gui()

    assert calls["init"].endswith("launcher_gui")
    assert calls["expose"] is module.start_sidar
    assert calls["start"] == ("index.html", (980, 680), (220, 120))

    importlib.reload(gui_launcher)


def test_main_calls_start_gui(monkeypatch):
    called = {"start_gui": False}

    def fake_start_gui():
        called["start_gui"] = True

    monkeypatch.setattr(gui_launcher, "start_gui", fake_start_gui)

    gui_launcher.main()

    assert called["start_gui"] is True


def test_module_main_block_runs_entrypoint(monkeypatch):
    calls = {}
    fake_eel = types.SimpleNamespace(
        init=lambda path: calls.setdefault("init", path),
        expose=lambda fn: calls.setdefault("expose", fn.__name__),
        start=lambda *args, **kwargs: calls.setdefault("start", (args, kwargs)),
    )
    monkeypatch.setitem(sys.modules, "eel", fake_eel)

    runpy.run_module("gui_launcher", run_name="__main__")

    assert calls["init"].endswith("launcher_gui")
    assert calls["expose"] == "start_sidar"
    assert calls["start"][0] == ("index.html",)