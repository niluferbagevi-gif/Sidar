from __future__ import annotations

import argparse
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from launcher import cli_args, env_reload, preflight, session, wizard


def test_wizard_default_keys_prefer_last_selection_over_config():
    cfg = SimpleNamespace(AI_PROVIDER="gemini", ACCESS_LEVEL="sandbox")
    last = {"mode": "cli", "provider": "anthropic", "level": "restricted", "log": "error"}

    assert wizard.wizard_default_keys(last, cfg=cfg) == {
        "mode": "2",
        "provider": "4",
        "level": "3",
        "log": "3",
    }


def test_wizard_default_keys_fall_back_to_config_and_safe_defaults():
    cfg = SimpleNamespace(AI_PROVIDER="not-a-provider", ACCESS_LEVEL="sandbox")

    assert wizard.wizard_default_keys(None, cfg=cfg) == {
        "mode": "1",
        "provider": "1",
        "level": "2",
        "log": "1",
    }


def test_last_extra_args_returns_saved_mapping_only_when_present():
    assert wizard.last_extra_args(None) == {}
    assert wizard.last_extra_args({"extra_args": "bad"}) == {}
    assert wizard.last_extra_args({"extra_args": {}}) == {}
    assert wizard.last_extra_args({"extra_args": {"port": "9000"}}) == {"port": "9000"}


def test_build_arg_parser_mentions_session_file_and_parses_flags():
    parser = cli_args.build_arg_parser(session_filename=".custom_session.json")

    assert ".custom_session.json" in parser.format_help()
    args = parser.parse_args(["--quick", "web", "--port", "8080", "-y"])
    assert (args.quick, args.port, args.yes, args.log) == ("web", "8080", True, "info")


@pytest.mark.parametrize("value", ["1", "TRUE", " yes ", "on"])
def test_use_last_from_env_accepts_truthy_values(monkeypatch, value):
    monkeypatch.setenv("SIDAR_LAUNCHER_USE_LAST", value)
    assert cli_args.use_last_from_env() is True


def test_use_last_from_env_defaults_to_false(monkeypatch):
    monkeypatch.delenv("SIDAR_LAUNCHER_USE_LAST", raising=False)
    assert cli_args.use_last_from_env() is False


@pytest.mark.parametrize("port", ["0", "65536", "abc"])
def test_validate_port_argument_rejects_out_of_range_or_non_integer(port):
    parser = argparse.ArgumentParser()
    with pytest.raises(SystemExit):
        cli_args.validate_port_argument(parser, port)


def test_validate_port_argument_accepts_valid_or_missing_port():
    parser = argparse.ArgumentParser()
    cli_args.validate_port_argument(parser, None)
    cli_args.validate_port_argument(parser, "65535")


def test_warn_missing_provider_api_key_only_warns_for_empty_cloud_keys(capsys):
    logger = logging.getLogger("test-launcher-preflight")

    preflight.warn_missing_provider_api_key(
        "openai", SimpleNamespace(OPENAI_API_KEY=""), logger_obj=logger
    )
    preflight.warn_missing_provider_api_key(
        "gemini", SimpleNamespace(GEMINI_API_KEY="set"), logger_obj=logger
    )
    preflight.warn_missing_provider_api_key("ollama", SimpleNamespace(), logger_obj=logger)

    out = capsys.readouterr().out
    assert "OPENAI_API_KEY boş görünüyor" in out
    assert "GEMINI_API_KEY" not in out


def test_parse_env_source_file_handles_export_quotes_and_invalid_lines(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nexport A='1'\nB=\"two\"\nBAD KEY=x\nnoequals\nC= 3 \n", encoding="utf-8"
    )

    assert env_reload.parse_env_source_file(env_file) == {"A": "1", "B": "two", "C": "3"}
    assert env_reload.parse_env_source_file(tmp_path / "missing.env") == {}


def test_session_round_trip_normalizes_and_rejects_other_versions(tmp_path: Path):
    path = tmp_path / ".sidar_session.json"
    logger = logging.getLogger("test-launcher-session")

    def normalize(selection):
        return {**selection, "normalized": True}

    session.save_session({"mode": "web"}, path, normalize=normalize, version=1)

    assert session.load_session(path, normalize=normalize, version=1, logger_obj=logger) == {
        "mode": "web",
        "normalized": True,
    }
    assert session.load_session(path, normalize=normalize, version=2, logger_obj=logger) is None
    assert (path.stat().st_mode & 0o777) == 0o600
