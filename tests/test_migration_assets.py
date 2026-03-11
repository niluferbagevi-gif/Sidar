from pathlib import Path


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
