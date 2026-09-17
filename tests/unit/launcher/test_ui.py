"""Tests for launcher UI logic kept outside the main entrypoint."""

from launcher import ui


def _colors() -> dict[str, str]:
    return {name: "" for name in ("yellow", "bold", "reset", "cyan", "green")}


def test_ask_choice_retries_and_uses_default(capsys) -> None:
    answers = iter(["invalid", ""])
    result = ui.ask_choice(
        "Mode",
        {"1": ("Web", "web")},
        "1",
        default_badge=None,
        input_fn=lambda _prompt: next(answers),
        magenta="",
        **_colors(),
    )
    assert result == "web"
    assert "Geçersiz seçim" in capsys.readouterr().out


def test_text_and_confirmation_defaults() -> None:
    colors = _colors()
    assert (
        ui.ask_text(
            "Model", "qwen2.5-coder:7b", default_badge=None, input_fn=lambda _: "", **colors
        )
        == "qwen2.5-coder:7b"
    )
    assert (
        ui.confirm(
            "Continue",
            True,
            input_fn=lambda _: "",
            **{k: colors[k] for k in ("yellow", "bold", "reset", "cyan")},
        )
        is True
    )
    assert (
        ui.confirm(
            "Continue",
            False,
            input_fn=lambda _: "evet",
            **{k: colors[k] for k in ("yellow", "bold", "reset", "cyan")},
        )
        is True
    )
