"""
agent/core/memory_hub.py için birim testleri.
Saf stdlib modülü; stub gerekmez.
"""
from __future__ import annotations

import sys
import types
import pathlib as _pl

_proj = _pl.Path(__file__).parent.parent

def _get_memory_hub():
    if "agent" not in sys.modules:
        _pkg = types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg

    if "agent.core" not in sys.modules:
        core_pkg = types.ModuleType("agent.core")
        core_pkg.__path__ = [str(_proj / "agent" / "core")]
        core_pkg.__package__ = "agent.core"
        sys.modules["agent.core"] = core_pkg
    else:
        core_pkg = sys.modules["agent.core"]
        if not hasattr(core_pkg, "__path__"):
            core_pkg.__path__ = [str(_proj / "agent" / "core")]
            core_pkg.__package__ = "agent.core"

    sys.modules.pop("agent.core.memory_hub", None)
    import agent.core.memory_hub as mh
    return mh


class TestRoleMemory:
    def test_role_memory_defaults(self):
        mh = _get_memory_hub()
        rm = mh.RoleMemory(role="coder")
        assert rm.role == "coder"
        assert rm.notes == []

    def test_role_memory_with_notes(self):
        mh = _get_memory_hub()
        rm = mh.RoleMemory(role="reviewer", notes=["not 1", "not 2"])
        assert len(rm.notes) == 2


class TestMemoryHubGlobal:
    def test_add_global_and_retrieve(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_global("ilk not")
        hub.add_global("ikinci not")
        ctx = hub.global_context()
        assert "ilk not" in ctx
        assert "ikinci not" in ctx

    def test_add_global_empty_string_ignored(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_global("")
        assert hub.global_context() == []

    def test_global_context_limit(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        for i in range(10):
            hub.add_global(f"not {i}")
        ctx = hub.global_context(limit=3)
        assert len(ctx) == 3
        assert ctx[-1] == "not 9"

    def test_global_context_default_limit(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        for i in range(20):
            hub.add_global(f"not {i}")
        ctx = hub.global_context()
        assert len(ctx) == 5  # varsayılan limit=5

    def test_global_context_limit_one(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_global("a")
        hub.add_global("b")
        ctx = hub.global_context(limit=1)
        assert len(ctx) == 1
        assert ctx[0] == "b"

    def test_global_context_zero_limit_returns_at_least_one(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_global("tek")
        ctx = hub.global_context(limit=0)
        assert len(ctx) == 1

    def test_aadd_global_alias(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.aadd_global("alias ile eklendi")
        ctx = hub.aglobal_context()
        assert "alias ile eklendi" in ctx


class TestMemoryHubRoleNotes:
    def test_add_role_note_and_retrieve(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_role_note("coder", "kod yazıldı")
        ctx = hub.role_context("coder")
        assert "kod yazıldı" in ctx

    def test_add_role_note_empty_ignored(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_role_note("coder", "")
        assert hub.role_context("coder") == []

    def test_role_context_unknown_role_returns_empty(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        assert hub.role_context("unknown_role_xyz") == []

    def test_role_context_limit(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        for i in range(10):
            hub.add_role_note("reviewer", f"inceleme {i}")
        ctx = hub.role_context("reviewer", limit=3)
        assert len(ctx) == 3
        assert ctx[-1] == "inceleme 9"

    def test_multiple_roles_isolated(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_role_note("coder", "coder notu")
        hub.add_role_note("reviewer", "reviewer notu")
        assert hub.role_context("coder") == ["coder notu"]
        assert hub.role_context("reviewer") == ["reviewer notu"]

    def test_add_role_note_multiple_times(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_role_note("qa", "test 1")
        hub.add_role_note("qa", "test 2")
        hub.add_role_note("qa", "test 3")
        ctx = hub.role_context("qa", limit=10)
        assert len(ctx) == 3

    def test_aadd_role_note_alias(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.aadd_role_note("poyraz", "pazarlama notu")
        ctx = hub.arole_context("poyraz")
        assert "pazarlama notu" in ctx

    def test_role_context_zero_limit_returns_at_least_one(self):
        mh = _get_memory_hub()
        hub = mh.MemoryHub()
        hub.add_role_note("coder", "tek")
        ctx = hub.role_context("coder", limit=0)
        assert len(ctx) == 1


class TestMemoryHubIsolation:
    def test_fresh_instance_has_no_notes(self):
        mh = _get_memory_hub()
        hub1 = mh.MemoryHub()
        hub2 = mh.MemoryHub()
        hub1.add_global("hub1 notu")
        assert hub2.global_context() == []

    def test_fresh_instance_has_no_role_notes(self):
        mh = _get_memory_hub()
        hub1 = mh.MemoryHub()
        hub2 = mh.MemoryHub()
        hub1.add_role_note("coder", "hub1")
        assert hub2.role_context("coder") == []
