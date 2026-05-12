"""Unit tests for `core.utils.network_validation`.

B104 (Bind to all interfaces) bypass'ı yerine geçen doğrulama katmanının
hem güvenli host kabulünü hem de üretim profili reddini garanti eder.
"""

from __future__ import annotations

import pytest

from core.utils import network_validation as nv


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",
        "::",
        "[::]",
        "",
        "   ",
        None,
    ],
)
def test_is_unspecified_bind_detects_wildcard(host: str | None) -> None:
    assert nv.is_unspecified_bind(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "::1",
        "localhost",
        "192.168.1.10",
        "example.com",
    ],
)
def test_is_unspecified_bind_rejects_normal_hosts(host: str) -> None:
    assert nv.is_unspecified_bind(host) is False


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.5.4.3",
        "::1",
        "[::1]",
        "localhost",
        "LOCALHOST",
        "ip6-localhost",
    ],
)
def test_is_loopback_host_recognises_loopback(host: str) -> None:
    assert nv.is_loopback_host(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",
        "8.8.8.8",
        "example.com",
        "",
    ],
)
def test_is_loopback_host_rejects_non_loopback(host: str) -> None:
    assert nv.is_loopback_host(host) is False


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("0.0.0.0", True),
        ("::", True),
        ("::1", True),
        ("8.8.8.8", False),
        ("example.com", False),
    ],
)
def test_is_local_only_host(host: str, expected: bool) -> None:
    assert nv.is_local_only_host(host) is expected


@pytest.mark.parametrize(
    "hostname",
    [
        "localhost",
        "api.example.com",
        "service-1.internal",
        "a",
    ],
)
def test_is_valid_hostname_accepts_valid(hostname: str) -> None:
    assert nv.is_valid_hostname(hostname) is True


@pytest.mark.parametrize(
    "hostname",
    [
        "",
        "-leading-dash",
        "trailing-dash-",
        "double..dot",
        "spa ce",
        "under_score",
        "x" * 254,
    ],
)
def test_is_valid_hostname_rejects_invalid(hostname: str) -> None:
    assert nv.is_valid_hostname(hostname) is False


def test_validate_bind_host_allows_loopback() -> None:
    assert nv.validate_bind_host("127.0.0.1") == "127.0.0.1"
    assert nv.validate_bind_host("localhost") == "localhost"
    assert nv.validate_bind_host("::1") == "::1"


def test_validate_bind_host_allows_public_outside_production() -> None:
    assert nv.validate_bind_host("0.0.0.0", env="development") == "0.0.0.0"
    assert nv.validate_bind_host("::", env="") == "::"


def test_validate_bind_host_blocks_wildcard_in_production() -> None:
    with pytest.raises(ValueError, match="production"):
        nv.validate_bind_host("0.0.0.0", env="production", allow_public=False)
    with pytest.raises(ValueError, match="production"):
        nv.validate_bind_host("::", env="PRODUCTION", allow_public=False)


def test_validate_bind_host_allows_wildcard_in_production_with_flag() -> None:
    assert (
        nv.validate_bind_host("0.0.0.0", env="production", allow_public=True)
        == "0.0.0.0"
    )


def test_validate_bind_host_uses_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")
    monkeypatch.delenv("SIDAR_ALLOW_PUBLIC_BIND", raising=False)
    with pytest.raises(ValueError):
        nv.validate_bind_host("0.0.0.0")

    monkeypatch.setenv("SIDAR_ALLOW_PUBLIC_BIND", "true")
    assert nv.validate_bind_host("0.0.0.0") == "0.0.0.0"


def test_validate_bind_host_rejects_empty() -> None:
    with pytest.raises(ValueError):
        nv.validate_bind_host("")
    with pytest.raises(ValueError):
        nv.validate_bind_host(None)  # type: ignore[arg-type]


def test_validate_bind_host_rejects_invalid_hostname() -> None:
    with pytest.raises(ValueError, match="geçersiz"):
        nv.validate_bind_host("bad host name!")


def test_validate_bind_host_accepts_hostname() -> None:
    assert nv.validate_bind_host("api.internal.example") == "api.internal.example"


def test_is_production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")
    assert nv.is_production_env() is True
    monkeypatch.setenv("SIDAR_ENV", "development")
    assert nv.is_production_env() is False
    assert nv.is_production_env(env="production") is True


def test_is_public_bind_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIDAR_ALLOW_PUBLIC_BIND", raising=False)
    assert nv.is_public_bind_allowed() is False
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("SIDAR_ALLOW_PUBLIC_BIND", truthy)
        assert nv.is_public_bind_allowed() is True
    monkeypatch.setenv("SIDAR_ALLOW_PUBLIC_BIND", "no")
    assert nv.is_public_bind_allowed() is False
    assert nv.is_public_bind_allowed(flag="1") is True
