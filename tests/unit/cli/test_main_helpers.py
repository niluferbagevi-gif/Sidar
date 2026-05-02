"""Unit tests for launcher helper functions in main.py."""

from __future__ import annotations

import pytest

import main
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


def test_main_quick_mode_executes_built_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--quick", "cli", "--provider", "ollama", "--level", "full"],
    )
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))

    seen: dict[str, object] = {}

    def fake_execute(cmd: list[str], capture_output: bool = False, child_log_path: str | None = None) -> int:
        seen["cmd"] = cmd
        seen["capture"] = capture_output
        seen["child_log"] = child_log_path
        return 0

    monkeypatch.setattr(main, "execute_command", fake_execute)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
    assert isinstance(seen["cmd"], list)
    assert "cli.py" in seen["cmd"]
    assert seen["capture"] is False
    assert seen["child_log"] is None


def test_main_quick_mode_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--quick", "web", "--port", "70000"])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 2


def test_main_exits_when_runtime_dependencies_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--quick", "web", "--provider", "openai"])
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (False, "runtime error"))

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 2


def test_run_wizard_returns_2_when_runtime_dependencies_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "print_banner", lambda: None)
    choices = iter(["web", "openai", "full", "info"])
    monkeypatch.setattr(main, "ask_choice", lambda *args, **kwargs: next(choices))
    monkeypatch.setattr(main, "ask_text", lambda *args, **kwargs: "7860")
    monkeypatch.setattr(main, "preflight", lambda _provider: None)
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (False, "runtime boom"))

    rc = main.run_wizard()

    assert rc == 2


def test_execute_command_capture_output_nonzero(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(main, "_run_with_streaming", lambda _cmd, _log: 7)

    rc = main.execute_command(["python", "cli.py"], capture_output=True)
    out = capsys.readouterr().out

    assert rc == 7
    assert "Program hata ile sonlandı (Çıkış Kodu: 7)" in out


def test_execute_command_handles_called_process_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise main.subprocess.CalledProcessError(returncode=9, cmd=["python", "cli.py"])

    monkeypatch.setattr(main.subprocess, "run", _raise)

    rc = main.execute_command(["python", "cli.py"])

    assert rc == 9


def test_main_without_quick_runs_wizard_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py"])
    monkeypatch.setattr(main, "run_wizard", lambda: 5)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 5
