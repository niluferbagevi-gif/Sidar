from __future__ import annotations

import os

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
    assert (
        config_dotenv.resolve_dotenv_path("relative.env", base_dir=tmp_path)
        == tmp_path / "relative.env"
    )
    assert (
        config_dotenv.resolve_dotenv_path("~/secret.env", base_dir=tmp_path)
        == tmp_path / "secret.env"
    )


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
    assert config_dotenv.clone_dotenv_key_source_report({"KEY": {"label": "test"}}) == {
        "KEY": {"label": "test"}
    }
    assert config_dotenv.skip_default_dotenv_layers({"SIDAR_SKIP_DEFAULT_DOTENV": "yes"}) is True
    monkeypatch.delenv("SIDAR_SKIP_DEFAULT_DOTENV", raising=False)
    assert config_dotenv.skip_default_dotenv_layers() is False


def test_config_dotenv_parse_missing_file_and_non_override_tracking(tmp_path):
    missing_path = tmp_path / "missing.env"
    assert config_dotenv.parse_dotenv_source_values(missing_path) == {}

    env = {"KEPT": "original", "ADDED": "value"}
    managed: set[str] = set()
    originals: dict[str, str] = {}
    sources: dict[str, dict[str, object]] = {}

    config_dotenv.record_dotenv_key_sources(
        environ=env,
        managed_keys=managed,
        original_env_values=originals,
        key_sources=sources,
        label="non-override",
        path=tmp_path / ".env",
        override=False,
        parsed_values={"KEPT": "ignored", "ADDED": "value", "ABSENT": "value"},
        before_values={"KEPT": "original", "ADDED": None, "ABSENT": None},
    )

    assert managed == {"ADDED"}
    assert originals == {}
    assert "KEPT" not in sources
    assert sources["ADDED"]["override"] is False

    config_dotenv.record_dotenv_key_sources(
        environ=env,
        managed_keys=managed,
        original_env_values=originals,
        key_sources=sources,
        label="already-managed",
        path=tmp_path / ".env.second",
        override=True,
        parsed_values={"ADDED": "updated"},
        before_values={"ADDED": "value"},
    )

    assert originals == {}
    assert sources["ADDED"]["label"] == "already-managed"


def test_load_dotenv_if_exists_records_empty_missing_and_loaded_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTENV_SAMPLE", raising=False)
    events: list[dict[str, object]] = []
    missing: list[str] = []
    managed: set[str] = set()
    originals: dict[str, str] = {}
    sources: dict[str, dict[str, object]] = {}

    assert (
        config_dotenv.load_dotenv_if_exists(
            "   ",
            base_dir=tmp_path,
            environ=os.environ,
            load_events=events,
            missing_file_notices=missing,
            managed_keys=managed,
            original_env_values=originals,
            key_sources=sources,
            override=False,
            label="empty",
        )
        is None
    )
    assert events[-1]["reason"] == "empty_path"

    assert (
        config_dotenv.load_dotenv_if_exists(
            "absent.env",
            base_dir=tmp_path,
            environ=os.environ,
            load_events=events,
            missing_file_notices=missing,
            managed_keys=managed,
            original_env_values=originals,
            key_sources=sources,
            override=False,
            label="missing",
        )
        is None
    )
    assert missing[-1] == f"missing={tmp_path / 'absent.env'}"

    missing_count = len(missing)
    assert (
        config_dotenv.load_dotenv_if_exists(
            "still-absent.env",
            base_dir=tmp_path,
            environ=os.environ,
            load_events=events,
            missing_file_notices=missing,
            managed_keys=managed,
            original_env_values=originals,
            key_sources=sources,
            override=False,
            label="optional-missing",
            record_missing=False,
        )
        is None
    )
    assert len(missing) == missing_count

    dotenv_file = tmp_path / ".env.loaded"
    dotenv_file.write_text("DOTENV_SAMPLE=loaded\n", encoding="utf-8")
    assert config_dotenv.load_dotenv_if_exists(
        ".env.loaded",
        base_dir=tmp_path,
        environ=os.environ,
        load_events=events,
        missing_file_notices=missing,
        managed_keys=managed,
        original_env_values=originals,
        key_sources=sources,
        override=True,
        label="loaded",
    ) == dotenv_file

    assert os.environ["DOTENV_SAMPLE"] == "loaded"
    assert "DOTENV_SAMPLE" in managed
    assert sources["DOTENV_SAMPLE"]["label"] == "loaded"


def test_load_dotenv_into_effective_env_and_reload_baseline(tmp_path):
    events: list[dict[str, object]] = []
    missing: list[str] = []
    managed: set[str] = {"MANAGED"}
    originals: dict[str, str] = {}
    sources: dict[str, dict[str, object]] = {}
    effective_env = {"MANAGED": "from-old-dotenv", "KEPT": "original"}

    assert (
        config_dotenv.load_dotenv_into_effective_env(
            effective_env,
            "missing.env",
            base_dir=tmp_path,
            load_events=events,
            missing_file_notices=missing,
            managed_keys=managed,
            original_env_values=originals,
            key_sources=sources,
            override=False,
            label="missing",
        )
        is None
    )
    assert events[-1]["reason"] == "missing"

    dotenv_file = tmp_path / ".env.reload"
    assert (
        config_dotenv.load_dotenv_into_effective_env(
            effective_env,
            "   ",
            base_dir=tmp_path,
            load_events=events,
            missing_file_notices=missing,
            managed_keys=managed,
            original_env_values=originals,
            key_sources=sources,
            override=False,
            label="empty",
        )
        is None
    )
    assert events[-1]["reason"] == "empty_path"

    dotenv_file.write_text("KEPT=dotenv\nNEW=value\nIGNORED_KEY\n", encoding="utf-8")
    assert config_dotenv.load_dotenv_into_effective_env(
        effective_env,
        ".env.reload",
        base_dir=tmp_path,
        load_events=events,
        missing_file_notices=missing,
        managed_keys=managed,
        original_env_values=originals,
        key_sources=sources,
        override=False,
        label="reload",
    ) == dotenv_file

    assert effective_env["KEPT"] == "original"
    assert effective_env["NEW"] == "value"
    assert sources["NEW"]["label"] == "reload"
    assert config_dotenv.dotenv_reload_baseline_environment(
        environ=effective_env, managed_keys=managed
    ) == {"KEPT": "original"}
