from tests.unit.migrations.migration_test_utils import FakeOp, load_migration


def test_0001_upgrade_and_downgrade_operations():
    mod = load_migration("0001_baseline_schema.py")
    fake_op = FakeOp()
    mod.op = fake_op

    mod.upgrade()
    created_tables = [call[1] for call in fake_op.calls if call[0] == "create_table"]
    assert "users" in created_tables
    assert "messages" in created_tables

    mod.downgrade()
    dropped_tables = [call[1] for call in fake_op.calls if call[0] == "drop_table"]
    assert "users" in dropped_tables
    assert "schema_versions" in dropped_tables
