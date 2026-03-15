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