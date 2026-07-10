"""Facade-independent LLM helpers shared by provider adapters.

``core/llm/<provider>.py`` modules import from here instead of
``core.llm_client``. This breaks the circular import that previously existed
between the facade (``core/llm_client.py``, which imports every provider
module) and the providers (which used to import the facade back via
``import core.llm_client as llm_facade`` for shared helpers). Anything a
provider adapter needs at import time or call time must live here, not in
``core.llm_client``.

``core/llm_client.py`` re-exports these names for backward compatibility, so
existing ``core.llm_client.X`` references keep working.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import nullcontext
from typing import Any, Protocol

import httpx
from opentelemetry import trace

from config import OLLAMA_BATCH_POLICY
from core.llm_metrics import get_current_metrics_user_id, get_llm_metrics_collector
from core.utils.json_repair import (
    is_safe_literal_eval_candidate,
    repair_json_text,
    repair_json_text_async,
)

logger = logging.getLogger("core.llm_client")

# Geriye dönük/kolaylaştırıcı test erişimleri
_repair_json_text = repair_json_text
_is_safe_literal_eval_candidate = is_safe_literal_eval_candidate

SIDAR_TOOL_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "tool": {"type": "string"},
        "argument": {"type": "string"},
    },
    "required": ["thought", "tool", "argument"],
    "additionalProperties": False,
}

# Sağlayıcıdan bağımsız, tüm istemcilerin system prompt'una enjekte ettiği standart JSON talimatı
SIDAR_TOOL_JSON_INSTRUCTION: str = (
    "Yalnızca aşağıdaki JSON şemasına uygun tek bir JSON nesnesi döndür. "
    'Şema: {"thought": string, "tool": string, "argument": string}. '
    "Ek açıklama, markdown kod bloğu veya ek metin ekleme; sadece ham JSON."
)

MAX_SAFE_TOKEN_COUNT = 2_147_483_647
OLLAMA_NUM_BATCH_DEFAULT = OLLAMA_BATCH_POLICY.default
OLLAMA_NUM_BATCH_MAX = OLLAMA_BATCH_POLICY.maximum
OLLAMA_NUM_BATCH_AUTO_MIN = OLLAMA_BATCH_POLICY.auto_min
_OLLAMA_GPU_LIMITERS: dict[tuple[str, int], asyncio.Semaphore] = {}
_OLLAMA_GPU_LIMITERS_LOCK = asyncio.Lock()
_PROVIDER_RETRYABLE_STATUS_CODES: dict[str, set[int]] = {
    "ollama": {408, 409, 425, 429, 500, 502, 503, 504},
    "gemini": {408, 409, 429, 500, 502, 503, 504},
    "openai": {408, 409, 429, 500, 502, 503, 504},
    "anthropic": {408, 409, 429, 500, 502, 503, 504, 529},
    "litellm": {408, 409, 425, 429, 500, 502, 503, 504},
}
_CONTEXT_LIMIT_MARKERS = (
    "context length",
    "context_length",
    "maximum context",
    "token limit",
    "too many tokens",
    "input is too long",
    "prompt is too long",
    "reduce the length",
)


def _setting(config: Any, key: str, default: Any) -> Any:
    return getattr(config, key, default)


def _ollama_gpu_pool_size(config: Any) -> int:
    if not bool(_setting(config, "USE_GPU", False)):
        return 0
    configured = int(_setting(config, "OLLAMA_GPU_REQUEST_POOL_SIZE", 0) or 0)
    if configured > 0:
        return max(1, min(configured, 16))
    return 1


def _ollama_gpu_backpressure_int_setting(config: Any, key: str, default: int) -> int:
    raw = _setting(config, key, default)
    if not isinstance(raw, str | int | float | bool):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _ollama_gpu_backpressure_timeout_s(config: Any) -> float:
    timeout_ms = _ollama_gpu_backpressure_int_setting(
        config, "OLLAMA_GPU_BACKPRESSURE_TIMEOUT_MS", 0
    )
    if timeout_ms <= 0:
        return 0.0
    return max(0.001, timeout_ms / 1000)


def _ollama_gpu_backpressure_poll_s(config: Any) -> float:
    poll_ms = _ollama_gpu_backpressure_int_setting(config, "OLLAMA_GPU_BACKPRESSURE_POLL_MS", 25)
    return max(0.001, min(poll_ms / 1000, 1.0))


async def _ollama_gpu_limiter(base_url: str, pool_size: int) -> asyncio.Semaphore | None:
    if pool_size <= 0:
        return None
    key = (base_url, pool_size)
    limiter = _OLLAMA_GPU_LIMITERS.get(key)
    if limiter is not None:
        return limiter
    async with _OLLAMA_GPU_LIMITERS_LOCK:
        limiter = _OLLAMA_GPU_LIMITERS.get(key)
        if limiter is None:
            limiter = asyncio.Semaphore(pool_size)
            _OLLAMA_GPU_LIMITERS[key] = limiter
        return limiter


async def _release_limiter_after_stream(
    stream: AsyncIterator[str], limiter: asyncio.Semaphore
) -> AsyncGenerator[str, None]:
    try:
        async for chunk in stream:
            yield chunk
    finally:
        limiter.release()


def _get_tracer(config: Any) -> Any:
    if getattr(config, "ENABLE_TRACING", False):
        return trace.get_tracer(__name__)
    return None


def _prepare_span_scope(config: Any, span_name: str, stream: bool) -> tuple[Any, Any | None]:
    tracer = _get_tracer(config)
    if tracer is None:
        return nullcontext(None), None
    if stream:
        return nullcontext(None), tracer.start_span(span_name)
    return tracer.start_as_current_span(span_name), None


def build_provider_json_mode_config(provider: str) -> dict[str, Any]:
    """Sidar'ın tekil araç JSON formatını sağlayıcıya göre adapte eder."""
    provider = (provider or "").lower()
    if provider == "ollama":
        return {"format": SIDAR_TOOL_JSON_SCHEMA}
    if provider == "openai":
        # Chat Completions endpointi için yaygın JSON object modu.
        return {"response_format": {"type": "json_object"}}
    if provider == "litellm":
        return {"response_format": {"type": "json_object"}}
    if provider == "gemini":
        return {"generation_config": {"response_mime_type": "application/json"}}
    if provider == "anthropic":
        return {}
    return {}


class LLMAPIError(RuntimeError):
    """Sağlayıcı çağrılarında standart hata sözleşmesi."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


async def _acquire_ollama_gpu_limiter(limiter: asyncio.Semaphore, config: Any) -> float:
    """Acquire the shared Ollama GPU limiter with optional bounded backpressure.

    Returns the queue wait in milliseconds. A zero timeout keeps the historical
    behavior: wait until a GPU slot is available.
    """

    timeout_s = _ollama_gpu_backpressure_timeout_s(config)
    started_at = time.monotonic()
    if timeout_s <= 0:
        await limiter.acquire()
        return (time.monotonic() - started_at) * 1000

    poll_s = min(_ollama_gpu_backpressure_poll_s(config), timeout_s)
    deadline = started_at + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LLMAPIError(
                "ollama",
                "Ollama GPU request pool saturated; adaptive backpressure timeout exceeded.",
                status_code=429,
                retryable=True,
            )
        try:
            await asyncio.wait_for(limiter.acquire(), timeout=min(poll_s, remaining))
            return (time.monotonic() - started_at) * 1000
        except TimeoutError:
            continue


def _safe_token_count(value: Any) -> int:
    """Return a non-negative bounded token count for provider usage payloads."""
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    if parsed <= 0:
        return 0
    return min(parsed, MAX_SAFE_TOKEN_COUNT)


def _extract_status_code(exc: Exception) -> int | None:
    """Extract an HTTP-like status code from SDK/httpx exceptions."""
    status_code = getattr(exc, "status_code", None)
    http_status_error = getattr(httpx, "HTTPStatusError", None)
    if http_status_error and isinstance(exc, http_status_error):
        status_code = exc.response.status_code
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    try:
        return int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        return None


def _format_exception_message(exc: Exception) -> str:
    """İstisna mesajı boş olduğunda hata tipini log/mesaja dahil et."""
    detail = str(exc).strip()
    if detail:
        return detail
    return exc.__class__.__name__


def _is_context_limit_error(exc: Exception) -> bool:
    detail = _format_exception_message(exc).lower()
    return any(marker in detail for marker in _CONTEXT_LIMIT_MARKERS)


def _is_retryable_exception(exc: Exception, provider: str = "") -> tuple[bool, int | None]:
    provider_key = (provider or getattr(exc, "provider", "") or "").strip().lower()
    status_code = _extract_status_code(exc)

    if isinstance(exc, LLMAPIError):
        if _is_context_limit_error(exc):
            return False, status_code
        if exc.retryable:
            return True, status_code
        if status_code is None:
            return False, None

    if _is_context_limit_error(exc):
        return False, status_code

    retryable_statuses = _PROVIDER_RETRYABLE_STATUS_CODES.get(
        provider_key, _PROVIDER_RETRYABLE_STATUS_CODES["openai"]
    )
    if status_code is not None:
        return status_code in retryable_statuses, status_code

    if isinstance(
        exc, httpx.TimeoutException | httpx.ConnectError | httpx.ReadError | asyncio.TimeoutError
    ):
        return True, status_code
    return False, status_code


async def _retry_with_backoff(
    provider: str,
    operation: Any,
    *,
    config: Any,
    retry_hint: str,
) -> Any:
    max_retries = max(0, int(getattr(config, "LLM_MAX_RETRIES", 2) or 0))
    base_delay = max(0.05, float(getattr(config, "LLM_RETRY_BASE_DELAY", 0.4) or 0.4))
    max_delay = max(base_delay, float(getattr(config, "LLM_RETRY_MAX_DELAY", 4.0) or 4.0))

    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as exc:
            retryable, status_code = _is_retryable_exception(exc, provider=provider)
            err_detail = _format_exception_message(exc)
            if (not retryable) or attempt >= max_retries:
                message = f"{retry_hint}: {err_detail}"
                raise LLMAPIError(
                    provider, message, status_code=status_code, retryable=retryable
                ) from exc

            jitter_cap = min(0.5, base_delay)
            delay = min(max_delay, base_delay * (2**attempt)) + random.uniform(0, jitter_cap)  # nosec B311  # güvenlik değil jitter/backoff amaçlıdır.
            attempt += 1
            logger.warning(
                "%s geçici hata (%s). %d/%d yeniden deneme %.2fs sonra yapılacak.",
                provider,
                err_detail,
                attempt,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)


def _ensure_json_text(text: str, provider: str) -> str:
    """json_mode çağrılarında düz metin sızıntısını güvenli JSON'a çevir."""
    raw = text or ""
    try:
        json.loads(raw)
        return raw
    except Exception:
        repaired = _repair_json_text(raw)
        if repaired is not None:
            logger.warning(
                "%s: JSON dışı yanıt alındı, onarım uygulanıp JSON'a çevrildi.", provider
            )
            return str(repaired)
        logger.warning("%s: JSON dışı yanıt alındı, fallback uygulanıyor.", provider)
        return json.dumps(
            {
                "thought": f"{provider} sağlayıcısı JSON dışı içerik döndürdü.",
                "tool": "final_answer",
                "argument": raw or "[UYARI] Sağlayıcı boş içerik döndürdü.",
            },
            ensure_ascii=False,
        )


async def _ensure_json_text_async(text: str, provider: str) -> str:
    """json_mode çağrılarında düz metin sızıntısını güvenli JSON'a çevir (async onarım)."""
    raw = text or ""
    try:
        json.loads(raw)
        return raw
    except Exception:
        repaired = await repair_json_text_async(raw)
        if repaired is not None:
            logger.warning(
                "%s: JSON dışı yanıt alındı, onarım uygulanıp JSON'a çevrildi.", provider
            )
            return str(repaired)
        logger.warning("%s: JSON dışı yanıt alındı, fallback uygulanıyor.", provider)
        return json.dumps(
            {
                "thought": f"{provider} sağlayıcısı JSON dışı içerik döndürdü.",
                "tool": "final_answer",
                "argument": raw or "[UYARI] Sağlayıcı boş içerik döndürdü.",
            },
            ensure_ascii=False,
        )


async def _fallback_stream(msg: str) -> AsyncGenerator[str, None]:
    """Hata durumlarında tek elemanlı asenkron akış döndürür."""
    yield msg


def _extract_usage_tokens(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    if not isinstance(usage, dict):
        return 0, 0

    prompt = _safe_token_count(usage.get("prompt_tokens", 0))
    completion = _safe_token_count(usage.get("completion_tokens", usage.get("output_tokens", 0)))
    return prompt, completion


def _extract_gemini_usage_tokens(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or getattr(response, "usage", None)
    if usage is None:
        return 0, 0

    if isinstance(usage, dict):
        prompt = _safe_token_count(
            usage.get(
                "prompt_token_count", usage.get("input_token_count", usage.get("prompt_tokens", 0))
            )
        )
        completion = _safe_token_count(
            usage.get(
                "candidates_token_count",
                usage.get(
                    "output_token_count",
                    usage.get("completion_tokens", usage.get("output_tokens", 0)),
                ),
            )
        )
        return prompt, completion

    prompt = _safe_token_count(
        getattr(usage, "prompt_token_count", getattr(usage, "input_token_count", 0))
    )
    completion = _safe_token_count(
        getattr(
            usage,
            "candidates_token_count",
            getattr(usage, "output_token_count", getattr(usage, "completion_tokens", 0)),
        )
    )
    return prompt, completion


def _record_llm_metric(
    *,
    provider: str,
    model: str,
    started_at: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    success: bool = True,
    error: str = "",
) -> None:
    get_llm_metrics_collector().record(
        provider=provider,
        model=model,
        latency_ms=(time.monotonic() - started_at) * 1000,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        success=success,
        error=error,
        user_id=get_current_metrics_user_id(),
    )


async def _track_stream_completion(
    stream_iter: AsyncIterator[str],
    *,
    provider: str,
    model: str,
    started_at: float,
) -> AsyncIterator[str]:
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
        _record_llm_metric(provider=provider, model=model, started_at=started_at, success=True)
    except Exception as exc:
        partial_response = "".join(partial_parts)
        logger.warning(
            "%s stream interrupted after partial response (%d chars): %s",
            provider,
            len(partial_response),
            partial_response,
        )
        try:
            _record_llm_metric(
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


async def _trace_stream_metrics(
    stream_iter: AsyncIterator[str], span: Any, started_at: float
) -> AsyncGenerator[str, None]:
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


class LLMProvider(Protocol):
    """Strategy contract implemented by provider adapters behind the LLM facade."""

    async def generate(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Generate streaming text chunks for the given chat messages."""
        ...

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        """Provider-specific chat call used by the compatibility facade."""
        ...


class BaseLLMClient(ABC):
    """LLM sağlayıcıları için soyut istemci arayüzü."""

    def __init__(self, config: Any) -> None:
        self.config = config

    @abstractmethod
    def json_mode_config(self) -> dict[str, Any]:
        """json_mode=True çağrısında payload'a eklenecek sağlayıcıya özel ayarları döndürür."""

    @staticmethod
    def _inject_json_instruction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Mesaj listesindeki system mesajına JSON şema talimatını ekler (system yoksa başa ekler)."""
        result = list(messages)
        for i, msg in enumerate(result):
            if msg.get("role") == "system":
                existing = (msg.get("content") or "").strip()
                result[i] = {
                    **msg,
                    "content": f"{existing}\n\n{SIDAR_TOOL_JSON_INSTRUCTION}".strip(),
                }
                return result
        return [{"role": "system", "content": SIDAR_TOOL_JSON_INSTRUCTION}] + result

    @staticmethod
    async def _iter_openai_compatible_stream_lines(
        response: httpx.Response,
    ) -> AsyncGenerator[dict[str, Any], None]:
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                body = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(body, dict):
                yield body

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        """Sağlayıcıya özel chat çağrısı."""

    async def generate(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Strategy API: stream generated chunks regardless of provider implementation."""
        response = await self.chat(messages, stream=True, **kwargs)
        if isinstance(response, str):
            yield response
            return
        async for chunk in response:
            yield chunk
