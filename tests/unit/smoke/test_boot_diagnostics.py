"""Unit coverage for smoke boot diagnostics."""

from pathlib import Path

import pytest

import config
from tests.smoke import test_boot


@pytest.fixture(autouse=True)
def _reset_dotenv_managed_state() -> None:
    config._reset_dotenv_managed_environment()
    yield
    config._reset_dotenv_managed_environment()


@pytest.mark.xdist_group("env-globals")
def test_database_url_dotenv_diagnostics_reports_source_without_password(
    monkeypatch, tmp_path: Path
) -> None:
    dotenv_path = tmp_path / ".env.test"
    monkeypatch.setenv("SIDAR_ENV", "test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret-pass")
    monkeypatch.setattr(
        config,
        "get_dotenv_key_source_report",
        lambda: {
            "DATABASE_URL": {"label": "environment:test", "path": str(dotenv_path)},
            "POSTGRES_PASSWORD": {"label": "environment:test", "path": str(dotenv_path)},
        },
    )
    monkeypatch.setattr(
        config,
        "get_dotenv_load_report",
        lambda: [
            {"label": "base", "path": str(tmp_path / ".env"), "loaded": True},
            {"label": "environment:test", "path": str(dotenv_path), "loaded": True},
        ],
    )

    diagnostics = test_boot._database_url_dotenv_diagnostics(
        "postgresql://sidar:super-secret-pass@127.0.0.1:5432/sidar"
    )

    assert "SIDAR_ENV='test'" in diagnostics
    assert "DATABASE_URL_SOURCE=environment:test" in diagnostics
    assert f"DATABASE_URL_DOTENV_PATH={dotenv_path}" in diagnostics
    assert "POSTGRES_PASSWORD_SOURCE=environment:test" in diagnostics
    assert f"POSTGRES_PASSWORD_DOTENV_PATH={dotenv_path}" in diagnostics
    assert "POSTGRES_PASSWORD_HASH=sha256:" in diagnostics
    assert "host=127.0.0.1" in diagnostics
    assert "database=sidar" in diagnostics
    assert "password_hash=sha256:" in diagnostics
    assert "super-secret-pass" not in diagnostics
