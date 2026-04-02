from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


_DB_MODULE_PATH = Path(__file__).resolve().parents[2] / "core/db.py"


def _load_db_module_with_jwt_stub():
    jwt_mod = types.ModuleType("jwt")

    class _PyJWTError(Exception):
        pass

    jwt_mod.PyJWTError = _PyJWTError
    jwt_mod.encode = lambda payload, _secret, algorithm="HS256": f"{algorithm}:{payload.get('sub', '')}"
    jwt_mod.decode = lambda *_args, **_kwargs: {"sub": "1", "username": "stub"}
    sys.modules.setdefault("jwt", jwt_mod)

    spec = importlib.util.spec_from_file_location("db_under_test", _DB_MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_password_hash_and_verify_roundtrip() -> None:
    db_mod = _load_db_module_with_jwt_stub()

    encoded = db_mod._hash_password("s3cret")

    assert encoded.startswith("pbkdf2_sha256$")
    assert db_mod._verify_password("s3cret", encoded) is True
    assert db_mod._verify_password("wrong", encoded) is False
    assert db_mod._verify_password("s3cret", "invalid") is False


def test_quote_sql_identifier_validates_and_quotes() -> None:
    db_mod = _load_db_module_with_jwt_stub()

    assert db_mod._quote_sql_identifier("schema_versions") == '"schema_versions"'

    try:
        db_mod._quote_sql_identifier("bad-name")
    except ValueError as exc:
        assert "Invalid SQL identifier" in str(exc)
    else:
        raise AssertionError("Expected invalid SQL identifier to raise ValueError")


def test_database_configures_sqlite_relative_path(tmp_path: Path) -> None:
    db_mod = _load_db_module_with_jwt_stub()
    cfg = types.SimpleNamespace(
        DATABASE_URL="sqlite+aiosqlite:///nested/sidar.db",
        BASE_DIR=tmp_path,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        DB_POOL_SIZE=1,
    )

    db = db_mod.Database(cfg)

    assert db._backend == "sqlite"
    assert db._sqlite_path == (tmp_path / "nested/sidar.db")
    assert db._sqlite_path.parent.exists()
