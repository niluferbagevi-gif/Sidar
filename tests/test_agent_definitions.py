"""
agent/definitions.py için birim testleri.
SIDAR_KEYS, SIDAR_WAKE_WORDS, DEFAULT_SYSTEM_PROMPT sabitleri.
"""
from __future__ import annotations

import sys


def _get_defs():
    if "agent.definitions" in sys.modules:
        del sys.modules["agent.definitions"]
    import agent.definitions as defs
    return defs


class TestDefinitions:
    def test_sidar_keys_contains_sidar(self):
        defs = _get_defs()
        assert "sidar" in defs.SIDAR_KEYS

    def test_sidar_keys_is_list(self):
        defs = _get_defs()
        assert isinstance(defs.SIDAR_KEYS, list)
        assert len(defs.SIDAR_KEYS) > 0

    def test_wake_words_contains_sidar(self):
        defs = _get_defs()
        assert "sidar" in defs.SIDAR_WAKE_WORDS

    def test_default_system_prompt_is_str(self):
        defs = _get_defs()
        assert isinstance(defs.DEFAULT_SYSTEM_PROMPT, str)
        assert len(defs.DEFAULT_SYSTEM_PROMPT) > 100

    def test_sidar_system_prompt_equals_default(self):
        defs = _get_defs()
        assert defs.SIDAR_SYSTEM_PROMPT == defs.DEFAULT_SYSTEM_PROMPT

    def test_default_prompt_contains_hallucination_ban(self):
        defs = _get_defs()
        assert "HALLUCINATION" in defs.DEFAULT_SYSTEM_PROMPT or "UYDURMA" in defs.DEFAULT_SYSTEM_PROMPT

    def test_default_prompt_mentions_json(self):
        defs = _get_defs()
        assert "JSON" in defs.DEFAULT_SYSTEM_PROMPT
