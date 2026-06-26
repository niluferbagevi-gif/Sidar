from __future__ import annotations

import config_security


def test_load_security_settings_generates_runtime_jwt_without_api_key_fallback(monkeypatch):
    monkeypatch.setattr(config_security.secrets, "token_urlsafe", lambda size: f"runtime-{size}")
    monkeypatch.setenv("JWT_TTL_DAYS", "14")

    values = {
        "API_KEY": "public-api-key",
        "JWT_SECRET_KEY": "",
        "SIDAR_SKIP_DEFAULT_DOTENV": "true",
        "SIDAR_KEYS_FILE": "/tmp/sidar.keys",
        "ACCESS_LEVEL": "admin",
        "JWT_ALGORITHM": "HS512",
    }
    settings = config_security.load_security_settings(
        getenv=lambda key, default=None: values.get(key, default)
    )

    assert settings.api_key == "public-api-key"
    assert settings.jwt_secret_key == "runtime-32"
    assert settings.jwt_secret_key != settings.api_key
    assert settings.jwt_secret_key_explicitly_configured is False
    assert settings.sidar_skip_default_dotenv is True
    assert settings.sidar_keys_file == "/tmp/sidar.keys"
    assert settings.access_level == "admin"
    assert settings.jwt_algorithm == "HS512"
    assert settings.jwt_ttl_days == 14


def test_missing_security_runtime_keys_requires_explicit_production_secrets():
    assert config_security.get_missing_security_runtime_keys(
        api_key="",
        jwt_secret_key="runtime-generated",
        jwt_secret_key_explicitly_configured=False,
        is_production=True,
        is_test_env=False,
    ) == ["JWT_SECRET_KEY", "API_KEY"]

    assert (
        config_security.get_missing_security_runtime_keys(
            api_key="api-ok",
            jwt_secret_key="jwt-ok",
            jwt_secret_key_explicitly_configured=True,
            is_production=True,
            is_test_env=False,
        )
        == []
    )
