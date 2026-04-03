from __future__ import annotations

import pytest

from gui_launcher import _extra_args_for_mode, _normalize_selection, launch_from_gui, start_gui, start_sidar


def test_normalize_selection_and_extra_args():
    out = _normalize_selection(" WEB ", " OLLAMA ", " FULL ", " DEBUG ")
    assert out == {
        "mode": "web",
        "provider": "ollama",
        "level": "full",
        "log_level": "debug",
    }
    assert _extra_args_for_mode("web") == {"host": "0.0.0.0", "port": "7860"}
    assert _extra_args_for_mode("cli") == {}


def test_normalize_selection_invalid_values_raise():
    with pytest.raises(ValueError):
        _normalize_selection("x", "ollama", "full", "info")
    with pytest.raises(ValueError):
        _normalize_selection("cli", "x", "full", "info")
    with pytest.raises(ValueError):
        _normalize_selection("cli", "ollama", "x", "info")
    with pytest.raises(ValueError):
        _normalize_selection("cli", "ollama", "full", "x")


def test_launch_from_gui_success(monkeypatch):
    monkeypatch.setattr("gui_launcher.preflight", lambda *_: None)
    monkeypatch.setattr("gui_launcher.build_command", lambda *args, **kwargs: ["python", "cli.py"])
    monkeypatch.setattr("gui_launcher.execute_command", lambda *_: 0)

    result = launch_from_gui("cli", "ollama", "full", "info")
    assert result["status"] == "success"


def test_launch_from_gui_nonzero_return(monkeypatch):
    monkeypatch.setattr("gui_launcher.preflight", lambda *_: None)
    monkeypatch.setattr("gui_launcher.build_command", lambda *args, **kwargs: ["python", "cli.py"])
    monkeypatch.setattr("gui_launcher.execute_command", lambda *_: 9)

    result = launch_from_gui("cli", "ollama", "full", "info")
    assert result["status"] == "error"
    assert result["return_code"] == 9


def test_launch_from_gui_error(monkeypatch):
    monkeypatch.setattr("gui_launcher.preflight", lambda *_: None)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("bad-input")

    monkeypatch.setattr("gui_launcher.build_command", _boom)
    result = launch_from_gui("cli", "ollama", "full", "info")
    assert result["status"] == "error"
    assert result["return_code"] == 1


def test_start_sidar_delegates(monkeypatch):
    monkeypatch.setattr("gui_launcher.launch_from_gui", lambda *args, **kwargs: {"status": "success", "return_code": 0})
    assert start_sidar("cli", "ollama", "full", "info")["status"] == "success"


def test_start_gui_import_error(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "eel":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(RuntimeError):
        start_gui()


def test_start_gui_happy_path(monkeypatch):
    class _Eel:
        def __init__(self):
            self.calls = []

        def init(self, directory):
            self.calls.append(("init", directory))

        def expose(self, fn):
            self.calls.append(("expose", fn.__name__))

        def start(self, page, **kwargs):
            self.calls.append(("start", page, kwargs))

    fake = _Eel()

    import builtins

    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "eel":
            return fake
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    start_gui()

    assert fake.calls[0][0] == "init"
    assert fake.calls[1] == ("expose", "start_sidar")
    assert fake.calls[2][0] == "start"
