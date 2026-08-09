"""Tests for pytest dotenv loading safety defaults."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._fixtures import dotenv


def test_pytest_dotenv_chain_does_not_load_real_keys_without_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """General pytest startup must not import user-private secret overlays."""
    keys_file = tmp_path / "sidar_keys.env"
    keys_file.write_text("SIDAR_REAL_SECRET_SENTINEL=from-real-keys\n", encoding="utf-8")

    monkeypatch.setattr(dotenv, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(keys_file))
    monkeypatch.delenv("SIDAR_TEST_LOAD_REAL_KEYS", raising=False)
    monkeypatch.delenv("SIDAR_REAL_SECRET_SENTINEL", raising=False)

    dotenv.load_pytest_dotenv_chain()

    assert "SIDAR_REAL_SECRET_SENTINEL" not in os.environ


@pytest.mark.parametrize("truthy", ["1", "true", "yes"])
def test_pytest_dotenv_chain_loads_real_keys_only_with_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, truthy: str
) -> None:
    """Secret-chain tests may opt into a temporary keys file explicitly."""
    keys_file = tmp_path / "sidar_keys.env"
    keys_file.write_text("SIDAR_REAL_SECRET_SENTINEL=from-real-keys\n", encoding="utf-8")

    monkeypatch.setattr(dotenv, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(keys_file))
    monkeypatch.setenv("SIDAR_TEST_LOAD_REAL_KEYS", truthy)
    monkeypatch.delenv("SIDAR_REAL_SECRET_SENTINEL", raising=False)

    dotenv.load_pytest_dotenv_chain()

    assert os.environ["SIDAR_REAL_SECRET_SENTINEL"] == "from-real-keys"


def test_installer_smoke_does_not_import_real_secret_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Large real secret files must not enter pytest env without explicit opt-in."""
    secret_file = tmp_path / ".sidar_keys.env"
    secret_file.write_text("OPENAI_API_KEY=" + ("x" * 200_000) + "\n", encoding="utf-8")

    monkeypatch.setattr(dotenv, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(secret_file))
    monkeypatch.delenv("SIDAR_TEST_LOAD_REAL_KEYS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    dotenv.load_pytest_dotenv_chain()

    assert "OPENAI_API_KEY" not in os.environ
