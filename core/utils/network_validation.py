"""Ağ host/IP değerleri için güvenlik odaklı doğrulama katmanı.

Bu modül, Bandit B104 (Bind to all interfaces) uyarılarını `# nosec` ile
bypass etmek yerine gelen host değerinin gerçekten beklenen sınıfa
(loopback / unspecified / geçerli IP / geçerli hostname) ait olup olmadığını
`ipaddress` modülü üzerinden doğrular.

Üretim profilinde (SIDAR_ENV=production) `0.0.0.0` veya `::` gibi tüm
arayüzlere bağlanan değerler, açıkça `SIDAR_ALLOW_PUBLIC_BIND=true`
verilmediği sürece reddedilir.
"""

from __future__ import annotations

import ipaddress
import os
import re

LOOPBACK_HOSTNAMES: frozenset[str] = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)

# RFC 1123 uyumlu temel hostname düzeni (DNS lookup yapmaz, yalnızca sözdizimi).
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)" r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)" r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def _normalize(host: str | None) -> str:
    return (host or "").strip().strip("[]").lower()


def is_unspecified_bind(host: str | None) -> bool:
    """`0.0.0.0`, `::` veya eşdeğeri "tüm arayüze bağlan" değeri için True."""
    normalized = _normalize(host)
    if not normalized:
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return ip.is_unspecified


def is_loopback_host(host: str | None) -> bool:
    """Loopback IP veya bilinen yerel hostname için True döner."""
    normalized = _normalize(host)
    if not normalized:
        return False
    if normalized in LOOPBACK_HOSTNAMES:
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return ip.is_loopback


def is_local_only_host(host: str | None) -> bool:
    """Loopback veya unspecified (yerel ağ tarafına açılmamış) host için True."""
    return is_loopback_host(host) or is_unspecified_bind(host)


def is_valid_hostname(host: str | None) -> bool:
    """RFC 1123 hostname sözdizimine uyuyor mu (DNS lookup yapmadan)."""
    normalized = _normalize(host)
    if not normalized:
        return False
    return bool(_HOSTNAME_RE.match(normalized))


def is_production_env(env: str | None = None) -> bool:
    """SIDAR_ENV=production kontrolü; explicit `env` öncelikli."""
    value = env if env is not None else os.getenv("SIDAR_ENV", "")
    return value.strip().lower() == "production"


def is_public_bind_allowed(flag: str | None = None) -> bool:
    """SIDAR_ALLOW_PUBLIC_BIND bayrağı için truthy kontrolü."""
    value = flag if flag is not None else os.getenv("SIDAR_ALLOW_PUBLIC_BIND", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def validate_bind_host(
    host: str | None,
    *,
    env: str | None = None,
    allow_public: bool | None = None,
) -> str:
    """Bind adresini doğrular, normalize edilmiş güvenli host string döner.

    - Boş değer → ValueError.
    - Bilinen loopback hostname'leri → izinli.
    - `ipaddress.ip_address` ile çözülebilen değerler doğrulanır.
    - Üretim profilinde unspecified (0.0.0.0 / ::) bağlanma yalnızca
      `SIDAR_ALLOW_PUBLIC_BIND=true` ile mümkündür; aksi halde ValueError.
    - Hostname olduğu varsayılan değerler RFC 1123 sözdiziminden geçmelidir.

    Raises:
        ValueError: Geçersiz veya politika tarafından reddedilen host için.
    """
    if host is None:
        raise ValueError("Bind host belirtilmedi (None).")
    raw = host.strip()
    if not raw:
        raise ValueError("Bind host boş olamaz.")

    candidate = raw.strip("[]")
    normalized = candidate.lower()

    if normalized in LOOPBACK_HOSTNAMES:
        return raw

    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        if not is_valid_hostname(candidate):
            raise ValueError(f"Bind host geçersiz IP veya hostname biçiminde: {host!r}") from None
        return raw

    if ip.is_unspecified:
        production = is_production_env(env)
        public_allowed = allow_public if allow_public is not None else is_public_bind_allowed()
        if production and not public_allowed:
            raise ValueError(
                "SIDAR_ENV=production iken tüm arayüzlere bağlanmak (0.0.0.0/::) "
                "yasaktır. Açıkça izin vermek için SIDAR_ALLOW_PUBLIC_BIND=true "
                "ortam değişkenini ayarlayın veya WEB_HOST değerini özel bir "
                "adres ile sınırlayın."
            )
    return raw


__all__ = [
    "LOOPBACK_HOSTNAMES",
    "is_loopback_host",
    "is_unspecified_bind",
    "is_local_only_host",
    "is_valid_hostname",
    "is_production_env",
    "is_public_bind_allowed",
    "validate_bind_host",
]
