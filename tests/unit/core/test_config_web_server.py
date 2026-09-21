"""Tests for web server bind host/port settings resolution."""

from core.config_web_server import load_web_server_settings

_ALL_KEYS = (
    "WEB_HOST",
    "WEB_PORT",
    "WEB_GPU_PORT",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_web_server_settings()

    assert settings.web_host == "127.0.0.1"
    assert settings.web_port == 7860
    assert settings.web_gpu_port == 7861


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("WEB_PORT", "9000")
    monkeypatch.setenv("WEB_GPU_PORT", "9001")

    settings = load_web_server_settings()

    assert settings.web_host == "0.0.0.0"
    assert settings.web_port == 9000
    assert settings.web_gpu_port == 9001


def test_malformed_port_envs_fall_back_to_defaults(monkeypatch):
    """Non-integer port env values fall back to their defaults."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("WEB_PORT", "not-an-int")
    monkeypatch.setenv("WEB_GPU_PORT", "not-an-int")

    settings = load_web_server_settings()

    assert settings.web_port == 7860
    assert settings.web_gpu_port == 7861
