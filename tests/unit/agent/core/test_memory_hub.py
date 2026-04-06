from agent.core.memory_hub import MemoryHub, RoleMemory


def test_add_global_ignores_empty_and_returns_latest_with_limit() -> None:
    hub = MemoryHub()

    hub.add_global("")
    hub.add_global("n1")
    hub.add_global("n2")
    hub.add_global("n3")

    assert hub.global_context() == ["n1", "n2", "n3"]
    assert hub.global_context(limit=2) == ["n2", "n3"]
    assert hub.global_context(limit=0) == ["n3"]


def test_add_role_note_ignores_empty_and_creates_memory_for_missing_role() -> None:
    hub = MemoryHub()

    hub.add_role_note("reviewer", "")
    assert hub.role_context("reviewer") == []

    hub.add_role_note("reviewer", "r1")
    hub.add_role_note("reviewer", "r2")

    assert hub.role_context("reviewer") == ["r1", "r2"]
    assert hub.role_context("reviewer", limit=1) == ["r2"]
    assert hub.role_context("reviewer", limit=0) == ["r2"]


def test_add_role_note_replaces_unknown_default_memory() -> None:
    hub = MemoryHub()

    # defaultdict üzerinden erişim, role='unknown' ile placeholder üretir.
    _ = hub._role_notes["coder"]
    assert hub._role_notes["coder"].role == "unknown"

    hub.add_role_note("coder", "first note")

    assert hub._role_notes["coder"].role == "coder"
    assert hub.role_context("coder") == ["first note"]


def test_role_context_returns_empty_for_missing_role() -> None:
    hub = MemoryHub()

    assert hub.role_context("missing") == []


def test_async_alias_methods_delegate_to_sync_methods() -> None:
    hub = MemoryHub()

    hub.aadd_global("g1")
    hub.aadd_global("g2")
    hub.aadd_role_note("qa", "q1")
    hub.aadd_role_note("qa", "q2")

    assert hub.aglobal_context() == ["g1", "g2"]
    assert hub.aglobal_context(limit=1) == ["g2"]
    assert hub.arole_context("qa") == ["q1", "q2"]
    assert hub.arole_context("qa", limit=1) == ["q2"]


def test_role_memory_dataclass_defaults() -> None:
    memory = RoleMemory(role="researcher")

    assert memory.role == "researcher"
    assert memory.notes == []
