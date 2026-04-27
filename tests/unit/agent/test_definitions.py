"""agent/definitions.py modülü için unit testler."""

from agent.definitions import (
    DEFAULT_SYSTEM_PROMPT,
    SIDAR_KEYS,
    SIDAR_SYSTEM_PROMPT,
    SIDAR_WAKE_WORDS,
)


def test_sidar_keys_is_nonempty_list():
    """SIDAR_KEYS liste tipinde ve en az bir eleman içermelidir."""
    assert isinstance(SIDAR_KEYS, list)
    assert len(SIDAR_KEYS) > 0


def test_sidar_keys_contains_sidar():
    """SIDAR_KEYS'in 'sidar' wake-word'ünü içermesi zorunludur."""
    assert "sidar" in SIDAR_KEYS


def test_sidar_keys_all_lowercase_strings():
    """SIDAR_KEYS elemanlarının tümü küçük harfli string olmalıdır."""
    for key in SIDAR_KEYS:
        assert isinstance(key, str), f"SIDAR_KEYS elemanı str olmalı: {key!r}"
        assert key == key.lower(), f"SIDAR_KEYS elemanı küçük harfli olmalı: {key!r}"


def test_sidar_wake_words_is_nonempty_list():
    """SIDAR_WAKE_WORDS liste tipinde ve en az bir eleman içermelidir."""
    assert isinstance(SIDAR_WAKE_WORDS, list)
    assert len(SIDAR_WAKE_WORDS) > 0


def test_sidar_wake_words_contains_sidar():
    """Her wake-word 'sidar' kelimesini içermelidir."""
    assert all("sidar" in w for w in SIDAR_WAKE_WORDS)


def test_sidar_wake_words_all_lowercase_strings():
    """SIDAR_WAKE_WORDS elemanlarının tümü küçük harfli string olmalıdır."""
    for word in SIDAR_WAKE_WORDS:
        assert isinstance(word, str), f"SIDAR_WAKE_WORDS elemanı str olmalı: {word!r}"
        assert word == word.lower(), f"SIDAR_WAKE_WORDS elemanı küçük harfli olmalı: {word!r}"


def test_default_system_prompt_is_nonempty_string():
    """DEFAULT_SYSTEM_PROMPT dolu bir string olmalıdır."""
    assert isinstance(DEFAULT_SYSTEM_PROMPT, str)
    assert len(DEFAULT_SYSTEM_PROMPT) > 100


def test_default_system_prompt_has_personality_section():
    """Sistem prompt'u KİŞİLİK bölümünü içermelidir."""
    assert "KİŞİLİK" in DEFAULT_SYSTEM_PROMPT


def test_default_system_prompt_has_mission_section():
    """Sistem prompt'u MİSYON bölümünü içermelidir."""
    assert "MİSYON" in DEFAULT_SYSTEM_PROMPT


def test_default_system_prompt_has_hallucination_guard():
    """Sistem prompt'u HALLUCINATION YASAĞI güvencesini içermelidir."""
    assert "HALLUCINATION" in DEFAULT_SYSTEM_PROMPT


def test_sidar_system_prompt_is_backward_compat_alias():
    """SIDAR_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT ile aynı nesne olmalıdır (geriye dönük uyumluluk)."""
    assert SIDAR_SYSTEM_PROMPT is DEFAULT_SYSTEM_PROMPT
