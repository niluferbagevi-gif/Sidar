"""
core/__init__.py için birim testleri.
Opsiyonel import yardımcıları, alias'lar ve __all__ davranışını kapsar.
"""

from __future__ import annotations

import importlib


def _get_core():
    import core

    return importlib.reload(core)


class TestOptionalImportHelpers:
    def test_optional_module_returns_none_on_missing_module(self):
        core = _get_core()
        assert core._optional_module("modul_yok_12345") is None

    def test_optional_import_returns_proxy_on_missing_module(self):
        core = _get_core()
        missing_cls = core._optional_import("modul_yok_12345", "MissingThing")
        assert callable(missing_cls)

        try:
            missing_cls()
            raised = False
        except RuntimeError as exc:
            raised = True
            assert "MissingThing" in str(exc)

        assert raised is True


class TestExportsAndAliases:
    def test_all_contains_expected_symbols(self):
        core = _get_core()
        exported = set(core.__all__)
        assert "__version__" in exported
        assert "LLMClient" in exported
        assert "ConversationMemory" in exported
        assert "DocumentStore" in exported
        assert "Database" in exported
        assert "MultimodalPipeline" in exported
        assert "VoicePipeline" in exported
        assert "LLMMetricsCollector" in exported
        assert "get_llm_metrics_collector" in exported
        assert "MemoryManager" in exported
        assert "RAGManager" in exported
        assert "DatabaseManager" in exported

    def test_backwards_compatible_aliases_match_primary_symbols(self):
        core = _get_core()
        assert core.MemoryManager is core.ConversationMemory
        assert core.RAGManager is core.DocumentStore
        assert core.DatabaseManager is core.Database
