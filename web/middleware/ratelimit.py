"""Rate-limit middleware helpers for the Sidar FastAPI app."""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

RedisRateLimitChecker = Callable[[str, str, int, int], Awaitable[bool]]
ClientIpResolver = Callable[[Request], str]
RateLimitKeyResolver = Callable[[Request, str], str]
NextHandler = Callable[[Request], Awaitable[Response]]


DEFAULT_DDOS_BYPASS_PATHS: tuple[str, ...] = (
    "/health",
    "/healthz",
    "/readyz",
    "/favicon.ico",
    "/favicon.svg",
)
DEFAULT_DDOS_BYPASS_PREFIXES: tuple[str, ...] = ("/ui/", "/static/", "/assets/")

# GET requests are rate-limited by default (mirroring the POST/DELETE mutation
# bucket below, which already applies to every path with no opt-in list) so a
# newly-added GET endpoint can't silently fall back to only the much looser
# global DDoS bucket. Only genuinely cheap/frequently-polled paths are exempt.
DEFAULT_GET_IO_EXEMPT_PATHS: tuple[str, ...] = (
    "/health",
    "/healthz",
    "/readyz",
    "/metrics",
    "/favicon.ico",
    "/favicon.svg",
)
DEFAULT_GET_IO_EXEMPT_PREFIXES: tuple[str, ...] = ("/ui/", "/static/", "/vendor/", "/assets/")


async def ddos_rate_limit_middleware_impl(
    request: Request,
    call_next: NextHandler,
    *,
    get_client_ip: ClientIpResolver,
    redis_is_rate_limited: RedisRateLimitChecker,
    max_requests: int,
    window_sec: int,
    bypass_paths: tuple[str, ...] = DEFAULT_DDOS_BYPASS_PATHS,
    bypass_prefixes: tuple[str, ...] = DEFAULT_DDOS_BYPASS_PREFIXES,
) -> Response:
    """Apply the global DDoS protection bucket for non-static/non-health requests."""
    path = request.url.path
    if any(path.startswith(prefix) for prefix in bypass_prefixes) or path in bypass_paths:
        return await call_next(request)

    client_ip = get_client_ip(request)
    if await redis_is_rate_limited("ddos", client_ip, max_requests, window_sec):
        return JSONResponse(
            status_code=429,
            content={
                "error": (
                    "⚠ Rate Limit Aşıldı: Sunucuyu korumak için geçici olarak engellendiniz. "
                    "Lütfen 1 dakika bekleyip tekrar deneyin."
                )
            },
        )

    return await call_next(request)


async def rate_limit_middleware_impl(
    request: Request,
    call_next: NextHandler,
    *,
    get_client_ip: ClientIpResolver,
    redis_is_rate_limited: RedisRateLimitChecker,
    chat_limit: int,
    mutation_limit: int,
    get_io_limit: int,
    window_sec: int,
    get_io_exempt_paths: tuple[str, ...] = DEFAULT_GET_IO_EXEMPT_PATHS,
    get_io_exempt_prefixes: tuple[str, ...] = DEFAULT_GET_IO_EXEMPT_PREFIXES,
    get_rate_limit_key: RateLimitKeyResolver | None = None,
) -> Response:
    """Apply route-class-specific chat, mutation, and IO-heavy GET rate limits."""
    client_ip = get_client_ip(request)
    key_resolver = get_rate_limit_key or (lambda _request, fallback_ip: fallback_ip)
    principal_key = key_resolver(request, client_ip)

    if request.url.path == "/ws/chat":
        if await redis_is_rate_limited("chat", principal_key, chat_limit, window_sec):
            return JSONResponse(
                {"error": "Çok fazla istek. Lütfen bir dakika bekleyin."}, status_code=429
            )
    elif request.method in ("POST", "DELETE"):
        if await redis_is_rate_limited("mut", principal_key, mutation_limit, window_sec):
            return JSONResponse(
                {"error": "Çok fazla işlem isteği. Lütfen bir dakika bekleyin."}, status_code=429
            )
    elif request.method == "GET":
        path = request.url.path
        is_exempt = path in get_io_exempt_paths or any(
            path.startswith(prefix) for prefix in get_io_exempt_prefixes
        )
        if not is_exempt:
            if await redis_is_rate_limited("get", principal_key, get_io_limit, window_sec):
                return JSONResponse(
                    {"error": "Çok fazla sorgu isteği. Lütfen bir dakika bekleyin."},
                    status_code=429,
                )

    return await call_next(request)


def parse_forwarded_ip(value: str) -> str | None:
    """Return a normalized IP from a proxy header or None when invalid."""
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if any(ch in candidate for ch in "\r\n\t "):
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def trusted_proxy_matches(direct_ip: str, trusted_proxies: Iterable[Any]) -> bool:
    """Return whether the direct peer is allowed to supply forwarding headers."""
    if "*" in trusted_proxies:
        return True
    if direct_ip in trusted_proxies:
        return True
    try:
        peer_ip = ipaddress.ip_address(direct_ip)
    except ValueError:
        return False
    for proxy in trusted_proxies:
        try:
            if peer_ip in ipaddress.ip_network(str(proxy), strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(
    request: Request,
    *,
    trusted_proxy_matches: Callable[[str], bool],
    parse_forwarded_ip: Callable[[str], str | None],
) -> str:
    """İstemci IP'sini doğrulanmış proxy başlıklarından ya da direkt bağlantıdan döndürür.

    Proxy başlıkları (X-Forwarded-For, X-Real-IP) yalnızca direkt bağlantının
    Config.TRUSTED_PROXIES listesindeki bir adresten gelmesi durumunda okunur.
    Header değeri IP parser ile doğrulanır; boş, çok satırlı, port ekli veya
    IP olmayan değerler header injection/rate-limit bypass riskine karşı yok sayılır.
    """
    client = getattr(request, "client", None)
    direct_ip = getattr(client, "host", "unknown")
    if trusted_proxy_matches(direct_ip):
        xff = request.headers.get("X-Forwarded-For", "")
        first_forwarded = xff.split(",", 1)[0] if xff else ""
        parsed_xff = parse_forwarded_ip(first_forwarded)
        if parsed_xff:
            return parsed_xff
        parsed_real_ip = parse_forwarded_ip(request.headers.get("X-Real-IP", ""))
        if parsed_real_ip:
            return parsed_real_ip
    return direct_ip
