"""HTTP streaming lifecycle helpers for LLM provider adapters."""

from __future__ import annotations

import sys
from typing import Any

import httpx


async def enter_httpx_stream(
    client: httpx.AsyncClient,
    stream_cm: Any,
) -> httpx.Response:
    """Enter an httpx stream context and close the client on setup failure.

    Streaming providers create a short-lived ``AsyncClient`` before entering an
    ``httpx`` stream context. If connecting, response validation, or task
    cancellation fails before the caller receives that client, the caller's
    outer ``finally`` block cannot close it. This helper keeps the successful
    path unchanged while making failed setup attempts deterministic.
    """
    entered = False
    try:
        response = await stream_cm.__aenter__()
        entered = True
        response.raise_for_status()
        return response
    except BaseException:
        if entered:
            await stream_cm.__aexit__(*sys.exc_info())
        await client.aclose()
        raise
