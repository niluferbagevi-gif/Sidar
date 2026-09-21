"""Tests for web search/fetch settings resolution."""

from core.config_web_search import load_web_search_settings

_ALL_KEYS = (
    "SEARCH_ENGINE",
    "TAVILY_API_KEY",
    "GOOGLE_SEARCH_API_KEY",
    "GOOGLE_SEARCH_CX",
    "WEB_SEARCH_MAX_RESULTS",
    "WEB_FETCH_TIMEOUT",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_web_search_settings()

    assert settings.search_engine == "auto"
    assert settings.tavily_api_key == ""
    assert settings.google_search_api_key == ""
    assert settings.google_search_cx == ""
    assert settings.web_search_max_results == 5
    assert settings.web_fetch_timeout == 15


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("SEARCH_ENGINE", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-example")
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "google-key")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx-example")
    monkeypatch.setenv("WEB_SEARCH_MAX_RESULTS", "10")
    monkeypatch.setenv("WEB_FETCH_TIMEOUT", "30")

    settings = load_web_search_settings()

    assert settings.search_engine == "tavily"
    assert settings.tavily_api_key == "tvly-example"
    assert settings.google_search_api_key == "google-key"
    assert settings.google_search_cx == "cx-example"
    assert settings.web_search_max_results == 10
    assert settings.web_fetch_timeout == 30


def test_malformed_integer_env_falls_back_to_default(monkeypatch):
    """A non-integer WEB_SEARCH_MAX_RESULTS/WEB_FETCH_TIMEOUT falls back to the default."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("WEB_SEARCH_MAX_RESULTS", "not-a-number")
    monkeypatch.setenv("WEB_FETCH_TIMEOUT", "also-not-a-number")

    settings = load_web_search_settings()

    assert settings.web_search_max_results == 5
    assert settings.web_fetch_timeout == 15
