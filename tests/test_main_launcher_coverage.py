from __future__ import annotations

import argparse
import builtins
import importlib
import sys
import types

import pytest


main = importlib.import_module("main")


def test_dummy_config_has_initialize_directories() -> None:
    dummy = main.DummyConfig()
    assert dummy.initialize_directories() is None


def test_run_wizard_runtime_dependency_block(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["1", "1", "1", "1", "", ""])  # web + ollama + full + info + host + port

    monkeypatch.setattr(main, "print_banner", lambda: None)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(answers))
    monkeypatch.setattr(main, "preflight", lambda _provider: None)
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (False, "blocked"))

    exit_code = main.run_wizard()
    assert exit_code == 2


def test_main_quick_mode_invalid_port_triggers_parser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: argparse.Namespace(
            quick="web",
            provider="ollama",
            level="full",
            model=None,
            host=None,
            port="99999",
            log="info",
            capture_output=False,
            child_log=None,
        ),
    )

    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2


def test_main_quick_mode_executes_command(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: argparse.Namespace(
            quick="cli",
            provider="ollama",
            level="sandbox",
            model="qwen",
            host=None,
            port=None,
            log="debug",
            capture_output=True,
            child_log="logs/child.log",
        ),
    )
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))

    def _fake_exec(cmd, capture_output=False, child_log_path=None):
        called["cmd"] = cmd
        called["capture_output"] = capture_output
        called["child_log_path"] = child_log_path
        return 0

    monkeypatch.setattr(main, "execute_command", _fake_exec)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
    assert called["capture_output"] is True
    assert called["child_log_path"] == "logs/child.log"
    assert "--model" in called["cmd"]


def test_import_falls_back_when_config_constructor_attribute_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_config = types.ModuleType("config")

    class _BrokenConfig:
        def __init__(self) -> None:
            raise AttributeError("broken")

    fake_config.Config = _BrokenConfig

    monkeypatch.setitem(sys.modules, "config", fake_config)

    reloaded = importlib.reload(main)
    assert reloaded.CONFIG_IMPORT_OK is False
    assert isinstance(reloaded.cfg, reloaded.DummyConfig)

    importlib.reload(main)
