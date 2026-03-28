from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from core.db import Database, _hash_password, _quote_sql_identifier, _verify_password


@dataclass
class _DummyConfig:
    DATABASE_URL: str
    BASE_DIR: Path
    DB_POOL_SIZE: int = 3
    DB_SCHEMA_VERSION_TABLE: str = "schema_versions"
    DB_SCHEMA_TARGET_VERSION: int = 1


def test_quote_sql_identifier_accepts_safe_identifiers():
    assert _quote_sql_identifier("schema_versions") == '"schema_versions"'


@pytest.mark.parametrize("identifier", ["", "123table", "invalid-name", "drop table users;"])
def test_quote_sql_identifier_rejects_invalid_identifiers(identifier):
    with pytest.raises(ValueError):
        _quote_sql_identifier(identifier)


def test_hash_and_verify_password_roundtrip():
    encoded = _hash_password("super-secret")

    assert encoded.startswith("pbkdf2_sha256$")
    assert _verify_password("super-secret", encoded) is True
    assert _verify_password("wrong-password", encoded) is False


def test_database_configures_sqlite_path_relative_to_base_dir(tmp_path):
    cfg = _DummyConfig(DATABASE_URL="sqlite+aiosqlite:///data/test.db", BASE_DIR=tmp_path)

    db = Database(cfg)

    assert db._backend == "sqlite"
    assert db._sqlite_path == tmp_path / "data" / "test.db"
    assert db._sqlite_path.parent.exists()


def test_database_configures_postgresql_backend(tmp_path):
    cfg = _DummyConfig(DATABASE_URL="postgresql://user:pass@localhost:5432/sidar", BASE_DIR=tmp_path)

    db = Database(cfg)

    assert db._backend == "postgresql"
    assert db._sqlite_path is None
