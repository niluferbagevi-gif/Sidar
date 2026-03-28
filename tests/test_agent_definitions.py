"""
agent/definitions.py için birim testleri.
SIDAR_KEYS, SIDAR_WAKE_WORDS ve DEFAULT_SYSTEM_PROMPT sabitlerini kapsar.
"""
from __future__ import annotations

import sys
import types


def _get_definitions():
    for mod in ("agent.definitions", "agent"):
        sys.modules.pop(mod, None)

    import agent.definitions as defs
    return defs


class TestSidarKeys:
    def test_sidar_keys_is_list(self):
        defs = _get_definitions()
        assert isinstance(defs.SIDAR_KEYS, list)

    def test_sidar_keys_contains_sidar(self):
        defs = _get_definitions()
        assert "sidar" in defs.SIDAR_KEYS

    def test_sidar_keys_not_empty(self):
        defs = _get_definitions()
        assert len(defs.SIDAR_KEYS) > 0

    def test_sidar_keys_all_strings(self):
        defs = _get_definitions()
        for key in defs.SIDAR_KEYS:
            assert isinstance(key, str)


class TestSidarWakeWords:
    def test_wake_words_is_list(self):
        defs = _get_definitions()
        assert isinstance(defs.SIDAR_WAKE_WORDS, list)

    def test_wake_words_contains_sidar(self):
        defs = _get_definitions()
        assert "sidar" in defs.SIDAR_WAKE_WORDS

    def test_wake_words_not_empty(self):
        defs = _get_definitions()
        assert len(defs.SIDAR_WAKE_WORDS) > 0

    def test_wake_words_all_lowercase(self):
        defs = _get_definitions()
        for word in defs.SIDAR_WAKE_WORDS:
            assert word == word.lower()


class TestDefaultSystemPrompt:
    def test_prompt_is_string(self):
        defs = _get_definitions()
        assert isinstance(defs.DEFAULT_SYSTEM_PROMPT, str)

    def test_prompt_not_empty(self):
        defs = _get_definitions()
        assert len(defs.DEFAULT_SYSTEM_PROMPT.strip()) > 0

    def test_prompt_contains_sidar_identity(self):
        defs = _get_definitions()
        assert "SİDAR" in defs.DEFAULT_SYSTEM_PROMPT or "SIDAR" in defs.DEFAULT_SYSTEM_PROMPT.upper()

    def test_prompt_contains_json_format_instruction(self):
        defs = _get_definitions()
        assert "JSON" in defs.DEFAULT_SYSTEM_PROMPT

    def test_prompt_contains_tool_section(self):
        defs = _get_definitions()
        assert "tool" in defs.DEFAULT_SYSTEM_PROMPT.lower()

    def test_sidar_system_prompt_alias_equals_default(self):
        defs = _get_definitions()
        assert defs.SIDAR_SYSTEM_PROMPT == defs.DEFAULT_SYSTEM_PROMPT
