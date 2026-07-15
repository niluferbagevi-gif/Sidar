"""Streaming helpers for the LLM facade."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any

logger = logging.getLogger("core.llm_client")

MetricRecorder = Callable[..., None]
TokenEstimator = Callable[[str], int]
CostResolver = Callable[[Any, str], float]
CostRecorder = Callable[[float], None]


async def fallback_stream(msg: str) -> AsyncGenerator[str, None]:
    """Return a single-element async stream for error/fallback paths."""

    yield msg


async def track_stream_completion(
    stream_iter: AsyncIterator[str],
    *,
    provider: str,
    model: str,
    started_at: float,
    record_metric: MetricRecorder,
) -> AsyncIterator[str]:
    """Track stream success/failure metrics while preserving streamed chunks."""

    partial_parts: list[str] = []
    partial_chars = 0
    partial_cap = 2_000
    try:
        async for chunk in stream_iter:
            if chunk and partial_chars < partial_cap:
                remaining = partial_cap - partial_chars
                partial_parts.append(str(chunk)[:remaining])
                partial_chars += min(len(str(chunk)), remaining)
            yield chunk
        record_metric(provider=provider, model=model, started_at=started_at, success=True)
    except Exception as exc:
        partial_response = "".join(partial_parts)
        logger.warning(
            "%s stream interrupted after partial response (%d chars): %s",
            provider,
            len(partial_response),
            partial_response,
        )
        try:
            record_metric(
                provider=provider,
                model=model,
                started_at=started_at,
                success=False,
                error=str(exc),
            )
        except Exception as metric_exc:
            logger.debug(
                "%s stream failure metric could not be recorded: %s",
                provider,
                metric_exc,
            )
        raise


async def track_stream_routing_cost(
    stream_iter: AsyncIterator[str],
    *,
    messages: list[dict[str, str]],
    config: Any,
    model: str = "",
    estimate_tokens: TokenEstimator,
    resolve_cost_per_token: CostResolver,
    record_cost: CostRecorder,
) -> AsyncIterator[str]:
    """Record estimated routing cost after a streamed response completes or closes."""

    response_parts: list[str] = []
    try:
        async for chunk in stream_iter:
            if chunk:
                response_parts.append(chunk)
            yield chunk
    finally:
        prompt_text = "\n".join(str(m.get("content") or "") for m in messages)
        completion_text = "".join(response_parts)
        est_tokens = estimate_tokens(prompt_text) + estimate_tokens(completion_text)
        if est_tokens > 0:
            cost_per_token = resolve_cost_per_token(config, model)
            record_cost(est_tokens * cost_per_token)


async def trace_stream_metrics(
    stream_iter: AsyncIterator[str], span: Any, started_at: float
) -> AsyncGenerator[str, None]:
    """Set TTFT/total latency span attributes for a streamed response."""

    first_token_at = None
    try:
        async for chunk in stream_iter:
            if first_token_at is None and chunk:
                first_token_at = time.monotonic()
            yield chunk
        if span is not None:
            span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
            if first_token_at is not None:
                span.set_attribute("sidar.llm.ttft_ms", (first_token_at - started_at) * 1000)
    finally:
        if span is not None:
            span.end()
