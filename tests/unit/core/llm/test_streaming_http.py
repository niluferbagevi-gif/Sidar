"""Tests for LLM HTTP streaming lifecycle helpers."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from core.llm.streaming_http import enter_httpx_stream


class _TrackedClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FailingStreamContext:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.exited = False

    async def __aenter__(self) -> httpx.Response:
        raise self.exc

    async def __aexit__(self, *_exc_info: object) -> None:
        self.exited = True


class _StatusFailingStreamContext:
    def __init__(self) -> None:
        self.exited = False

    async def __aenter__(self) -> httpx.Response:
        return httpx.Response(503, request=httpx.Request("GET", "http://example.test"))

    async def __aexit__(self, *_exc_info: object) -> None:
        self.exited = True


@pytest.mark.asyncio
async def test_enter_httpx_stream_closes_client_when_enter_fails() -> None:
    """A setup failure before ownership is returned must not leak AsyncClient."""
    client = _TrackedClient()
    stream_cm = _FailingStreamContext(RuntimeError("connect failed"))

    with pytest.raises(RuntimeError, match="connect failed"):
        await enter_httpx_stream(client, stream_cm)

    assert client.closed is True
    assert stream_cm.exited is False


@pytest.mark.asyncio
async def test_enter_httpx_stream_exits_stream_and_closes_client_on_bad_status() -> None:
    """A response status failure must exit the stream context and close the client."""
    client = _TrackedClient()
    stream_cm = _StatusFailingStreamContext()

    with pytest.raises(httpx.HTTPStatusError):
        await enter_httpx_stream(client, stream_cm)

    assert stream_cm.exited is True
    assert client.closed is True


@pytest.mark.asyncio
async def test_enter_httpx_stream_closes_client_on_cancellation() -> None:
    """Cancellation during stream setup must also close the newly created client."""
    client = _TrackedClient()
    stream_cm = _FailingStreamContext(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await enter_httpx_stream(client, stream_cm)

    assert client.closed is True
