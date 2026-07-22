"""Tests for rate-limit and Redis configuration resolution."""

from core.config_rate_limit import resolve_redis_url


def test_resolve_redis_url_adds_encoded_password_for_local_compose(monkeypatch):
    """Local Compose credentials are added without producing an invalid URL."""
    monkeypatch.setenv("SIDAR_REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("REDIS_PASSWORD", "secret:/ value")

    assert resolve_redis_url() == "redis://:secret%3A%2F%20value@localhost:6379/15"


def test_resolve_redis_url_preserves_explicit_or_remote_credentials(monkeypatch):
    """Explicit URLs and remote Redis services remain operator-controlled."""
    monkeypatch.setenv("REDIS_PASSWORD", "local-secret")
    monkeypatch.setenv("SIDAR_REDIS_URL", "redis://:explicit@localhost:6379/0")
    assert resolve_redis_url() == "redis://:explicit@localhost:6379/0"

    monkeypatch.setenv("SIDAR_REDIS_URL", "rediss://cache.example.com:6380/0")
    assert resolve_redis_url() == "rediss://cache.example.com:6380/0"


def test_resolve_redis_url_returns_url_unchanged_when_no_password_set(monkeypatch):
    """No REDIS_PASSWORD means no credential-injection logic runs at all."""
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.setenv("SIDAR_REDIS_URL", "redis://localhost:6379/0")
    assert resolve_redis_url() == "redis://localhost:6379/0"

    monkeypatch.setenv("REDIS_PASSWORD", "   ")
    assert resolve_redis_url() == "redis://localhost:6379/0"


def test_resolve_redis_url_uses_compose_host_port_only_for_local_url(monkeypatch):
    """REDIS_PORT keeps local runtime aligned with the Compose host mapping."""
    monkeypatch.setenv("REDIS_PASSWORD", "local-secret")
    monkeypatch.setenv("REDIS_PORT", "6391")
    monkeypatch.setenv("SIDAR_REDIS_URL", "redis://localhost:6379/0")
    assert resolve_redis_url() == "redis://:local-secret@localhost:6391/0"

    monkeypatch.setenv("SIDAR_REDIS_URL", "rediss://cache.example.com:7443/0")
    assert resolve_redis_url() == "rediss://cache.example.com:7443/0"
