"""Unit tests for the shared dotenv-scoped pydantic-settings subclass builder."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from core.config_scoped_settings import build_scoped_settings_type


class _SampleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    VALUE: int = 1


def test_build_scoped_settings_type_reads_the_given_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("VALUE=42\n", encoding="utf-8")

    scoped_type = build_scoped_settings_type(_SampleSettings, env_file=str(env_path))

    assert issubclass(scoped_type, _SampleSettings)
    assert scoped_type().VALUE == 42


def test_build_scoped_settings_type_defaults_env_ignore_empty_to_false(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("VALUE=\n", encoding="utf-8")

    scoped_type = build_scoped_settings_type(_SampleSettings, env_file=str(env_path))

    # Blank env values are not silently dropped unless env_ignore_empty=True is
    # requested -- pydantic-settings' own default, preserved so callers that
    # never opted in keep their pre-existing validation behavior.
    try:
        scoped_type()
    except Exception:  # noqa: BLE001 - pydantic ValidationError, asserted loosely on purpose.
        pass
    else:
        raise AssertionError("expected a validation error for a blank int field")


def test_build_scoped_settings_type_honors_env_ignore_empty(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("VALUE=\n", encoding="utf-8")

    scoped_type = build_scoped_settings_type(
        _SampleSettings, env_file=str(env_path), env_ignore_empty=True
    )

    assert scoped_type().VALUE == 1


def test_build_scoped_settings_type_names_the_subclass_after_its_base() -> None:
    scoped_type = build_scoped_settings_type(_SampleSettings, env_file="/nonexistent/.env")

    assert scoped_type.__name__ == "Scoped_SampleSettings"
    assert scoped_type.__module__ == _SampleSettings.__module__
