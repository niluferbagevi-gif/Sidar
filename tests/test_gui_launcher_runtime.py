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
