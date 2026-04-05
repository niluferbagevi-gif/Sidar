from tests.unit.migrations.migration_test_utils import FakeOp, load_migration


def test_0003_upgrade_and_downgrade_operations():
    mod = load_migration("0003_audit_trail.py")
    fake_op = FakeOp()
    mod.op = fake_op

    mod.upgrade()
    assert ("create_table", "audit_logs") in fake_op.calls

    mod.downgrade()
    assert ("drop_table", "audit_logs") in fake_op.calls
