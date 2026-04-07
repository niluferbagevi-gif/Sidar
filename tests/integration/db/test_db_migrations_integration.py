from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_alembic_migrations_up_and_down(tmp_path, monkeypatch):
    """Run alembic migrations end-to-end on a temporary SQLite database."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{db_path}"

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))

    command.upgrade(alembic_cfg, "head")
    assert db_path.exists(), "SQLite database file should be created after upgrade."

    engine = create_engine(db_url)
    try:
        upgraded_tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "alembic_version" in upgraded_tables
    assert len(upgraded_tables) > 1, "Expected schema tables to exist after upgrade."

    command.downgrade(alembic_cfg, "base")

    downgraded_engine = create_engine(db_url)
    try:
        downgraded_tables = set(inspect(downgraded_engine).get_table_names())
    finally:
        downgraded_engine.dispose()

    assert "alembic_version" not in downgraded_tables
    assert not downgraded_tables, "Expected empty schema after downgrade to base."
