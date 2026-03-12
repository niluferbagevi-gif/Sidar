import sqlite3
import sys
import types
from importlib import util
from pathlib import Path

import pytest


def test_alembic_baseline_assets_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "alembic.ini").exists()
    assert (root / "migrations" / "env.py").exists()
    assert (root / "migrations" / "versions" / "0001_baseline_schema.py").exists()


def test_cutover_playbook_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    playbook = root / "runbooks" / "production-cutover-playbook.md"
    assert playbook.exists()
    content = playbook.read_text(encoding="utf-8")
    assert "SQLite -> PostgreSQL" in content
    assert "rollback" in content.lower()


def test_alembic_upgrade_head_creates_schema(tmp_path: Path) -> None:
    alembic = pytest.importorskip("alembic")
    assert alembic is not None

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "alembic_test.db"

    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(cfg, "head")

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "users" in tables
    assert "sessions" in tables
    assert "messages" in tables
    assert "schema_versions" in tables
    assert "alembic_version" in tables


def test_alembic_downgrade_base_drops_schema(tmp_path: Path) -> None:
    alembic = pytest.importorskip("alembic")
    assert alembic is not None

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "alembic_downgrade_test.db"

    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "users" not in tables
    assert "auth_tokens" not in tables
    assert "user_quotas" not in tables
    assert "provider_usage_daily" not in tables
    assert "sessions" not in tables
    assert "messages" not in tables
    assert "schema_versions" not in tables


def test_migrations_env_load_database_url_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = Path(__file__).resolve().parents[1] / "migrations" / "env.py"

    class DummyConfig:
        config_file_name = None
        config_ini_section = "alembic"

        @staticmethod
        def get_main_option(_: str) -> str:
            return "sqlite:///fallback.db"

        @staticmethod
        def get_section(_: str) -> dict[str, str]:
            return {"sqlalchemy.url": "sqlite:///fallback.db"}

    class DummyContext:
        config = DummyConfig()

        def __init__(self) -> None:
            self.x_args: dict[str, str] = {}

        def get_x_argument(self, as_dictionary: bool = False) -> dict[str, str]:
            assert as_dictionary is True
            return self.x_args

        @staticmethod
        def configure(**_: object) -> None:
            return None

        class _Tx:
            def __enter__(self) -> None:
                return None

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                return False

        @staticmethod
        def begin_transaction() -> "DummyContext._Tx":
            return DummyContext._Tx()

        @staticmethod
        def run_migrations() -> None:
            return None

        @staticmethod
        def is_offline_mode() -> bool:
            return True

    dummy_context = DummyContext()
    alembic_module = types.ModuleType("alembic")
    alembic_module.context = dummy_context

    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_module.engine_from_config = lambda *args, **kwargs: object()
    sqlalchemy_module.pool = types.SimpleNamespace(NullPool=object())

    monkeypatch.setitem(sys.modules, "alembic", alembic_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_module)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    spec = util.spec_from_file_location("test_migrations_env_module", env_path)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)

    dummy_context.x_args = {"database_url": "postgresql://from-x-arg"}
    assert module._load_database_url() == "postgresql://from-x-arg"

    dummy_context.x_args = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-env")
    assert module._load_database_url() == "postgresql://from-env"

    monkeypatch.setenv("DATABASE_URL", "   ")
    assert module._load_database_url() is None
