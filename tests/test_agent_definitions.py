"""agent/definitions.py için mantıksal birim testleri."""
from __future__ import annotations

import importlib
import re
import sys


EXPECTED_RUNTIME_SECTIONS = (
    "## KİŞİLİK",
    "## MİSYON",
    "## HALLUCINATION YASAĞI — MUTLAK KURAL",
    "## DOSYA ERİŞİM STRATEJİSİ — TEMEL",
    "## GÖREV TAKİP STRATEJİSİ — TEMEL",
    "## ARAÇ KULLANIM STRATEJİLERİ",
)

EXPECTED_CORE_TOOLS = (
    "get_config",
    "glob_search",
    "grep_files",
    "read_file",
    "patch_file",
    "run_shell",
)


def _get_definitions():
    for mod in ("agent.definitions", "agent"):
        sys.modules.pop(mod, None)
    return importlib.import_module("agent.definitions")


class TestSidarActivationLexicon:
    def test_keys_and_wake_words_are_normalized_and_unique(self):
        defs = _get_definitions()

        keys = defs.SIDAR_KEYS
        wake_words = defs.SIDAR_WAKE_WORDS

        assert keys, "SIDAR_KEYS boş olmamalı"
        assert wake_words, "SIDAR_WAKE_WORDS boş olmamalı"
        assert len(keys) == len(set(keys)), "SIDAR_KEYS tekrarlı değer içermemeli"
        assert len(wake_words) == len(set(wake_words)), "SIDAR_WAKE_WORDS tekrarlı değer içermemeli"
        assert all(item == item.lower() for item in keys)
        assert all(item == item.lower() for item in wake_words)

    def test_wake_words_are_subset_of_key_space_intent(self):
        defs = _get_definitions()
        key_space = set(defs.SIDAR_KEYS)

        # Wake words daha tetikleyici ve dar bir küme olmalı;
        # en azından temel kimlik anahtarı kesişimi garanti edilir.
        assert "sidar" in key_space
        assert "sidar" in defs.SIDAR_WAKE_WORDS
        assert key_space.intersection(defs.SIDAR_WAKE_WORDS)


class TestDefaultSystemPromptContract:
    def test_prompt_contains_required_operational_sections(self):
        defs = _get_definitions()
        prompt = defs.DEFAULT_SYSTEM_PROMPT

        for section in EXPECTED_RUNTIME_SECTIONS:
            assert section in prompt, f"Eksik bölüm: {section}"

    def test_prompt_enforces_non_hallucination_and_runtime_resolution(self):
        defs = _get_definitions()
        prompt = defs.DEFAULT_SYSTEM_PROMPT

        assert "ASLA TAHMİN ETME" in prompt
        assert "get_config" in prompt
        assert "GERÇEK RUNTIME DEĞERLERİ" in prompt

    def test_prompt_includes_actionable_tool_instructions(self):
        defs = _get_definitions()
        prompt = defs.DEFAULT_SYSTEM_PROMPT

        for tool_name in EXPECTED_CORE_TOOLS:
            assert tool_name in prompt, f"Prompt araç yönlendirmesi eksik: {tool_name}"

    def test_prompt_does_not_contain_unresolved_template_variables(self):
        defs = _get_definitions()
        prompt = defs.DEFAULT_SYSTEM_PROMPT

        unresolved = re.findall(r"\{[^{}]+\}", prompt)
        # Bu prompt seed/fallback olarak runtime'a direkt yazıldığı için
        # unresolved template placeholder kalmamalı.
        assert unresolved == []

    def test_sidar_system_prompt_alias_equals_default(self):
        defs = _get_definitions()
        assert defs.SIDAR_SYSTEM_PROMPT == defs.DEFAULT_SYSTEM_PROMPT
