from tests.unit.migrations.migration_test_utils import FakeOp, load_migration


def test_0004_upgrade_and_downgrade_operations():
    mod = load_migration("0004_faz_e_tables.py")
    fake_op = FakeOp()
    mod.op = fake_op

    mod.upgrade()
    created = [call[1] for call in fake_op.calls if call[0] == "create_table"]
    assert "marketing_campaigns" in created
    assert "coverage_findings" in created

    mod.downgrade()
    dropped = [call[1] for call in fake_op.calls if call[0] == "drop_table"]
    assert "marketing_campaigns" in dropped
    assert "coverage_findings" in dropped
