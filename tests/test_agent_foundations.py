"""
tests/test_agent_foundations.py
================================
agent/definitions.py, agent/core/registry.py, agent/core/memory_hub.py
modüllerinin birim testleri.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

_BASE = os.path.dirname(os.path.dirname(__file__))


def _load_direct(dotted_name: str):
    """
    Dosyayı __init__ zincirine girmeden doğrudan yükle.
    Örn: "agent.core.memory_hub" → agent/core/memory_hub.py
    """
    file_path = os.path.join(_BASE, dotted_name.replace(".", os.sep) + ".py")
    # Üst paketleri stub'la
    parts = dotted_name.split(".")
    for i in range(1, len(parts)):
        pkg = ".".join(parts[:i])
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)

    sys.modules.pop(dotted_name, None)
    spec = importlib.util.spec_from_file_location(dotted_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fresh(name: str):
    return _load_direct(name)


# ═════════════════════════════════════════════════════════════════════════════
#  agent/definitions.py
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentDefinitions:
    """agent/definitions.py sabitlerinin testleri."""

    def setup_method(self):
        self.mod = _fresh("agent.definitions")

    def test_sidar_keys_liste(self):
        assert isinstance(self.mod.SIDAR_KEYS, list)
        assert len(self.mod.SIDAR_KEYS) > 0

    def test_sidar_wake_words_liste(self):
        assert isinstance(self.mod.SIDAR_WAKE_WORDS, list)
        assert len(self.mod.SIDAR_WAKE_WORDS) > 0

    def test_sidar_keys_sidar_iceriyor(self):
        assert "sidar" in self.mod.SIDAR_KEYS

    def test_wake_words_sidar_iceriyor(self):
        assert "sidar" in self.mod.SIDAR_WAKE_WORDS

    def test_default_system_prompt_string(self):
        assert isinstance(self.mod.DEFAULT_SYSTEM_PROMPT, str)
        assert len(self.mod.DEFAULT_SYSTEM_PROMPT) > 100

    def test_sidar_system_prompt_string(self):
        assert isinstance(self.mod.SIDAR_SYSTEM_PROMPT, str)

    def test_default_ve_sidar_prompt_ayni(self):
        assert self.mod.DEFAULT_SYSTEM_PROMPT == self.mod.SIDAR_SYSTEM_PROMPT

    def test_prompt_turkce_icerik(self):
        assert "SİDAR" in self.mod.DEFAULT_SYSTEM_PROMPT or "Sidar" in self.mod.DEFAULT_SYSTEM_PROMPT


# ═════════════════════════════════════════════════════════════════════════════
#  agent/core/memory_hub.py
# ═════════════════════════════════════════════════════════════════════════════

class TestRoleMemory:
    """RoleMemory dataclass testleri."""

    def setup_method(self):
        self.mod = _fresh("agent.core.memory_hub")

    def test_olusturma_varsayilan(self):
        rm = self.mod.RoleMemory(role="coder")
        assert rm.role == "coder"
        assert rm.notes == []

    def test_notes_bagimsiz(self):
        rm1 = self.mod.RoleMemory(role="a")
        rm2 = self.mod.RoleMemory(role="b")
        rm1.notes.append("note")
        assert rm2.notes == []


class TestMemoryHub:
    """MemoryHub sınıf testleri."""

    def setup_method(self):
        self.mod = _fresh("agent.core.memory_hub")
        self.hub = self.mod.MemoryHub()

    def test_bos_global_context(self):
        assert self.hub.global_context() == []

    def test_add_global(self):
        self.hub.add_global("not 1")
        assert self.hub.global_context() == ["not 1"]

    def test_add_global_bos_eklenmez(self):
        self.hub.add_global("")
        assert self.hub.global_context() == []

    def test_global_context_limit(self):
        for i in range(10):
            self.hub.add_global(f"not {i}")
        result = self.hub.global_context(limit=3)
        assert len(result) == 3

    def test_add_role_note(self):
        self.hub.add_role_note("coder", "kod yaz")
        assert self.hub.role_context("coder") == ["kod yaz"]

    def test_add_role_note_bos_eklenmez(self):
        self.hub.add_role_note("coder", "")
        assert self.hub.role_context("coder") == []

    def test_role_context_bilinmiyor(self):
        assert self.hub.role_context("bilinmiyor") == []

    def test_role_context_limit(self):
        for i in range(10):
            self.hub.add_role_note("reviewer", f"not {i}")
        result = self.hub.role_context("reviewer", limit=2)
        assert len(result) == 2
        assert result == ["not 8", "not 9"]

    def test_farkli_roller_bagimsiz(self):
        self.hub.add_role_note("coder", "kod yaz")
        self.hub.add_role_note("reviewer", "gözden geçir")
        assert self.hub.role_context("coder") == ["kod yaz"]
        assert self.hub.role_context("reviewer") == ["gözden geçir"]

    def test_add_role_note_var_olan_role(self):
        self.hub.add_role_note("qa", "test et")
        self.hub.add_role_note("qa", "doğrula")
        assert len(self.hub.role_context("qa", limit=10)) == 2

    def test_aadd_global_proxy(self):
        self.hub.aadd_global("proxy not")
        assert "proxy not" in self.hub.global_context()

    def test_aadd_role_note_proxy(self):
        self.hub.aadd_role_note("coder", "proxy kod")
        assert "proxy kod" in self.hub.role_context("coder")

    def test_aglobal_context_proxy(self):
        self.hub.add_global("async not")
        result = self.hub.aglobal_context(limit=5)
        assert "async not" in result

    def test_arole_context_proxy(self):
        self.hub.add_role_note("sup", "async rol")
        result = self.hub.arole_context("sup", limit=5)
        assert "async rol" in result

    def test_role_unknown_default_override(self):
        # defaultdict ile "unknown" rolü oluşturuluyor, sonra gerçek nota ekleniyor
        hub = self.mod.MemoryHub()
        # defaultdict "unknown" rol ile RoleMemory oluşturur
        _ = hub._role_notes["new_role"]
        # Ardından not eklenince gerçek rol adıyla değiştirilmeli
        hub.add_role_note("new_role", "test notu")
        assert "test notu" in hub.role_context("new_role")


# ═════════════════════════════════════════════════════════════════════════════
#  agent/core/registry.py
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentRegistry:
    """AgentRegistry testleri."""

    def setup_method(self):
        # base_agent mock'la — ağır bağımlılık yok
        mock_base_agent = MagicMock()
        mock_base_agent.BaseAgent = MagicMock
        sys.modules["agent.base_agent"] = mock_base_agent
        self.mod = _fresh("agent.core.registry")
        self.Registry = self.mod.AgentRegistry
        self.mock_agent = MagicMock()

    def teardown_method(self):
        sys.modules.pop("agent.base_agent", None)
        sys.modules.pop("agent.core.registry", None)

    def test_bos_registry(self):
        r = self.Registry()
        assert list(r.roles()) == []

    def test_register_ve_get(self):
        r = self.Registry()
        r.register("coder", self.mock_agent)
        assert r.get("coder") is self.mock_agent

    def test_get_kayitsiz_rol_hata(self):
        r = self.Registry()
        with pytest.raises(KeyError, match="kayıtlı değil"):
            r.get("unknown_role")

    def test_has_var_olan_rol(self):
        r = self.Registry()
        r.register("reviewer", self.mock_agent)
        assert r.has("reviewer") is True

    def test_has_olmayan_rol(self):
        r = self.Registry()
        assert r.has("ghost_role") is False

    def test_roles_tuple_doner(self):
        r = self.Registry()
        r.register("a", self.mock_agent)
        r.register("b", self.mock_agent)
        roles = r.roles()
        assert "a" in roles
        assert "b" in roles

    def test_override_rol(self):
        r = self.Registry()
        agent1 = MagicMock()
        agent2 = MagicMock()
        r.register("coder", agent1)
        r.register("coder", agent2)
        assert r.get("coder") is agent2

    def test_hata_mesajinda_mevcut_roller_gosterilir(self):
        r = self.Registry()
        r.register("coder", self.mock_agent)
        with pytest.raises(KeyError) as exc_info:
            r.get("nonexistent")
        assert "coder" in str(exc_info.value)