"""
agent/definitions.py için birim testleri.
SIDAR_KEYS, SIDAR_WAKE_WORDS ve DEFAULT_SYSTEM_PROMPT sabitlerini kapsar.
"""
from __future__ import annotations

import sys

import pytest


def _get_definitions():
    for mod in ("agent.definitions", "agent"):
        sys.modules.pop(mod, None)

    import agent.definitions as defs
    return defs


class TestSidarKeys:
    @pytest.mark.parametrize(
        ("attribute", "validator"),
        [
            ("SIDAR_KEYS", lambda value: isinstance(value, list)),
            ("SIDAR_KEYS", lambda value: "sidar" in value),
            ("SIDAR_KEYS", lambda value: len(value) > 0),
        ],
    )
    def test_sidar_keys_common_guards(self, attribute, validator):
        defs = _get_definitions()
        assert validator(getattr(defs, attribute))

    def test_sidar_keys_all_strings(self):
        defs = _get_definitions()
        for key in defs.SIDAR_KEYS:
            assert isinstance(key, str)


class TestSidarWakeWords:
    @pytest.mark.parametrize(
        ("attribute", "validator"),
        [
            ("SIDAR_WAKE_WORDS", lambda value: isinstance(value, list)),
            ("SIDAR_WAKE_WORDS", lambda value: "sidar" in value),
            ("SIDAR_WAKE_WORDS", lambda value: len(value) > 0),
        ],
    )
    def test_wake_words_common_guards(self, attribute, validator):
        defs = _get_definitions()
        assert validator(getattr(defs, attribute))

    def test_wake_words_all_lowercase(self):
        defs = _get_definitions()
        for word in defs.SIDAR_WAKE_WORDS:
            assert word == word.lower()


class TestDefaultSystemPrompt:
    @pytest.mark.parametrize(
        "validator",
        [
            lambda value: isinstance(value, str),
            lambda value: len(value.strip()) > 0,
        ],
    )
    def test_prompt_type_and_content_guards(self, validator):
        defs = _get_definitions()
        assert validator(defs.DEFAULT_SYSTEM_PROMPT)

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
