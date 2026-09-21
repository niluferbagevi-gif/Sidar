"""Tests for browser automation settings resolution."""

from core.config_browser import load_browser_settings

_ALL_KEYS = (
    "BROWSER_PROVIDER",
    "BROWSER_HEADLESS",
    "BROWSER_TIMEOUT_MS",
    "BROWSER_ALLOWED_DOMAINS",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_browser_settings()

    assert settings.browser_provider == "auto"
    assert settings.browser_headless is True
    assert settings.browser_timeout_ms == 15000
    assert settings.browser_allowed_domains == []


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("BROWSER_PROVIDER", "playwright")
    monkeypatch.setenv("BROWSER_HEADLESS", "false")
    monkeypatch.setenv("BROWSER_TIMEOUT_MS", "30000")
    monkeypatch.setenv("BROWSER_ALLOWED_DOMAINS", "example.com,sidar.dev")

    settings = load_browser_settings()

    assert settings.browser_provider == "playwright"
    assert settings.browser_headless is False
    assert settings.browser_timeout_ms == 30000
    assert settings.browser_allowed_domains == ["example.com", "sidar.dev"]


def test_malformed_timeout_env_falls_back_to_default(monkeypatch):
    """A non-integer timeout env value falls back to its default."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("BROWSER_TIMEOUT_MS", "not-an-int")

    settings = load_browser_settings()

    assert settings.browser_timeout_ms == 15000
