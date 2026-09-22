"""Tests for memory encryption (Fernet) settings resolution."""

from core.config_memory_security import load_memory_security_settings

_ALL_KEYS = (
    "MEMORY_ENCRYPTION_KEY",
    "MEMORY_ENCRYPTION_KEY_PREVIOUS",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_memory_security_settings()

    assert settings.memory_encryption_key == ""
    assert settings.memory_encryption_key_previous == ""


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("MEMORY_ENCRYPTION_KEY", "current-fernet-key")
    monkeypatch.setenv("MEMORY_ENCRYPTION_KEY_PREVIOUS", "old-key-1,old-key-2")

    settings = load_memory_security_settings()

    assert settings.memory_encryption_key == "current-fernet-key"
    assert settings.memory_encryption_key_previous == "old-key-1,old-key-2"
