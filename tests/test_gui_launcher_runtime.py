from __future__ import annotations

import gui_launcher


def test_normalize_selection_valid_values() -> None:
    result = gui_launcher._normalize_selection("Web", "OLLAMA", "Sandbox", "DEBUG")

    assert result == {
        "mode": "web",
        "provider": "ollama",
        "level": "sandbox",
        "log_level": "debug",
    }


def test_normalize_selection_invalid_mode() -> None:
    try:
        gui_launcher._normalize_selection("desktop", "ollama", "full", "info")
        raise AssertionError("ValueError bekleniyordu")
    except ValueError as exc:
        assert "Geçersiz mode" in str(exc)


def test_extra_args_for_mode() -> None:
    assert gui_launcher._extra_args_for_mode("web") == {"host": "0.0.0.0", "port": "7860"}
    assert gui_launcher._extra_args_for_mode("cli") == {}

def test_launch_from_gui_success_and_error_paths(monkeypatch) -> None:
    monkeypatch.setattr(gui_launcher, "preflight", lambda _provider: None)
    monkeypatch.setattr(gui_launcher, "build_command", lambda *a, **k: ["python", "cli.py"])

    monkeypatch.setattr(gui_launcher, "execute_command", lambda _cmd: 0)
    ok = gui_launcher.launch_from_gui("web", "ollama", "sandbox", "info")
    assert ok["status"] == "success"
    assert ok["return_code"] == 0

    monkeypatch.setattr(gui_launcher, "execute_command", lambda _cmd: 3)
    err = gui_launcher.launch_from_gui("web", "ollama", "sandbox", "info")
    assert err["status"] == "error"
    assert err["return_code"] == 3


def test_start_gui_import_error(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "eel":
            raise ImportError("missing eel")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    try:
        gui_launcher.start_gui()
        raise AssertionError("RuntimeError bekleniyordu")
    except RuntimeError as exc:
        assert "Eel kurulu değil" in str(exc)

def test_normalize_selection_invalid_log_level() -> None:
    try:
        gui_launcher._normalize_selection("web", "ollama", "full", "trace")
        raise AssertionError("ValueError bekleniyordu")
    except ValueError as exc:
        assert "Geçersiz log_level" in str(exc)

def test_normalize_selection_invalid_provider_and_level() -> None:
    try:
        gui_launcher._normalize_selection("web", "unknown", "full", "info")
        raise AssertionError("ValueError bekleniyordu")
    except ValueError as exc:
        assert "Geçersiz provider" in str(exc)

    try:
        gui_launcher._normalize_selection("web", "ollama", "unsafe", "info")
        raise AssertionError("ValueError bekleniyordu")
    except ValueError as exc:
        assert "Geçersiz level" in str(exc)


def test_launch_from_gui_exception_path_and_start_sidar_wrapper(monkeypatch) -> None:
    def _boom(_provider):
        raise RuntimeError("preflight failed")

    monkeypatch.setattr(gui_launcher, "preflight", _boom)
    out = gui_launcher.launch_from_gui("web", "ollama", "sandbox", "info")
    assert out["status"] == "error"
    assert out["return_code"] == 1
    assert "preflight failed" in out["message"]

    monkeypatch.setattr(gui_launcher, "launch_from_gui", lambda *a, **k: {"status": "success", "message": "ok", "return_code": 0})
    wrapped = gui_launcher.start_sidar("web", "ollama", "sandbox", "info")
    assert wrapped["status"] == "success"


def test_start_gui_success_calls_eel_init_expose_and_start(monkeypatch) -> None:
    calls = {}

    class _Eel:
        @staticmethod
        def init(path):
            calls["init"] = path

        @staticmethod
        def expose(fn):
            calls["expose"] = fn.__name__

        @staticmethod
        def start(page, size=None, position=None):
            calls["start"] = (page, size, position)

    import sys
    monkeypatch.setitem(sys.modules, "eel", _Eel)

    gui_launcher.start_gui()

    assert calls["init"].endswith("launcher_gui")
    assert calls["expose"] == "start_sidar"
    assert calls["start"][0] == "index.html"


def test_gui_launcher_main_block_executes_start_gui(monkeypatch, tmp_path) -> None:
    import runpy
    import sys
    import types

    calls = {"started": False}

    fake_main = types.ModuleType("main")
    fake_main.build_command = lambda *a, **k: []
    fake_main.execute_command = lambda *_: 0
    fake_main.preflight = lambda *_: None
    monkeypatch.setitem(sys.modules, "main", fake_main)

    class _Eel:
        @staticmethod
        def init(_path):
            return None

        @staticmethod
        def expose(_fn):
            return None

        @staticmethod
        def start(*args, **kwargs):
            calls["started"] = True

    monkeypatch.setitem(sys.modules, "eel", _Eel)

    runpy.run_path("gui_launcher.py", run_name="__main__")
    assert calls["started"] is True
