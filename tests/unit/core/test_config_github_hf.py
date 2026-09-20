"""Tests for GitHub/Hugging Face integration settings resolution."""

import pytest

from core.config_github_hf import load_github_huggingface_settings

_ALL_KEYS = (
    "GITHUB_TOKEN",
    "GITHUB_REPO",
    "GITHUB_WEBHOOK_SECRET",
    "GITHUB_WEBHOOK_REQUIRE_SIGNATURE",
    "HF_TOKEN",
    "HF_HUB_OFFLINE",
    "HF_USE_LOCAL_CACHE_ONLY",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_are_empty_except_the_documented_boolean_defaults(monkeypatch):
    """With nothing configured, strings are blank and booleans match their documented defaults."""
    _clear_all(monkeypatch)

    settings = load_github_huggingface_settings()

    assert settings.github_token == ""
    assert settings.github_repo == ""
    assert settings.github_webhook_secret == ""
    assert settings.github_webhook_require_signature is True
    assert settings.hf_token == ""
    assert settings.hf_hub_offline is False
    assert settings.hf_use_local_cache_only is False


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_example")
    monkeypatch.setenv("GITHUB_REPO", "niluferbagevi-gif/Sidar")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("GITHUB_WEBHOOK_REQUIRE_SIGNATURE", "false")
    monkeypatch.setenv("HF_TOKEN", "hf_example")
    monkeypatch.setenv("HF_HUB_OFFLINE", "yes")
    monkeypatch.setenv("HF_USE_LOCAL_CACHE_ONLY", "true")

    settings = load_github_huggingface_settings()

    assert settings.github_token == "ghp_example"
    assert settings.github_repo == "niluferbagevi-gif/Sidar"
    assert settings.github_webhook_secret == "webhook-secret"
    assert settings.github_webhook_require_signature is False
    assert settings.hf_token == "hf_example"
    assert settings.hf_hub_offline is True
    assert settings.hf_use_local_cache_only is True


def test_github_webhook_require_signature_rejects_non_strict_boolean(monkeypatch):
    """GITHUB_WEBHOOK_REQUIRE_SIGNATURE uses the strict true/false parser, not external synonyms."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("GITHUB_WEBHOOK_REQUIRE_SIGNATURE", "yes")

    with pytest.raises(ValueError, match="GITHUB_WEBHOOK_REQUIRE_SIGNATURE"):
        load_github_huggingface_settings()


def test_hf_hub_offline_accepts_external_boolean_synonyms(monkeypatch):
    """HF_HUB_OFFLINE uses the external-provider boolean parser (1/0, yes/no, on/off)."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    assert load_github_huggingface_settings().hf_hub_offline is True

    monkeypatch.setenv("HF_HUB_OFFLINE", "off")

    assert load_github_huggingface_settings().hf_hub_offline is False
