"""Tests for autonomy service webhook settings resolution."""

from core.config_autonomy import load_autonomy_settings

_ALL_KEYS = (
    "AUTONOMY_SERVICE_USER_ID",
    "SYSTEM_USER_ID",
    "AUTONOMY_WEBHOOK_SECRET",
    "SIDAR_AUTONOMY_WEBHOOK_SECRET",
    "AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE",
    "SIDAR_AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_autonomy_settings()

    assert settings.autonomy_service_user_id == "system:autonomy"
    assert settings.autonomy_webhook_secret == ""
    assert settings.autonomy_webhook_require_signature is True


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own primary env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("AUTONOMY_SERVICE_USER_ID", "svc:custom")
    monkeypatch.setenv("AUTONOMY_WEBHOOK_SECRET", "primary-secret")
    monkeypatch.setenv("AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE", "false")

    settings = load_autonomy_settings()

    assert settings.autonomy_service_user_id == "svc:custom"
    assert settings.autonomy_webhook_secret == "primary-secret"
    assert settings.autonomy_webhook_require_signature is False


def test_legacy_alias_envs_are_used_when_primary_envs_are_unset(monkeypatch):
    """SYSTEM_USER_ID/SIDAR_AUTONOMY_* aliases are honored when the primary is unset."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("SYSTEM_USER_ID", "legacy:system")
    monkeypatch.setenv("SIDAR_AUTONOMY_WEBHOOK_SECRET", "legacy-secret")
    monkeypatch.setenv("SIDAR_AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE", "false")

    settings = load_autonomy_settings()

    assert settings.autonomy_service_user_id == "legacy:system"
    assert settings.autonomy_webhook_secret == "legacy-secret"
    assert settings.autonomy_webhook_require_signature is False


def test_primary_envs_take_precedence_over_legacy_aliases(monkeypatch):
    """When both primary and alias envs are set, the primary env wins."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("AUTONOMY_SERVICE_USER_ID", "svc:primary")
    monkeypatch.setenv("SYSTEM_USER_ID", "legacy:system")
    monkeypatch.setenv("AUTONOMY_WEBHOOK_SECRET", "primary-secret")
    monkeypatch.setenv("SIDAR_AUTONOMY_WEBHOOK_SECRET", "legacy-secret")
    monkeypatch.setenv("AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE", "true")
    monkeypatch.setenv("SIDAR_AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE", "false")

    settings = load_autonomy_settings()

    assert settings.autonomy_service_user_id == "svc:primary"
    assert settings.autonomy_webhook_secret == "primary-secret"
    assert settings.autonomy_webhook_require_signature is True
