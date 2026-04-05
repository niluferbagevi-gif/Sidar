"""Unit tests for lightweight role/global memory hub."""

from __future__ import annotations

from agent.core.memory_hub import MemoryHub


def test_initial_state_is_empty() -> None:
    hub = MemoryHub()

    assert hub.global_context() == []
    assert hub.role_context("coder") == []


def test_add_global_ignores_empty_note() -> None:
    hub = MemoryHub()

    hub.add_global("note-1")
    hub.add_global("")
    hub.add_global("note-2")

    assert hub.global_context() == ["note-1", "note-2"]


def test_add_role_note_creates_and_appends_notes() -> None:
    hub = MemoryHub()

    hub.add_role_note("qa", "first")
    hub.add_role_note("qa", "")
    hub.add_role_note("qa", "second")

    assert hub.role_context("qa") == ["first", "second"]


def test_context_limit_defaults_and_lower_bound() -> None:
    hub = MemoryHub()

    for i in range(10):
        hub.add_global(f"g{i}")
        hub.add_role_note("reviewer", f"r{i}")

    assert hub.global_context() == ["g5", "g6", "g7", "g8", "g9"]
    assert hub.role_context("reviewer", limit=3) == ["r7", "r8", "r9"]

    # limit <= 0 should still return the last item because implementation clamps with max(1, limit)
    assert hub.global_context(limit=0) == ["g9"]
    assert hub.role_context("reviewer", limit=-99) == ["r9"]


def test_async_prefixed_helpers_delegate_to_sync_methods() -> None:
    hub = MemoryHub()

    hub.aadd_global("async-global")
    hub.aadd_role_note("coder", "async-role")

    assert hub.aglobal_context() == ["async-global"]
    assert hub.arole_context("coder") == ["async-role"]
