from agent.core.memory_hub import MemoryHub


def test_memory_hub_global_and_role_context_limits() -> None:
    hub = MemoryHub()

    hub.add_global("")
    hub.add_global("g1")
    hub.add_global("g2")
    hub.add_global("g3")

    hub.add_role_note("coder", "")
    hub.add_role_note("coder", "r1")
    hub.add_role_note("coder", "r2")

    assert hub.global_context(limit=2) == ["g2", "g3"]
    assert hub.global_context(limit=0) == ["g3"]
    assert hub.role_context("coder", limit=2) == ["r1", "r2"]
    assert hub.role_context("unknown-role") == []


def test_memory_hub_async_aliases_delegate_to_sync_methods() -> None:
    hub = MemoryHub()

    hub.aadd_global("g")
    hub.aadd_role_note("reviewer", "r")

    assert hub.aglobal_context() == ["g"]
    assert hub.arole_context("reviewer") == ["r"]
