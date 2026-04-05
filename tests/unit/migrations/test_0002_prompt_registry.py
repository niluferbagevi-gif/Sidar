from tests.unit.migrations.migration_test_utils import FakeOp, load_migration


def test_0002_upgrade_and_downgrade_operations():
    mod = load_migration("0002_prompt_registry.py")
    fake_op = FakeOp()
    mod.op = fake_op

    mod.upgrade()
    assert ("create_table", "prompt_registry") in fake_op.calls
    assert any(call[0] == "execute" for call in fake_op.calls)

    mod.downgrade()
    assert ("drop_table", "prompt_registry") in fake_op.calls
