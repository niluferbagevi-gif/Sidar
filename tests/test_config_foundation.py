from __future__ import annotations

import config


def test_get_bool_env_parses_truthy_and_blank(monkeypatch):
    monkeypatch.setenv("FLAG_ENABLED", " yes ")
    monkeypatch.setenv("FLAG_BLANK", "   ")

    assert config.get_bool_env("FLAG_ENABLED", default=False) is True
    assert config.get_bool_env("FLAG_BLANK", default=True) is True
    assert config.get_bool_env("FLAG_MISSING", default=False) is False


def test_get_int_and_float_env_fallback_to_default(monkeypatch):
    monkeypatch.setenv("MAX_RETRY", "invalid")
    monkeypatch.setenv("THRESHOLD", "0.75")

    assert config.get_int_env("MAX_RETRY", default=5) == 5
    assert config.get_float_env("THRESHOLD", default=0.2) == 0.75


def test_get_list_env_splits_and_strips(monkeypatch):
    monkeypatch.setenv("ENABLED_MODULES", " core, db , ,api ")

    assert config.get_list_env("ENABLED_MODULES") == ["core", "db", "api"]
    assert config.get_list_env("MISSING_LIST", default=["default"]) == ["default"]
