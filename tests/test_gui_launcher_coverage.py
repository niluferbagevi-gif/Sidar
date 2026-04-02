from gui_launcher import _extra_args_for_mode, _normalize_selection, launch_from_gui


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


def test_launch_from_gui_success(monkeypatch):
    monkeypatch.setattr("gui_launcher.preflight", lambda *_: None)
    monkeypatch.setattr("gui_launcher.build_command", lambda *args, **kwargs: ["python", "cli.py"])
    monkeypatch.setattr("gui_launcher.execute_command", lambda *_: 0)

    result = launch_from_gui("cli", "ollama", "full", "info")
    assert result["status"] == "success"


def test_launch_from_gui_error(monkeypatch):
    monkeypatch.setattr("gui_launcher.preflight", lambda *_: None)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("bad-input")

    monkeypatch.setattr("gui_launcher.build_command", _boom)
    result = launch_from_gui("cli", "ollama", "full", "info")
    assert result["status"] == "error"
    assert result["return_code"] == 1
