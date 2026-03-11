import sqlite3
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