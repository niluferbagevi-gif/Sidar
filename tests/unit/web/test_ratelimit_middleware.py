from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Request
from starlette.datastructures import Headers

from web.middleware.ratelimit import ddos_rate_limit_middleware_impl, rate_limit_middleware_impl


def _request(path: str, method: str = "GET") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": Headers({}).raw,
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
    }
    return Request(scope)


async def _ok_next(_request: Request):
    return SimpleNamespace(status_code=200)


@pytest.mark.asyncio
async def test_ddos_rate_limit_impl_skips_health_paths() -> None:
    calls: list[tuple[str, str, int, int]] = []

    async def _limited(namespace: str, key: str, limit: int, window: int) -> bool:
        calls.append((namespace, key, limit, window))
        return True

    response = await ddos_rate_limit_middleware_impl(
        _request("/healthz"),
        _ok_next,
        get_client_ip=lambda _request: "127.0.0.1",
        redis_is_rate_limited=_limited,
        max_requests=1,
        window_sec=60,
    )

    assert response.status_code == 200
    assert calls == []


@pytest.mark.asyncio
async def test_rate_limit_impl_blocks_get_io_bucket() -> None:
    calls: list[tuple[str, str, int, int]] = []

    async def _limited(namespace: str, key: str, limit: int, window: int) -> bool:
        calls.append((namespace, key, limit, window))
        return namespace == "get"

    response = await rate_limit_middleware_impl(
        _request("/files/readme.md", "GET"),
        _ok_next,
        get_client_ip=lambda _request: "10.0.0.1",
        redis_is_rate_limited=_limited,
        chat_limit=2,
        mutation_limit=3,
        get_io_limit=4,
        window_sec=60,
        get_io_paths=("/files",),
    )

    assert response.status_code == 429
    assert calls == [("get", "10.0.0.1", 4, 60)]
