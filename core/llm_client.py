"""Sidar Project - LLM İstemcisi.

Ollama, Google Gemini, OpenAI ve Anthropic API entegrasyonu (Asenkron, OOP tabanlı).
"""

from __future__ import annotations

import asyncio
import codecs
import importlib
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any, cast

import httpx
from opentelemetry import trace

import core.utils.token_counter as token_counter
from config import OLLAMA_BATCH_POLICY
from core.cache_metrics import record_cache_skip
from core.dlp import mask_messages as _dlp_mask_messages
from core.llm.cache import SemanticChatCache
from core.llm.facade import LLMProvider as LLMProvider
from core.llm.router import LLMRoutingService
from core.llm.streaming import (
    fallback_stream,
    trace_stream_metrics,
    track_stream_completion,
    track_stream_routing_cost,
)
from core.llm_metrics import get_current_metrics_user_id, get_llm_metrics_collector
from core.router import record_routing_cost
from core.utils.json_repair import (
    is_safe_literal_eval_candidate,
    repair_json_text,
    repair_json_text_async,
)

if TYPE_CHECKING:
    from core.llm.gemini import GeminiClient
    from core.llm.ollama import OllamaClient

logger = logging.getLogger(__name__)
_COMPAT_IMPORTED_MODULES = (codecs, importlib)

# Geriye dönük test/yardımcı erişimleri
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

DEFAULT_COST_PER_TOKEN_USD = 2e-6
OLLAMA_NUM_BATCH_DEFAULT = OLLAMA_BATCH_POLICY.default
OLLAMA_NUM_BATCH_MAX = OLLAMA_BATCH_POLICY.maximum
OLLAMA_NUM_BATCH_AUTO_MIN = OLLAMA_BATCH_POLICY.auto_min
_OLLAMA_GPU_LIMITERS: dict[tuple[str, int], asyncio.Semaphore] = {}
_OLLAMA_GPU_LIMITERS_LOCK = asyncio.Lock()
MAX_SAFE_TOKEN_COUNT = 2_147_483_647
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
MODEL_COSTS_PER_TOKEN_USD: dict[str, float] = {
    "gpt-4o": 5e-6,
    "gpt-4o-mini": 2e-6,
    "claude-3-5-sonnet": 3e-6,
    "claude-3-5-sonnet-latest": 3e-6,
    "gemini-1.5-pro": 3.5e-6,
    "gemini-1.5-flash": 7.5e-7,
}

# Sağlayıcıdan bağımsız, tüm istemcilerin system prompt'una enjekte ettiği standart JSON talimatı
SIDAR_TOOL_JSON_INSTRUCTION: str = (
    "Yalnızca aşağıdaki JSON şemasına uygun tek bir JSON nesnesi döndür. "
    'Şema: {"thought": string, "tool": string, "argument": string}. '
    "Ek açıklama, markdown kod bloğu veya ek metin ekleme; sadece ham JSON."
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


def _format_exception_message(exc: Exception) -> str:
    """İstisna mesajı boş olduğunda hata tipini log/mesaja dahil et."""
    detail = str(exc).strip()
    if detail:
        return detail
    return exc.__class__.__name__


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
    async for chunk in fallback_stream(msg):
        yield chunk


def _get_tracer(config: Any) -> Any:
    if getattr(config, "ENABLE_TRACING", False):
        return trace.get_tracer(__name__)
    return None


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


def _resolve_cost_per_token_usd(config: Any, model: str = "") -> float:
    raw_map = getattr(config, "COST_ROUTING_MODEL_COSTS_USD", None)
    if isinstance(raw_map, dict):
        for key, value in raw_map.items():
            if str(key).strip().lower() == (model or "").strip().lower():
                try:
                    return float(value)
                except (TypeError, ValueError):
                    break

    normalized = (model or "").strip().lower()
    if normalized:
        for known_model, known_cost in sorted(
            MODEL_COSTS_PER_TOKEN_USD.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if normalized.startswith(known_model):
                return known_cost

    configured_default = getattr(config, "COST_ROUTING_TOKEN_COST_USD", DEFAULT_COST_PER_TOKEN_USD)
    try:
        return float(configured_default or DEFAULT_COST_PER_TOKEN_USD)
    except (TypeError, ValueError):
        return DEFAULT_COST_PER_TOKEN_USD


def _estimate_tokens_bounded(text: str, *, model: str = "") -> int:
    """Estimate tokens with overflow/negative protection."""
    try:
        return _safe_token_count(token_counter.estimate_tokens(text, model=model))
    except Exception as exc:
        logger.debug("Token estimate failed; treating prompt as zero tokens: %s", exc)
        return 0


def _estimate_message_tokens(messages: list[dict[str, str]], *, model: str = "") -> int:
    """Estimate bounded tokens for a chat message list."""
    prompt_text = "\n".join(str(m.get("content") or "") for m in messages)
    return _estimate_tokens_bounded(prompt_text, model=model)


def _configured_prompt_token_limit(config: Any) -> int:
    """Return configured prompt token limit; zero disables preflight rejection."""
    for key in ("LLM_MAX_PROMPT_TOKENS", "MAX_INPUT_TOKENS"):
        raw_limit = getattr(config, key, 0)
        if not isinstance(raw_limit, str | int | float | bool):
            continue
        limit = _safe_token_count(raw_limit)
        if limit > 0:
            return limit
    return 0


def _validate_prompt_token_budget(
    *, provider: str, messages: list[dict[str, str]], config: Any, model: str = ""
) -> int:
    """Validate estimated prompt tokens before dispatching to a provider."""
    prompt_tokens = _estimate_message_tokens(messages, model=model)
    limit = _configured_prompt_token_limit(config)
    if limit > 0 and prompt_tokens > limit:
        raise LLMAPIError(
            provider,
            f"Prompt token budget exceeded: estimated={prompt_tokens} limit={limit}",
            status_code=413,
            retryable=False,
        )
    return prompt_tokens


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
    async for chunk in track_stream_completion(
        stream_iter,
        provider=provider,
        model=model,
        started_at=started_at,
        record_metric=_record_llm_metric,
    ):
        yield chunk


async def _track_stream_routing_cost(
    stream_iter: AsyncIterator[str],
    *,
    messages: list[dict[str, str]],
    config: Any,
    model: str = "",
) -> AsyncIterator[str]:
    tracked = track_stream_routing_cost(
        stream_iter,
        messages=messages,
        config=config,
        model=model,
        estimate_tokens=lambda text: _estimate_tokens_bounded(text, model=model),
        resolve_cost_per_token=_resolve_cost_per_token_usd,
        record_cost=record_routing_cost,
    )
    try:
        async for chunk in tracked:
            yield chunk
    finally:
        await cast(Any, tracked).aclose()


async def _trace_stream_metrics(
    stream_iter: AsyncIterator[str], span: Any, started_at: float
) -> AsyncGenerator[str, None]:
    async for chunk in trace_stream_metrics(stream_iter, span, started_at):
        yield chunk


class BaseLLMClient(ABC):
    """LLM sağlayıcıları için soyut istemci arayüzü."""

    def __init__(self, config: Any) -> None:
        self.config = config

    @abstractmethod
    def json_mode_config(self) -> dict[str, Any]:
        """json_mode=True çağrısında payload'a eklenecek sağlayıcıya özel ayarları döndürür."""

    @staticmethod
    def _inject_json_instruction(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Mesaj listesindeki system mesajına JSON şema talimatını ekler.

        System mesajı yoksa listenin başına yeni bir tane eklenir.
        """
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


ProviderRegistryEntry = tuple[str, str] | type[BaseLLMClient]

_PROVIDER_IMPORTS: dict[str, ProviderRegistryEntry] = {
    "ollama": ("core.llm.ollama", "OllamaClient"),
    "gemini": ("core.llm.gemini", "GeminiClient"),
    "openai": ("core.llm.openai", "OpenAIClient"),
    "anthropic": ("core.llm.anthropic", "AnthropicClient"),
    "litellm": ("core.llm.litellm", "LiteLLMClient"),
}
_PROVIDER_CLASS_NAMES = {
    class_name: provider
    for provider, entry in _PROVIDER_IMPORTS.items()
    if isinstance(entry, tuple)
    for _, class_name in (entry,)
}
_PROVIDER_REGISTRY_CACHE: dict[str, type[BaseLLMClient]] = {}


def _provider_class(provider: str) -> type[BaseLLMClient]:
    provider_name = (provider or "").strip().lower()
    cached = _PROVIDER_REGISTRY_CACHE.get(provider_name)
    if cached is not None:
        return cached
    entry = _PROVIDER_IMPORTS[provider_name]
    if isinstance(entry, type):
        provider_cls = entry
        class_name = entry.__name__
    else:
        module_name, class_name = entry
        provider_cls = getattr(importlib.import_module(module_name), class_name)
    if not isinstance(provider_cls, type) or not issubclass(
        provider_cls, BaseLLMClient
    ):  # pragma: no cover - corrupted registry guard
        raise TypeError(f"{class_name} BaseLLMClient alt sınıfı olmalıdır.")
    _PROVIDER_REGISTRY_CACHE[provider_name] = provider_cls
    return provider_cls


def __getattr__(name: str) -> Any:
    """Expose provider classes lazily for backward-compatible imports."""
    provider = _PROVIDER_CLASS_NAMES.get(name)
    if provider is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return _provider_class(provider)


class LLMClient:
    """Factory sınıfı: sağlayıcıya göre doğru istemciyi seçer."""

    PROVIDER_REGISTRY = _PROVIDER_IMPORTS

    def __init__(self, provider: str, config: Any) -> None:
        self.provider = provider.lower()
        self.config = config
        self._semantic_cache = SemanticChatCache(config)
        self._router = LLMRoutingService(config)
        if self.provider not in self.PROVIDER_REGISTRY:
            raise ValueError(f"Bilinmeyen AI sağlayıcısı: {self.provider}")
        self._client = _provider_class(self.provider)(config)

    @classmethod
    def register_provider(cls, name: str, provider_cls: type[BaseLLMClient]) -> None:
        """Register a provider strategy without editing the facade dispatch code."""
        provider_name = (name or "").strip().lower()
        if not provider_name:
            raise ValueError("Provider adı boş olamaz.")
        if not isinstance(provider_cls, type) or not issubclass(provider_cls, BaseLLMClient):
            raise TypeError("Provider sınıfı BaseLLMClient alt sınıfı olmalıdır.")
        cls.PROVIDER_REGISTRY[provider_name] = (provider_cls.__module__, provider_cls.__name__)
        _PROVIDER_REGISTRY_CACHE[provider_name] = provider_cls

    @property
    def _ollama_base_url(self) -> str:
        """Geriye dönük uyumluluk: Ollama taban URL bilgisi."""
        ollama_cls = _provider_class("ollama")
        if isinstance(self._client, ollama_cls):
            ollama_client = cast("OllamaClient", self._client)
            return ollama_client.base_url
        return str(_setting(self.config, "OLLAMA_URL", "http://localhost:11434")).removesuffix(
            "/api"
        )

    def _build_ollama_timeout(self) -> httpx.Timeout:
        """Geriye dönük uyumluluk: eski timeout yardımcı adı."""
        ollama_cls = _provider_class("ollama")
        if isinstance(self._client, ollama_cls):
            ollama_client = cast("OllamaClient", self._client)
            return ollama_client._build_timeout()
        timeout_seconds = max(10, int(_setting(self.config, "OLLAMA_TIMEOUT", 120)))
        return httpx.Timeout(timeout_seconds, connect=10.0)

    def _truncate_messages_for_local_model(
        self, messages: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Yerel modellerde bağlam taşmasını azaltmak için mesajları karakter bazlı kırp."""
        max_chars = max(1200, int(_setting(self.config, "OLLAMA_CONTEXT_MAX_CHARS", 12000)))
        if not messages:
            return messages

        normalized: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = str(msg.get("content") or "")
            normalized.append({"role": role, "content": content})

        total = sum(len(m["content"]) for m in normalized)
        if total <= max_chars:
            return normalized

        def _is_rag_context_message(msg: dict[str, str]) -> bool:
            role = str(msg.get("role", "")).lower()
            if role in {"tool", "context"}:
                return True
            content_l = str(msg.get("content", "")).lower()
            return any(marker in content_l for marker in ("[rag]", "<rag>", "retrieval", "kaynak"))

        # Önce en son mesajı tam tutmaya çalış, ardından system mesajını sınırlı tut,
        # sonra geçmişi sondan başa doğru doldur.
        result: list[dict[str, str]] = []
        used = 0

        last_msg = normalized[-1]
        last_keep = max(400, min(len(last_msg["content"]), max_chars // 2))
        last_content = last_msg["content"][-last_keep:]
        result.insert(0, {"role": last_msg["role"], "content": last_content})
        used += len(last_content)

        system_idx = next((i for i, m in enumerate(normalized) if m["role"] == "system"), None)
        if system_idx is not None and system_idx != len(normalized) - 1 and used < max_chars:
            system_msg = normalized[system_idx]
            budget = max(200, min(max_chars - used, max_chars // 3))
            system_content = system_msg["content"][:budget]
            if system_content:
                result.insert(0, {"role": "system", "content": system_content})
                used += len(system_content)

        rag_idx = next(
            (
                i
                for i in range(len(normalized) - 2, -1, -1)
                if _is_rag_context_message(normalized[i])
            ),
            None,
        )
        if rag_idx is not None and used < max_chars:
            rag_msg = normalized[rag_idx]
            remaining = max_chars - used
            rag_content = rag_msg["content"]
            if len(rag_content) > remaining:
                # RAG mesajlarının başındaki başlık/yönergeleri korumak için
                # sondan değil baştan kırp.
                rag_content = rag_content[:remaining]
            if rag_content:
                insert_at = 1 if result and result[0]["role"] == "system" else 0
                result.insert(insert_at, {"role": rag_msg["role"], "content": rag_content})
                used += len(rag_content)

        for idx in range(len(normalized) - 2, -1, -1):
            msg = normalized[idx]
            if used >= max_chars:
                break
            if msg["role"] == "system":
                continue
            if rag_idx is not None and idx == rag_idx:
                continue
            remaining = max_chars - used
            content = msg["content"]
            if len(content) > remaining:
                content = content[-remaining:]
            if content:
                result.insert(
                    1 if result and result[0]["role"] == "system" else 0,
                    {"role": msg["role"], "content": content},
                )
                used += len(content)

        return result

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + list(messages)

        # Cost-Aware Routing: karmaşıklık + bütçeye göre provider/model seç
        routed_provider, routed_model = self._router.select(messages, self.provider, model)
        if routed_provider != self.provider:
            # Farklı sağlayıcıya yönlendirme — geçici istemci oluştur
            try:
                routed_client = LLMClient(routed_provider, self.config)
                return await routed_client.chat(
                    messages=messages,
                    model=routed_model or model,
                    system_prompt=None,
                    temperature=temperature,
                    stream=stream,
                    json_mode=json_mode,
                )
            except Exception as exc:
                logger.warning(
                    "CostRouter yönlendirme başarısız (%s): %s — varsayılana dönülüyor.",
                    routed_provider,
                    exc,
                )
        else:
            model = routed_model or model

        if self.provider == "ollama":
            messages = self._truncate_messages_for_local_model(messages)

        # DLP: hassas verileri API çağrısından önce maskele
        masked_messages = _dlp_mask_messages(cast(list[Mapping[str, Any]], messages))
        messages = [
            {"role": str(message.get("role", "")), "content": str(message.get("content", ""))}
            for message in masked_messages
        ]

        _validate_prompt_token_budget(
            provider=self.provider, messages=messages, config=self.config, model=str(model or "")
        )

        user_prompt = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                user_prompt = (message.get("content") or "").strip()
                break

        if (not stream) and user_prompt:
            cached_response = await self._semantic_cache.get(user_prompt)
            if cached_response is not None:
                return str(cached_response)
        elif stream:
            record_cache_skip()

        response = await self._client.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            stream=stream,
            json_mode=json_mode,
        )

        if stream and self.provider != "ollama":
            if asyncio.iscoroutine(response):
                response = await response
            if isinstance(response, str):
                return _fallback_stream(response)
            return _track_stream_routing_cost(
                response,
                messages=messages,
                config=self.config,
                model=str(model or ""),
            )

        # Bulgu Y-6: Günlük bütçe izleyicisine maliyet kaydı — yalnızca bulut sağlayıcıları için
        if (not stream) and isinstance(response, str) and self.provider != "ollama":
            _msg_text = "\n".join(m.get("content") or "" for m in messages)
            _est_tokens = _estimate_tokens_bounded(
                _msg_text, model=str(model or "")
            ) + _estimate_tokens_bounded(response, model=str(model or ""))
            _cost_per_token = _resolve_cost_per_token_usd(self.config, model=str(model or ""))
            record_routing_cost(_est_tokens * _cost_per_token)

        if (not stream) and user_prompt and isinstance(response, str):
            await self._semantic_cache.set(user_prompt, response)

        return response

    async def list_ollama_models(self) -> list[str]:
        ollama_cls = _provider_class("ollama")
        if isinstance(self._client, ollama_cls):
            ollama_client = cast("OllamaClient", self._client)
            return await ollama_client.list_models()
        return []

    async def is_ollama_available(self) -> bool:
        ollama_cls = _provider_class("ollama")
        if isinstance(self._client, ollama_cls):
            ollama_client = cast("OllamaClient", self._client)
            return await ollama_client.is_available()
        return False

    async def _stream_gemini_generator(
        self, response_stream: AsyncIterator[Any]
    ) -> AsyncGenerator[str, None]:
        """Test/geri uyumluluk için Gemini stream dönüştürücüsünü dışa aç."""
        gemini_cls = _provider_class("gemini")
        gemini_client = (
            cast("GeminiClient", self._client)
            if isinstance(self._client, gemini_cls)
            else cast("GeminiClient", gemini_cls(self.config))
        )
        async for chunk in gemini_client._stream_gemini_generator(response_stream):
            yield chunk
