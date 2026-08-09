"""Dotenv loading and PostgreSQL parity checks for pytest startup."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_pytest_dotenv_chain() -> None:
    """Load the runtime dotenv chain before pytest collection imports app modules."""
    base_env_path = PROJECT_ROOT / ".env"
    advanced_env_path = PROJECT_ROOT / ".env.advanced"
    profile_env_path = PROJECT_ROOT / f".env.{os.getenv('SIDAR_ENV', '').strip()}"

    # config.py ile aynı temel önceliği koru: .env ve .env.advanced mevcut
    # process ortamını ezmez; profil/explicit dosyaları bilinçli override eder.
    # Testlerde secret overlay yalnız SIDAR_TEST_LOAD_REAL_KEYS opt-in ile yüklenir.
    load_dotenv(dotenv_path=base_env_path, override=False)
    load_dotenv(dotenv_path=advanced_env_path, override=False)
    if profile_env_path.name != ".env." and profile_env_path.exists():
        load_dotenv(dotenv_path=profile_env_path, override=True)

    explicit_dotenv = os.getenv("DOTENV_FILE", "").strip()
    if explicit_dotenv:
        explicit_path = Path(explicit_dotenv).expanduser()
        if not explicit_path.is_absolute():
            explicit_path = PROJECT_ROOT / explicit_path
        load_dotenv(dotenv_path=explicit_path, override=True)

    load_real_keys = os.getenv("SIDAR_TEST_LOAD_REAL_KEYS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    keys_file = os.getenv("SIDAR_KEYS_FILE", "").strip()
    if load_real_keys and keys_file:
        load_dotenv(dotenv_path=Path(keys_file).expanduser(), override=True)


def read_dotenv_assignment(dotenv_path: Path, key: str) -> str:
    """Return a parsed dotenv assignment value without mutating process env."""
    if not dotenv_path.is_file():
        return ""
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, raw_value = line.split("=", 1)
        if current_key.strip() != key:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


def _postgres_url_password(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    if not parsed.scheme.startswith("postgresql"):
        return ""
    return unquote(parsed.password or "")


def assert_test_dotenv_postgres_parity() -> None:
    """Fail early when .env.test would override runtime DB credentials."""
    base_env_path = PROJECT_ROOT / ".env"
    test_env_path = PROJECT_ROOT / ".env.test"
    if not base_env_path.is_file() or not test_env_path.is_file():
        return

    base_password = read_dotenv_assignment(base_env_path, "POSTGRES_PASSWORD")
    test_password = read_dotenv_assignment(test_env_path, "POSTGRES_PASSWORD")
    if base_password and test_password and base_password != test_password:
        pytest.fail(
            "PostgreSQL dotenv parity check failed before tests: "
            ".env.test içindeki POSTGRES_PASSWORD, .env içindeki POSTGRES_PASSWORD "
            "ile aynı değil. Smoke testler runtime PostgreSQL'e bağlanırken bu drift "
            "InvalidPasswordError üretebilir. Düzeltme: `uv run python "
            "scripts/sync_database_passwords.py --all-envs` veya `./install_sidar.sh "
            "--smoke-test` pre-smoke sync adımını çalıştırın.",
            pytrace=False,
        )

    base_database_url = read_dotenv_assignment(base_env_path, "DATABASE_URL")
    test_database_url = read_dotenv_assignment(test_env_path, "DATABASE_URL")
    base_url_password = _postgres_url_password(base_database_url)
    test_url_password = _postgres_url_password(test_database_url)
    if base_password and base_url_password and base_url_password != base_password:
        pytest.fail(
            "PostgreSQL dotenv parity check failed before tests: .env içindeki "
            "DATABASE_URL parolası POSTGRES_PASSWORD ile aynı değil. Önce "
            "`uv run python scripts/sync_database_passwords.py --all-envs` çalıştırın.",
            pytrace=False,
        )
    if base_password and test_url_password and test_url_password != base_password:
        pytest.fail(
            "PostgreSQL dotenv parity check failed before tests: .env.test içindeki "
            "DATABASE_URL parolası .env POSTGRES_PASSWORD ile aynı değil. Smoke testler "
            "yanlış parola ile runtime PostgreSQL'e bağlanabilir. Düzeltme: `uv run "
            "python scripts/sync_database_passwords.py --all-envs`.",
            pytrace=False,
        )
