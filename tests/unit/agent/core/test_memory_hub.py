from __future__ import annotations

from agent.core.memory_hub import MemoryHub


def test_global_notes_and_limits() -> None:
    hub = MemoryHub()

    hub.add_global("")
    hub.add_global("n1")
    hub.add_global("n2")
    hub.add_global("n3")

    assert hub.global_context(limit=2) == ["n2", "n3"]
    # limit <= 0 için en az 1 kayıt döndürülür
    assert hub.global_context(limit=0) == ["n3"]


def test_role_notes_with_unknown_and_empty_input() -> None:
    hub = MemoryHub()

    hub.add_role_note("coder", "")
    assert hub.role_context("coder") == []

    hub.add_role_note("coder", "ilk")
    hub.add_role_note("coder", "ikinci")
    assert hub.role_context("coder", limit=1) == ["ikinci"]

    assert hub.role_context("missing") == []


def test_async_alias_methods_delegate_to_sync_methods() -> None:
    hub = MemoryHub()

    hub.aadd_global("g1")
    hub.aadd_role_note("qa", "r1")

    assert hub.aglobal_context() == ["g1"]
    assert hub.arole_context("qa") == ["r1"]
