# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from pathlib import Path


def test_migration_cutover_workflow_contains_required_gates():
    wf = Path('.github/workflows/migration-cutover-checks.yml').read_text(encoding='utf-8')
    assert 'alembic -x database_url="$DATABASE_URL" upgrade head' in wf
    assert 'alembic -x database_url="$DATABASE_URL" downgrade base' in wf
    assert 'scripts/migrate_sqlite_to_pg.py' in wf
    assert '--dry-run' in wf
    assert 'scripts/load_test_db_pool.py' in wf
    assert '--concurrency 50' in wf


def test_db_pool_load_script_has_expected_cli_args():
    script = Path('scripts/load_test_db_pool.py').read_text(encoding='utf-8')
    assert '--database-url' in script
    assert '--concurrency' in script
    assert '--requests' in script
    assert 'POOL_LOAD_TEST_OK' in script