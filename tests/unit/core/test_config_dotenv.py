from __future__ import annotations

from core import config_dotenv


def test_config_dotenv_parse_and_resolve_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    dotenv_file = tmp_path / "sample.env"
    dotenv_file.write_text(
        "# comment\nexport FOO='bar'\nBAD KEY=x\nEMPTY=\"\"\nPLAIN=value\n",
        encoding="utf-8",
    )

    assert config_dotenv.parse_dotenv_source_values(dotenv_file) == {
        "FOO": "bar",
        "EMPTY": "",
        "PLAIN": "value",
    }
    assert config_dotenv.resolve_dotenv_path("relative.env", base_dir=tmp_path) == tmp_path / "relative.env"
    assert config_dotenv.resolve_dotenv_path("~/secret.env", base_dir=tmp_path) == tmp_path / "secret.env"


def test_config_dotenv_tracking_and_reset_helpers(tmp_path):
    env = {"EXISTING": "original", "NEW": "value"}
    managed: set[str] = set()
    originals: dict[str, str] = {}
    sources: dict[str, dict[str, object]] = {}

    config_dotenv.record_dotenv_key_sources(
        environ=env,
        managed_keys=managed,
        original_env_values=originals,
        key_sources=sources,
        label="test",
        path=tmp_path / ".env",
        override=True,
        parsed_values={"EXISTING": "changed", "NEW": "value"},
        before_values={"EXISTING": "original", "NEW": None},
    )

    assert managed == {"EXISTING", "NEW"}
    assert originals == {"EXISTING": "original"}
    assert sources["EXISTING"]["label"] == "test"

    config_dotenv.reset_dotenv_managed_environment(
        environ=env, managed_keys=managed, original_env_values=originals
    )

    assert env == {"EXISTING": "original"}
    assert managed == set()


def test_config_dotenv_event_reports_and_skip_flag(tmp_path, monkeypatch):
    events: list[dict[str, object]] = []
    missing: list[str] = []

    config_dotenv.record_dotenv_event(
        load_events=events,
        missing_file_notices=missing,
        label="missing",
        raw_path="missing.env",
        resolved_path=tmp_path / "missing.env",
        loaded=False,
        override=False,
        reason="missing",
    )

    assert config_dotenv.clone_dotenv_load_report(events)[0]["label"] == "missing"
    assert missing == [f"missing={tmp_path / 'missing.env'}"]
    assert config_dotenv.skip_default_dotenv_layers({"SIDAR_SKIP_DEFAULT_DOTENV": "yes"}) is True
    monkeypatch.delenv("SIDAR_SKIP_DEFAULT_DOTENV", raising=False)
    assert config_dotenv.skip_default_dotenv_layers() is False
