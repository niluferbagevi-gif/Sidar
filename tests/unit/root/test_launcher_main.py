from types import SimpleNamespace

import pytest

import main as launcher


def test_safe_helpers_normalize_values() -> None:
    assert launcher._safe_choice(" FULL ", "restricted", {"full", "restricted"}) == "full"
    assert launcher._safe_choice("bad", "restricted", {"full", "restricted"}) == "restricted"
    assert launcher._safe_text("  value  ", "fallback") == "value"
    assert launcher._safe_text("   ", "fallback") == "fallback"
    assert launcher._safe_port("7860") == "7860"
    assert launcher._safe_port("65536", default="8000") == "8000"
    assert launcher._safe_port("not-int", default="8000") == "8000"


def test_validate_runtime_dependencies_respects_config_import_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "CONFIG_IMPORT_OK", True)
    assert launcher.validate_runtime_dependencies("web") == (True, None)

    monkeypatch.setattr(launcher, "CONFIG_IMPORT_OK", False)
    ok, msg = launcher.validate_runtime_dependencies("cli")
    assert ok is False
    assert "cli.py" in str(msg)


def test_build_command_for_cli_and_web_modes() -> None:
    cli_cmd = launcher.build_command(
        "cli", "ollama", "full", "info", {"model": "qwen2.5-coder:14b"}
    )
    assert "cli.py" in cli_cmd
    assert "--model" in cli_cmd

    web_cmd = launcher.build_command(
        "web", "openai", "sandbox", "debug", {"host": "127.0.0.1", "port": "9000"}
    )
    assert "web_server.py" in web_cmd
    assert web_cmd[-4:] == ["--host", "127.0.0.1", "--port", "9000"]


@pytest.mark.parametrize(
    "mode,provider,level,log",
    [
        ("bad", "ollama", "full", "info"),
        ("web", "bad", "full", "info"),
        ("web", "ollama", "bad", "info"),
        ("web", "ollama", "full", "bad"),
    ],
)
def test_build_command_rejects_invalid_inputs(mode: str, provider: str, level: str, log: str) -> None:
    with pytest.raises(ValueError):
        launcher.build_command(mode, provider, level, log, {})


def test_main_quick_mode_uses_cfg_defaults_and_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        launcher.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            quick="cli",
            provider=None,
            level=None,
            model=None,
            host=None,
            port=None,
            log="INFO",
            capture_output=True,
            child_log="logs/child.log",
        ),
    )
    monkeypatch.setattr(launcher, "validate_runtime_dependencies", lambda mode: (True, None))

    captured = {}

    def _fake_execute(cmd, capture_output=False, child_log_path=None):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["child_log_path"] = child_log_path
        return 7

    monkeypatch.setattr(launcher, "execute_command", _fake_execute)
    monkeypatch.setattr(
        launcher,
        "cfg",
        SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            CODING_MODEL="qwen2.5-coder:7b",
            WEB_HOST="0.0.0.0",
            WEB_PORT=7860,
            validate_critical_settings=lambda: True,
        ),
    )

    with pytest.raises(SystemExit) as exc:
        launcher.main()

    assert exc.value.code == 7
    assert "cli.py" in captured["cmd"]
    assert captured["capture_output"] is True
    assert captured["child_log_path"] == "logs/child.log"


def test_main_fails_when_critical_validation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        launcher.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            quick="web",
            provider="openai",
            level="full",
            model=None,
            host="127.0.0.1",
            port="8080",
            log="info",
            capture_output=False,
            child_log=None,
        ),
    )
    monkeypatch.setattr(
        launcher,
        "cfg",
        SimpleNamespace(validate_critical_settings=lambda: False),
    )

    with pytest.raises(SystemExit) as exc:
        launcher.main()

    assert exc.value.code == 2
