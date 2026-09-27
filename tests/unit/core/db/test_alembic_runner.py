"""``core.db.alembic_runner`` modülü için unit testler."""

from core.db.alembic_runner import run_alembic_upgrade_head


def test_alembic_runner_exports_run_upgrade_callable():
    """Alembic runner exports run upgrade callable."""
    assert callable(run_alembic_upgrade_head)
