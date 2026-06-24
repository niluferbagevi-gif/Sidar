"""Rate-limit middleware helpers for the Sidar FastAPI app."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

RedisRateLimitChecker = Callable[[str, str, int, int], Awaitable[bool]]
ClientIpResolver = Callable[[Request], str]
NextHandler = Callable[[Request], Awaitable[Response]]


_DEFAULT_BYPASS_PATHS: tuple[str, ...] = ("/health", "/healthz", "/readyz")
_DEFAULT_BYPASS_PREFIXES: tuple[str, ...] = ("/ui/", "/static/")


async def ddos_rate_limit_middleware_impl(
    request: Request,
    call_next: NextHandler,
    *,
    get_client_ip: ClientIpResolver,
    redis_is_rate_limited: RedisRateLimitChecker,
    max_requests: int,
    window_sec: int,
    bypass_paths: tuple[str, ...] = _DEFAULT_BYPASS_PATHS,
    bypass_prefixes: tuple[str, ...] = _DEFAULT_BYPASS_PREFIXES,
) -> Response:
    """Apply the global DDoS protection bucket for non-static/non-health requests."""
    path = request.url.path
    if path in bypass_paths or any(path.startswith(prefix) for prefix in bypass_prefixes):
        return await call_next(request)

    client_ip = get_client_ip(request)
    if await redis_is_rate_limited("ddos", client_ip, max_requests, window_sec):
        return JSONResponse(
            status_code=429,
            content={
                "error": "⚠ Rate Limit Aşıldı: Sunucuyu korumak için geçici olarak engellendiniz. Lütfen 1 dakika bekleyip tekrar deneyin."
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
    get_io_paths: tuple[str, ...],
) -> Response:
    """Apply route-class-specific chat, mutation, and IO-heavy GET rate limits."""
    client_ip = get_client_ip(request)

    if request.url.path == "/ws/chat":
        if await redis_is_rate_limited("chat", client_ip, chat_limit, window_sec):
            return JSONResponse(
                {"error": "Çok fazla istek. Lütfen bir dakika bekleyin."}, status_code=429
            )
    elif request.method in ("POST", "DELETE"):
        if await redis_is_rate_limited("mut", client_ip, mutation_limit, window_sec):
            return JSONResponse(
                {"error": "Çok fazla işlem isteği. Lütfen bir dakika bekleyin."}, status_code=429
            )
    elif request.method == "GET":
        if any(request.url.path.startswith(path) for path in get_io_paths):
            if await redis_is_rate_limited("get", client_ip, get_io_limit, window_sec):
                return JSONResponse(
                    {"error": "Çok fazla sorgu isteği. Lütfen bir dakika bekleyin."},
                    status_code=429,
                )

    return await call_next(request)
