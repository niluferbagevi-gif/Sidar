"""Tests for LSP (Language Server Protocol) integration settings resolution."""

from core.config_lsp import load_lsp_settings

_ALL_KEYS = (
    "ENABLE_LSP",
    "LSP_TIMEOUT_SECONDS",
    "LSP_MAX_REFERENCES",
    "PYTHON_LSP_SERVER",
    "TYPESCRIPT_LSP_SERVER",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_lsp_settings()

    assert settings.enable_lsp is True
    assert settings.lsp_timeout_seconds == 15
    assert settings.lsp_max_references == 200
    assert settings.python_lsp_server == "pyright-langserver"
    assert settings.typescript_lsp_server == "typescript-language-server"


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("ENABLE_LSP", "false")
    monkeypatch.setenv("LSP_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LSP_MAX_REFERENCES", "500")
    monkeypatch.setenv("PYTHON_LSP_SERVER", "jedi-language-server")
    monkeypatch.setenv("TYPESCRIPT_LSP_SERVER", "vtsls")

    settings = load_lsp_settings()

    assert settings.enable_lsp is False
    assert settings.lsp_timeout_seconds == 30
    assert settings.lsp_max_references == 500
    assert settings.python_lsp_server == "jedi-language-server"
    assert settings.typescript_lsp_server == "vtsls"


def test_malformed_integer_envs_fall_back_to_defaults(monkeypatch):
    """Non-integer timeout/reference-limit env values fall back to their defaults."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("LSP_TIMEOUT_SECONDS", "not-an-int")
    monkeypatch.setenv("LSP_MAX_REFERENCES", "not-an-int")

    settings = load_lsp_settings()

    assert settings.lsp_timeout_seconds == 15
    assert settings.lsp_max_references == 200
