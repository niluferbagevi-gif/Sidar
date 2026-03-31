"""agent/definitions.py için davranış odaklı testler."""
from __future__ import annotations

import sys

import pytest


def _get_definitions():
    for mod in ("agent.definitions", "agent"):
        sys.modules.pop(mod, None)

    import agent.definitions as defs
    return defs


class TestWakeWordContracts:
    def test_keys_and_wake_words_are_normalized_and_unique(self):
        defs = _get_definitions()
        normalized_keys = [key.strip().lower() for key in defs.SIDAR_KEYS]
        normalized_wake_words = [word.strip().lower() for word in defs.SIDAR_WAKE_WORDS]

        assert "sidar" in normalized_keys
        assert "sidar" in normalized_wake_words
        assert len(normalized_keys) == len(set(normalized_keys))
        assert len(normalized_wake_words) == len(set(normalized_wake_words))


class TestDefaultSystemPromptContracts:
    @pytest.mark.parametrize(
        "critical_section",
        [
            "HALLUCINATION YASAĞI",
            "DOSYA ERİŞİM STRATEJİSİ",
            "ARAÇ KULLANIM STRATEJİLERİ",
            "DÖNGÜ YASAĞI",
            "HATA KURTARMA",
        ],
    )
    def test_prompt_contains_operational_guardrail_sections(self, critical_section):
        defs = _get_definitions()
        assert critical_section in defs.DEFAULT_SYSTEM_PROMPT

    @pytest.mark.parametrize(
        "required_tool",
        [
            "get_config",
            "glob_search",
            "grep_files",
            "read_file",
            "patch_file",
            "run_shell",
            "todo_write",
            "final_answer",
        ],
    )
    def test_prompt_declares_core_toolchain(self, required_tool):
        defs = _get_definitions()
        assert required_tool in defs.DEFAULT_SYSTEM_PROMPT

    def test_prompt_declares_json_response_contract_fields(self):
        defs = _get_definitions()
        prompt = defs.DEFAULT_SYSTEM_PROMPT

        assert '"thought"' in prompt
        assert '"tool"' in prompt
        assert '"argument"' in prompt

    def test_prompt_includes_runtime_truth_source_contract(self):
        defs = _get_definitions()
        prompt = defs.DEFAULT_SYSTEM_PROMPT
        assert "GERÇEK RUNTIME DEĞERLERİ" in prompt
        assert "TAHMİN ETME" in prompt

    def test_alias_points_to_default_prompt(self):
        defs = _get_definitions()
        assert defs.SIDAR_SYSTEM_PROMPT == defs.DEFAULT_SYSTEM_PROMPT