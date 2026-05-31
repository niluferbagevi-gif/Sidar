"""Alembic migration runner extracted from the database facade."""

from __future__ import annotations

from pathlib import Path


def run_alembic_upgrade_head(*, database_url: str, alembic_ini: Path, migrations_dir: Path) -> None:
    """Run Alembic to the latest revision for a configured database URL."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig(str(alembic_ini))
    alembic_cfg.set_main_option("script_location", str(migrations_dir))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_cfg, "head")


__all__ = ["run_alembic_upgrade_head"]
