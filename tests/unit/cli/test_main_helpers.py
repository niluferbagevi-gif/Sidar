"""Unit tests for launcher helper functions in main.py."""

from __future__ import annotations

import pytest

from main import _safe_choice, _safe_port, _safe_text, build_command


def test_safe_choice_falls_back_for_invalid_inputs() -> None:
    allowed = {"web", "cli"}

    assert _safe_choice("web", default="cli", allowed=allowed) == "web"
    assert _safe_choice("unknown", default="cli", allowed=allowed) == "cli"
    assert _safe_choice(None, default="cli", allowed=allowed) == "cli"


def test_safe_text_and_port_normalization() -> None:
    assert _safe_text("  hello  ", default="x") == "hello"
    assert _safe_text("", default="x") == "x"

    assert _safe_port("7860") == "7860"
    assert _safe_port("70000") == "7860"
    assert _safe_port("abc") == "7860"


def test_build_command_for_web_and_cli_modes() -> None:
    web_cmd = build_command(
        mode="web",
        provider="ollama",
        level="full",
        log="info",
        extra_args={"host": "0.0.0.0", "port": "9000"},
    )
    assert web_cmd[-4:] == ["--host", "0.0.0.0", "--port", "9000"]

    cli_cmd = build_command(
        mode="cli",
        provider="ollama",
        level="full",
        log="debug",
        extra_args={"model": "qwen2.5-coder:7b"},
    )
    assert "--model" in cli_cmd
    assert "qwen2.5-coder:7b" in cli_cmd


def test_build_command_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError):
        build_command(
            mode="invalid",
            provider="ollama",
            level="full",
            log="info",
            extra_args={},
        )
