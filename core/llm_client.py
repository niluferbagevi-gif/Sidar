"""
Sidar Project - LLM İstemcisi
Ollama, Google Gemini, OpenAI ve Anthropic API entegrasyonu (Asenkron, OOP tabanlı).
"""

from __future__ import annotations

import asyncio
import codecs
import inspect
import json
import logging
import random
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import nullcontext
from typing import Any

import httpx
from opentelemetry import trace

import core.utils.token_counter as token_counter
from core.cache.semantic_cache import SemanticCacheManager
from core.cache_metrics import record_cache_skip
from core.dlp import mask_messages as _dlp_mask_messages
from core.llm_metrics import get_current_metrics_user_id, get_llm_metrics_collector
from core.router import CostAwareRouter, record_routing_cost
from core.utils.json_repair import (
    is_safe_literal_eval_candidate,
    repair_json_text,
    repair_json_text_async,
)

logger = logging.getLogger(__name__)

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


def _prepare_span_scope(
    config: Any, span_name: str, stream: bool
) -> tuple[Any, Any | None]:
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


def _is_retryable_exception(exc: Exception) -> tuple[bool, int | None]:
    status_code = getattr(exc, "status_code", None)
    http_status_error = getattr(httpx, "HTTPStatusError", None)
    if http_status_error and isinstance(exc, http_status_error):
        status_code = exc.response.status_code
    if status_code == 429 or (status_code is not None and 500 <= int(status_code) < 600):
        return True, int(status_code)
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
            retryable, status_code = _is_retryable_exception(exc)
            if (not retryable) or attempt >= max_retries:
                message = f"{retry_hint}: {exc}"
                raise LLMAPIError(
                    provider, message, status_code=status_code, retryable=retryable
                ) from exc

            jitter_cap = min(0.5, base_delay)
            delay = min(max_delay, base_delay * (2**attempt)) + random.uniform(0, jitter_cap)
            attempt += 1
            logger.warning(
                "%s geçici hata (%s). %d/%d yeniden deneme %.2fs sonra yapılacak.",
                provider,
                exc,
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
            return repaired
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
            return repaired
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


def _get_tracer(config: Any) -> Any:
    if getattr(config, "ENABLE_TRACING", False):
        return trace.get_tracer(__name__)
    return None


def _extract_usage_tokens(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    if not isinstance(usage, dict):
        return 0, 0

    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    prompt = _safe_int(usage.get("prompt_tokens", 0))
    completion = _safe_int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
    return prompt, completion


def _extract_gemini_usage_tokens(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or getattr(response, "usage", None)
    if usage is None:
        return 0, 0

    if isinstance(usage, dict):
        prompt = int(
            usage.get(
                "prompt_token_count", usage.get("input_token_count", usage.get("prompt_tokens", 0))
            )
            or 0
        )
        completion = int(
            usage.get(
                "candidates_token_count",
                usage.get(
                    "output_token_count",
                    usage.get("completion_tokens", usage.get("output_tokens", 0)),
                ),
            )
            or 0
        )
        return prompt, completion

    prompt = int(getattr(usage, "prompt_token_count", getattr(usage, "input_token_count", 0)) or 0)
    completion = int(
        getattr(
            usage,
            "candidates_token_count",
            getattr(usage, "output_token_count", getattr(usage, "completion_tokens", 0)),
        )
        or 0
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
    try:
        async for chunk in stream_iter:
            yield chunk
        _record_llm_metric(provider=provider, model=model, started_at=started_at, success=True)
    except Exception as exc:
        _record_llm_metric(
            provider=provider, model=model, started_at=started_at, success=False, error=str(exc)
        )
        raise


async def _track_stream_routing_cost(
    stream_iter: AsyncIterator[str],
    *,
    messages: list[dict[str, str]],
    config: Any,
    model: str = "",
) -> AsyncIterator[str]:
    response_parts: list[str] = []
    try:
        async for chunk in stream_iter:
            if chunk:
                response_parts.append(chunk)
            yield chunk
    finally:
        prompt_text = "\n".join(str(m.get("content") or "") for m in messages)
        completion_text = "".join(response_parts)
        est_tokens = token_counter.estimate_tokens(
            prompt_text, model=model
        ) + token_counter.estimate_tokens(completion_text, model=model)
        if est_tokens > 0:
            cost_per_token = _resolve_cost_per_token_usd(config, model=model)
            record_routing_cost(est_tokens * cost_per_token)


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


class BaseLLMClient(ABC):
    """LLM sağlayıcıları için soyut istemci arayüzü."""

    def __init__(self, config) -> None:
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


class OllamaClient(BaseLLMClient):
    """Ollama sağlayıcısı istemcisi."""

    @property
    def base_url(self) -> str:
        return str(_setting(self.config, "OLLAMA_URL", "http://localhost:11434")).removesuffix(
            "/api"
        )

    def _build_timeout(self) -> httpx.Timeout:
        timeout_seconds = max(10, int(_setting(self.config, "OLLAMA_TIMEOUT", 120)))
        return httpx.Timeout(timeout_seconds, connect=10.0)

    def json_mode_config(self) -> dict[str, Any]:
        return {"format": SIDAR_TOOL_JSON_SCHEMA}

    @staticmethod
    def _build_missing_model_guidance(target_model: str, error_text: str) -> str | None:
        normalized = (error_text or "").lower()
        if ("model" in normalized) and ("not found" in normalized or "bulunamad" in normalized):
            return (
                f"Ollama modeli bulunamadı: '{target_model}'. "
                f"Lütfen terminalde `ollama pull {target_model}` komutunu çalıştırın."
            )
        return None

    @staticmethod
    def _error_chunk(message: str) -> str:
        return json.dumps(
            {
                "tool": "final_answer",
                "argument": message,
                "thought": "Hata",
            }
        )

    async def _iter_ollama_json_lines(
        self,
        response: httpx.Response,
        *,
        max_buffer_chars: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        buffer = ""
        utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        async for raw_bytes in response.aiter_bytes():
            decoded = utf8_decoder.decode(raw_bytes, final=False)
            if not decoded:
                continue
            buffer += decoded
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    body = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(body, dict):
                    yield body

            if len(buffer) > max_buffer_chars:
                # Bellek taşmasını önlemek için yalnızca işlenmemiş (incomplete) kuyruğu sınırla.
                buffer = buffer[-max_buffer_chars:]

        trailing = utf8_decoder.decode(b"", final=True)
        if trailing:
            buffer += trailing

        for raw_line in buffer.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                body = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(body, dict):
                yield body

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        target_model = str(model or _setting(self.config, "CODING_MODEL", "qwen2.5-coder:7b"))
        url = f"{self.base_url}/api/chat"

        options: dict[str, Any] = {"temperature": temperature}
        if bool(_setting(self.config, "USE_GPU", False)):
            options["num_gpu"] = -1

        payload = {
            "model": target_model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }
        if json_mode:
            payload.update(self.json_mode_config())

        timeout = self._build_timeout()
        span_scope, stream_span = _prepare_span_scope(self.config, "llm.ollama.chat", stream)
        with span_scope as scoped_span:
            span = scoped_span or stream_span
            started_at = time.monotonic()
            if span is not None:
                span.set_attribute("sidar.llm.provider", "ollama")
                span.set_attribute("sidar.llm.model", target_model)
                span.set_attribute("sidar.llm.stream", stream)
            try:
                if stream:
                    stream_iter = self._stream_response(url, payload, req_timeout=timeout)
                    return _trace_stream_metrics(stream_iter, span, started_at)

                async def _do_request() -> dict[str, Any]:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        resp = await client.post(url, json=payload)

                        if resp.is_error:
                            detail = ""
                            try:
                                detail = str(resp.json().get("error", "")).strip()
                            except Exception:
                                detail = (resp.text or "").strip()

                            if detail:
                                retryable = resp.status_code == 429 or 500 <= resp.status_code < 600
                                raise LLMAPIError(
                                    "ollama",
                                    detail,
                                    status_code=resp.status_code,
                                    retryable=retryable,
                                )

                        resp.raise_for_status()
                        return resp.json()

                data = await _retry_with_backoff(
                    "ollama", _do_request, config=self.config, retry_hint="Ollama isteği başarısız"
                )
                content = data.get("message", {}).get("content", "")
                if span is not None:
                    span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
                return await _ensure_json_text_async(content, "Ollama") if json_mode else content

            except LLMAPIError as exc:
                if stream and span is not None:
                    span.end()
                guidance = None
                if exc.status_code == 404:
                    guidance = self._build_missing_model_guidance(target_model, str(exc))
                if guidance:
                    message = f"{exc} {guidance}"
                    raise LLMAPIError(
                        "ollama",
                        message,
                        status_code=exc.status_code,
                        retryable=exc.retryable,
                    ) from exc
                raise
            except Exception as exc:
                if stream and span is not None:
                    span.end()
                guidance = self._build_missing_model_guidance(target_model, str(exc))
                if guidance:
                    logger.warning("Ollama eksik model: %s", guidance)
                    raise LLMAPIError("ollama", guidance, retryable=False) from exc
                logger.error("Ollama hata: %s", exc)
                raise LLMAPIError("ollama", f"Ollama hata: {exc}", retryable=False) from exc

    async def _stream_response(
        self,
        url: str,
        payload: dict[str, Any],
        req_timeout: httpx.Timeout,
    ) -> AsyncGenerator[str, None]:
        """Ollama stream yanıtını güvenli buffer yaklaşımı ile ayrıştırır."""
        client = None
        stream_cm = None
        resp = None
        try:

            async def _open_stream() -> tuple[httpx.AsyncClient, Any, httpx.Response]:
                stream_client = httpx.AsyncClient(timeout=req_timeout)
                cm = stream_client.stream("POST", url, json=payload)
                response = await cm.__aenter__()
                response.raise_for_status()
                return stream_client, cm, response

            client, stream_cm, resp = await _retry_with_backoff(
                "ollama",
                _open_stream,
                config=self.config,
                retry_hint="Ollama stream başlatma başarısız",
            )
            max_buffer_chars = max(
                1024, int(_setting(self.config, "OLLAMA_STREAM_MAX_BUFFER_CHARS", 1_000_000))
            )
            async for body in self._iter_ollama_json_lines(resp, max_buffer_chars=max_buffer_chars):
                err = str(body.get("error", "") or "")
                if err:
                    guidance = self._build_missing_model_guidance(
                        str(payload.get("model", "") or ""), err
                    )
                    if guidance:
                        yield self._error_chunk(f"\n[HATA] {guidance}")
                        return
                chunk = body.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
        except Exception as exc:
            yield self._error_chunk(f"\n[HATA] Akış kesildi: {exc}")
        finally:
            if stream_cm is not None:
                await stream_cm.__aexit__(*sys.exc_info())
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()

    async def list_models(self) -> list[str]:
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                models = resp.json().get("models", [])
                return [m["name"] for m in models]
        except Exception:
            return []

    async def is_available(self) -> bool:
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get(url)
                return True
        except Exception:
            return False


class GeminiClient(BaseLLMClient):
    """Gemini sağlayıcısı istemcisi."""

    def json_mode_config(self) -> dict[str, Any]:
        return {"generation_config": {"response_mime_type": "application/json"}}

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        genai_client = None
        genai_types = None
        try:
            from google import (
                genai as google_genai,  # type: ignore[import-not-found,import-untyped]
            )
            from google.genai import (
                types as google_genai_types,  # type: ignore[import-not-found,import-untyped]
            )

            genai_client = google_genai.Client(
                api_key=str(_setting(self.config, "GEMINI_API_KEY", ""))
            )
            genai_types = google_genai_types
        except ImportError:
            genai_client = None
            genai_types = None

        if genai_client is None or genai_types is None:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": "[HATA] Gemini istemcisi kurulu değil (google-genai).",
                    "thought": "Paket eksik",
                }
            )
            return _fallback_stream(msg) if stream else msg

        if not str(_setting(self.config, "GEMINI_API_KEY", "")):
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": "[HATA] GEMINI_API_KEY ayarlanmamış.",
                    "thought": "Key eksik",
                }
            )
            return _fallback_stream(msg) if stream else msg

        if json_mode:
            messages = self._inject_json_instruction(messages)

        system_text = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                chat_messages.append(m)

        gen_config = {"temperature": 0.2 if json_mode else temperature}
        if json_mode:
            gen_config.update(self.json_mode_config().get("generation_config", {}))

        history = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]}
            for m in chat_messages
        ]

        model_name = str(model or _setting(self.config, "GEMINI_MODEL", "gemini-2.0-flash"))
        span_scope, stream_span = _prepare_span_scope(self.config, "llm.gemini.chat", stream)
        with span_scope as scoped_span:
            span = scoped_span or stream_span
            started_at = time.monotonic()
            if span is not None:
                span.set_attribute("sidar.llm.provider", "gemini")
                span.set_attribute("sidar.llm.model", model_name)
                span.set_attribute("sidar.llm.stream", stream)
            try:
                config_kwargs = {"temperature": 0.2 if json_mode else temperature}
                if json_mode:
                    config_kwargs["response_mime_type"] = "application/json"
                if system_text:
                    config_kwargs["system_instruction"] = system_text
                generate_config = genai_types.GenerateContentConfig(**config_kwargs)
                contents = history or [{"role": "user", "parts": ["Merhaba"]}]
                if stream:

                    async def _start_stream() -> Any:
                        call = genai_client.aio.models.generate_content_stream(
                            model=model_name,
                            contents=contents,
                            config=generate_config,
                        )
                        return await call if inspect.isawaitable(call) else call

                    response_stream = await _retry_with_backoff(
                        "gemini",
                        _start_stream,
                        config=self.config,
                        retry_hint="Gemini stream başlatma başarısız",
                    )
                    stream_iter = self._stream_gemini_generator(response_stream)
                    return _trace_stream_metrics(stream_iter, span, started_at)

                async def _send_non_stream() -> Any:
                    call = genai_client.aio.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=generate_config,
                    )
                    return await call if inspect.isawaitable(call) else call

                response = await _retry_with_backoff(
                    "gemini",
                    _send_non_stream,
                    config=self.config,
                    retry_hint="Gemini yanıtı alınamadı",
                )

                text = getattr(response, "text", "") or ""
                prompt_tokens, completion_tokens = _extract_gemini_usage_tokens(response)
                _record_llm_metric(
                    provider="gemini",
                    model=model_name,
                    started_at=started_at,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    success=True,
                )
                if span is not None:
                    span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
                return await _ensure_json_text_async(text, "Gemini") if json_mode else text

            except Exception as exc:
                if stream and span is not None:
                    span.end()
                _record_llm_metric(
                    provider="gemini",
                    model=model_name,
                    started_at=started_at,
                    success=False,
                    error=str(exc),
                )
                logger.error("Gemini hata: %s", exc)
                msg = json.dumps(
                    {
                        "tool": "final_answer",
                        "argument": f"[HATA] Gemini: {exc}",
                        "thought": "Hata",
                    },
                    ensure_ascii=False,
                )
                return _fallback_stream(msg) if stream else msg

    async def _stream_gemini_generator(
        self, response_stream: AsyncIterator[Any]
    ) -> AsyncGenerator[str, None]:
        try:
            async for chunk in response_stream:
                text = getattr(chunk, "text", "")
                if text:
                    yield text
        except Exception as exc:
            yield json.dumps(
                {
                    "tool": "final_answer",
                    "argument": f"\n[HATA] Gemini akış hatası: {exc}",
                    "thought": "Hata",
                },
                ensure_ascii=False,
            )


class OpenAIClient(BaseLLMClient):
    """OpenAI Chat Completions istemcisi (opsiyonel sağlayıcı)."""

    def json_mode_config(self) -> dict[str, Any]:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "sidar_tool",
                    "strict": True,
                    "schema": SIDAR_TOOL_JSON_SCHEMA,
                },
            }
        }

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        api_key = getattr(self.config, "OPENAI_API_KEY", "")
        if not api_key:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": "[HATA] OPENAI_API_KEY ayarlanmamış.",
                    "thought": "Key eksik",
                }
            )
            return _fallback_stream(msg) if stream else msg

        model_name = model or getattr(self.config, "OPENAI_MODEL", "gpt-4o-mini")
        if json_mode:
            messages = self._inject_json_instruction(messages)
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload.update(self.json_mode_config())

        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(
            max(10, int(getattr(self.config, "OPENAI_TIMEOUT", 60))), connect=10.0
        )

        span_scope, stream_span = _prepare_span_scope(self.config, "llm.openai.chat", stream)
        with span_scope as scoped_span:
            span = scoped_span or stream_span
            started_at = time.monotonic()
            if span is not None:
                span.set_attribute("sidar.llm.provider", "openai")
                span.set_attribute("sidar.llm.model", model_name)
                span.set_attribute("sidar.llm.stream", stream)
            try:
                if stream:
                    payload["stream"] = True
                    payload["stream_options"] = {"include_usage": True}
                    stream_iter = self._stream_openai(payload, headers, req_timeout=timeout, json_mode=json_mode)
                    return _trace_stream_metrics(
                        _track_stream_completion(
                            stream_iter, provider="openai", model=model_name, started_at=started_at
                        ),
                        span,
                        started_at,
                    )

                async def _do_request() -> dict[str, Any]:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        resp = await client.post(
                            "https://api.openai.com/v1/chat/completions",
                            json=payload,
                            headers=headers,
                        )
                        if resp.is_error:
                            detail = ""
                            try:
                                err = resp.json().get("error", {})
                                detail = str(err.get("message") or "").strip()
                            except Exception:
                                detail = ""
                            if not detail:
                                detail = (resp.text or "").strip()
                            if detail:
                                retryable = resp.status_code == 429 or 500 <= resp.status_code < 600
                                raise LLMAPIError(
                                    "openai",
                                    detail,
                                    status_code=resp.status_code,
                                    retryable=retryable,
                                )
                        resp.raise_for_status()
                        return resp.json()

                data = await _retry_with_backoff(
                    "openai", _do_request, config=self.config, retry_hint="OpenAI isteği başarısız"
                )
                prompt_tokens, completion_tokens = _extract_usage_tokens(data)
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                _record_llm_metric(
                    provider="openai",
                    model=str(model_name or ""),
                    started_at=started_at,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    success=True,
                )
                if span is not None:
                    span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
                return await _ensure_json_text_async(content, "OpenAI") if json_mode else content
            except LLMAPIError as exc:
                if stream and span is not None:
                    span.end()
                _record_llm_metric(
                    provider="openai",
                    model=str(model_name or ""),
                    started_at=started_at,
                    success=False,
                    error=str(exc),
                )
                raise
            except Exception as exc:
                if stream and span is not None:
                    span.end()
                _record_llm_metric(
                    provider="openai",
                    model=str(model_name or ""),
                    started_at=started_at,
                    success=False,
                    error=str(exc),
                )
                logger.error("OpenAI hata: %s", exc)
                raise LLMAPIError("openai", f"OpenAI hata: {exc}", retryable=False) from exc

    async def _stream_openai(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        req_timeout: httpx.Timeout,
        json_mode: bool,
    ) -> AsyncGenerator[str, None]:
        client = None
        stream_cm = None
        resp = None
        try:

            async def _open_stream() -> tuple[httpx.AsyncClient, Any, httpx.Response]:
                stream_client = httpx.AsyncClient(timeout=req_timeout)
                cm = stream_client.stream(
                    "POST",
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response = await cm.__aenter__()
                response.raise_for_status()
                return stream_client, cm, response

            client, stream_cm, resp = await _retry_with_backoff(
                "openai",
                _open_stream,
                config=self.config,
                retry_hint="OpenAI stream başlatma başarısız",
            )
            async for body in self._iter_openai_compatible_stream_lines(resp):
                delta = body.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content", "")
                if text:
                    yield text
        except Exception as exc:
            if json_mode:
                msg = json.dumps(
                    {
                        "tool": "final_answer",
                        "argument": f"\n[HATA] OpenAI akış hatası: {exc}",
                        "thought": "Hata",
                    },
                    ensure_ascii=False,
                )
                yield await _ensure_json_text_async(msg, "OpenAI")
            else:
                yield f"\n[SİSTEM HATASI]: Akış kesildi ({exc})"

        finally:
            if stream_cm is not None:
                await stream_cm.__aexit__(*sys.exc_info())
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()


class LiteLLMClient(BaseLLMClient):
    """LiteLLM Gateway istemcisi (OpenAI uyumlu Chat Completions)."""

    def json_mode_config(self) -> dict[str, Any]:
        return {"response_format": {"type": "json_object"}}

    def _candidate_models(self, requested_model: str | None) -> list[str]:
        primary = (
            requested_model
            or str(_setting(self.config, "LITELLM_MODEL", ""))
            or str(_setting(self.config, "OPENAI_MODEL", "gpt-4o-mini"))
        ).strip()
        raw_fallbacks = getattr(self.config, "LITELLM_FALLBACK_MODELS", [])
        if not isinstance(raw_fallbacks, list):
            raw_fallbacks = []
        fallbacks = [str(m).strip() for m in raw_fallbacks if str(m).strip()]
        ordered = [primary] + fallbacks
        dedup: list[str] = []
        for m in ordered:
            if m and m not in dedup:
                dedup.append(m)
        return dedup

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        base_url = str(_setting(self.config, "LITELLM_GATEWAY_URL", "")).strip().rstrip("/")
        api_key = str(_setting(self.config, "LITELLM_API_KEY", "")).strip()
        if not base_url:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": "[HATA] LITELLM_GATEWAY_URL ayarlanmamış.",
                    "thought": "Gateway URL eksik",
                },
                ensure_ascii=False,
            )
            return _fallback_stream(msg) if stream else msg

        if json_mode:
            messages = self._inject_json_instruction(messages)

        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = httpx.Timeout(
            max(10, int(getattr(self.config, "LITELLM_TIMEOUT", 60))), connect=10.0
        )
        models = self._candidate_models(model)
        started_at = time.monotonic()
        last_error: Exception | None = None
        span_scope, stream_span = _prepare_span_scope(self.config, "llm.litellm.chat", stream)
        with span_scope as scoped_span:
            span = scoped_span or stream_span
            if span is not None:
                span.set_attribute("sidar.llm.provider", "litellm")
                span.set_attribute("sidar.llm.stream", stream)

            try:
                for idx, model_name in enumerate(models):
                    payload: dict[str, Any] = {
                        "model": model_name,
                        "messages": messages,
                        "temperature": temperature,
                    }
                    if json_mode:
                        payload.update(self.json_mode_config())

                    endpoint = f"{base_url}/chat/completions"
                    try:
                        if stream:
                            payload["stream"] = True
                            payload["stream_options"] = {"include_usage": True}
                            stream_iter = self._stream_openai_compatible(
                                endpoint, payload, headers, req_timeout=timeout, json_mode=json_mode
                            )
                            return _track_stream_completion(
                                stream_iter,
                                provider="litellm",
                                model=model_name,
                                started_at=started_at,
                            )

                        async def _do_request(
                            *,
                            endpoint: str = endpoint,
                            payload: dict[str, Any] = payload,
                        ) -> dict[str, Any]:
                            async with httpx.AsyncClient(timeout=timeout) as client:
                                resp = await client.post(endpoint, json=payload, headers=headers)
                                resp.raise_for_status()
                                return resp.json()

                        data = await _retry_with_backoff(
                            "litellm",
                            _do_request,
                            config=self.config,
                            retry_hint="LiteLLM isteği başarısız",
                        )
                        prompt_tokens, completion_tokens = _extract_usage_tokens(data)
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        _record_llm_metric(
                            provider="litellm",
                            model=model_name,
                            started_at=started_at,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            success=True,
                        )
                        if span is not None:
                            span.set_attribute("sidar.llm.model", model_name)
                            span.set_attribute(
                                "sidar.llm.total_ms", (time.monotonic() - started_at) * 1000
                            )
                        return (
                            await _ensure_json_text_async(content, "LiteLLM")
                            if json_mode
                            else content
                        )
                    except Exception as exc:
                        last_error = exc
                        logger.warning("LiteLLM modeli başarısız oldu (%s): %s", model_name, exc)
                        if idx == len(models) - 1:
                            break

                _record_llm_metric(
                    provider="litellm",
                    model=models[0] if models else "unknown",
                    started_at=started_at,
                    success=False,
                    error=str(last_error or "unknown"),
                )
                raise LLMAPIError("litellm", f"LiteLLM hata: {last_error}", retryable=False)
            except Exception:
                if stream and span is not None:
                    span.end()
                raise

    async def _stream_openai_compatible(
        self,
        endpoint: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        req_timeout: httpx.Timeout,
        json_mode: bool,
    ) -> AsyncGenerator[str, None]:
        client = None
        stream_cm = None
        try:

            async def _open_stream() -> tuple[httpx.AsyncClient, Any, httpx.Response]:
                stream_client = httpx.AsyncClient(timeout=req_timeout)
                cm = stream_client.stream("POST", endpoint, json=payload, headers=headers)
                response = await cm.__aenter__()
                response.raise_for_status()
                return stream_client, cm, response

            client, stream_cm, resp = await _retry_with_backoff(
                "litellm",
                _open_stream,
                config=self.config,
                retry_hint="LiteLLM stream başlatma başarısız",
            )
            async for body in self._iter_openai_compatible_stream_lines(resp):
                delta = body.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content", "")
                if text:
                    yield text
        except Exception as exc:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": f"\n[HATA] LiteLLM akış hatası: {exc}",
                    "thought": "Hata",
                },
                ensure_ascii=False,
            )
            yield await _ensure_json_text_async(msg, "LiteLLM") if json_mode else msg
        finally:
            if stream_cm is not None:
                await stream_cm.__aexit__(*sys.exc_info())
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude sağlayıcısı istemcisi."""

    def json_mode_config(self) -> dict[str, Any]:
        # Anthropic için yerel JSON modu bulunmaz; şema talimatı system prompt'a enjekte edilir
        return {}

    @staticmethod
    def _split_system_and_messages(
        messages: list[dict[str, str]],
    ) -> tuple[str, list[dict[str, str]]]:
        system_parts: list[str] = []
        conversation: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                if content:
                    system_parts.append(content)
                continue
            conversation.append({"role": role, "content": content})
        return "\n\n".join(system_parts).strip(), conversation

    def _build_timeout(self) -> int:
        return max(10, int(_setting(self.config, "ANTHROPIC_TIMEOUT", 60)))

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        api_key = str(_setting(self.config, "ANTHROPIC_API_KEY", ""))
        if not api_key:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": "[HATA] ANTHROPIC_API_KEY ayarlanmamış.",
                    "thought": "Anthropic anahtarı eksik.",
                }
            )
            return _fallback_stream(msg) if stream else msg

        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": f"[HATA] anthropic paketi kullanılamıyor: {exc}",
                    "thought": "Anthropic istemcisi başlatılamadı.",
                }
            )
            return _fallback_stream(msg) if stream else msg

        model_name = str(
            model or _setting(self.config, "ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        )
        if json_mode:
            messages = self._inject_json_instruction(messages)
        system_prompt, conversation = self._split_system_and_messages(messages)
        if not conversation:
            conversation = [{"role": "user", "content": "Merhaba"}]

        client = AsyncAnthropic(api_key=api_key, timeout=self._build_timeout())
        span_scope, stream_span = _prepare_span_scope(self.config, "llm.anthropic.chat", stream)
        with span_scope as scoped_span:
            span = scoped_span or stream_span
            started_at = time.monotonic()
            if span is not None:
                span.set_attribute("sidar.llm.provider", "anthropic")
                span.set_attribute("sidar.llm.model", model_name)
                span.set_attribute("sidar.llm.stream", stream)

            try:
                if stream:
                    stream_iter = self._stream_anthropic(
                        client=client,
                        model_name=model_name,
                        messages=conversation,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        json_mode=json_mode,
                    )
                    stream_iter: AsyncIterator[str] = _track_stream_completion(
                        stream_iter,
                        provider="anthropic",
                        model=model_name,
                        started_at=started_at,
                    )
                    return _trace_stream_metrics(stream_iter, span, started_at)

                async def _do_request() -> Any:
                    request_kwargs: dict[str, Any] = {
                        "model": model_name,
                        "max_tokens": 4096,
                        "temperature": temperature,
                        "messages": conversation,
                    }
                    if (system_prompt or "").strip():
                        request_kwargs["system"] = system_prompt
                    return await client.messages.create(**request_kwargs)

                response = await _retry_with_backoff(
                    "anthropic",
                    _do_request,
                    config=self.config,
                    retry_hint="Anthropic isteği başarısız",
                )
                usage = getattr(response, "usage", None)
                prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                text = "".join(
                    getattr(block, "text", "") for block in getattr(response, "content", [])
                )
                _record_llm_metric(
                    provider="anthropic",
                    model=model_name,
                    started_at=started_at,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    success=True,
                )
                if span is not None:
                    span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
                return await _ensure_json_text_async(text, "Anthropic") if json_mode else text
            except LLMAPIError as exc:
                if stream and span is not None:
                    span.end()
                _record_llm_metric(
                    provider="anthropic",
                    model=model_name,
                    started_at=started_at,
                    success=False,
                    error=str(exc),
                )
                raise
            except Exception as exc:
                if stream and span is not None:
                    span.end()
                _record_llm_metric(
                    provider="anthropic",
                    model=model_name,
                    started_at=started_at,
                    success=False,
                    error=str(exc),
                )
                logger.error("Anthropic hata: %s", exc)
                raise LLMAPIError("anthropic", f"Anthropic hata: {exc}", retryable=False) from exc

    async def _stream_anthropic(
        self,
        client: Any,
        model_name: str,
        messages: list[dict[str, str]],
        system_prompt: str,
        temperature: float,
        json_mode: bool,
    ) -> AsyncGenerator[str, None]:
        stream_cm = None
        stream = None
        try:

            async def _open_stream() -> tuple[Any, Any]:
                stream_kwargs: dict[str, Any] = {
                    "model": model_name,
                    "max_tokens": 4096,
                    "temperature": temperature,
                    "messages": messages,
                }
                if (system_prompt or "").strip():
                    stream_kwargs["system"] = system_prompt
                cm = client.messages.stream(**stream_kwargs)
                opened = await cm.__aenter__()
                return cm, opened

            stream_cm, stream = await _retry_with_backoff(
                "anthropic",
                _open_stream,
                config=self.config,
                retry_hint="Anthropic stream başlatma başarısız",
            )
            async for event in stream:
                if getattr(event, "type", "") != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                if getattr(delta, "type", "") != "text_delta":
                    continue
                text = getattr(delta, "text", "")
                if text:
                    yield text
        except Exception as exc:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": f"[HATA] Anthropic akış hatası: {exc}",
                    "thought": "Hata",
                },
                ensure_ascii=False,
            )
            yield await _ensure_json_text_async(msg, "Anthropic") if json_mode else msg
        finally:
            if stream_cm is not None:
                await stream_cm.__aexit__(*sys.exc_info())


class LLMClient:
    """Factory sınıfı: sağlayıcıya göre doğru istemciyi seçer."""

    PROVIDER_REGISTRY: dict[str, type[BaseLLMClient]] = {
        "ollama": OllamaClient,
        "gemini": GeminiClient,
        "openai": OpenAIClient,
        "anthropic": AnthropicClient,
        "litellm": LiteLLMClient,
    }

    def __init__(self, provider: str, config: Any) -> None:
        self.provider = provider.lower()
        self.config = config
        self._semantic_cache = SemanticCacheManager(config)
        self._router = CostAwareRouter(config)
        client_cls = self.PROVIDER_REGISTRY.get(self.provider)
        if client_cls is None:
            raise ValueError(f"Bilinmeyen AI sağlayıcısı: {self.provider}")
        self._client = client_cls(config)

    @property
    def _ollama_base_url(self) -> str:
        """Geriye dönük uyumluluk: Ollama taban URL bilgisi."""
        if isinstance(self._client, OllamaClient):
            return self._client.base_url
        return str(_setting(self.config, "OLLAMA_URL", "http://localhost:11434")).removesuffix(
            "/api"
        )

    def _build_ollama_timeout(self) -> httpx.Timeout:
        """Geriye dönük uyumluluk: eski timeout yardımcı adı."""
        if isinstance(self._client, OllamaClient):
            return self._client._build_timeout()
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
        messages = _dlp_mask_messages(messages)

        user_prompt = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                user_prompt = (message.get("content") or "").strip()
                break

        if (not stream) and user_prompt:
            cached_response = await self._semantic_cache.get(user_prompt)
            if cached_response is not None:
                return cached_response
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
            return _track_stream_routing_cost(  # type: ignore[arg-type]
                response,
                messages=messages,
                config=self.config,
                model=str(model or ""),
            )

        # Bulgu Y-6: Günlük bütçe izleyicisine maliyet kaydı — yalnızca bulut sağlayıcıları için
        if (not stream) and isinstance(response, str) and self.provider != "ollama":
            _msg_text = "\n".join(m.get("content") or "" for m in messages)
            _est_tokens = token_counter.estimate_tokens(
                _msg_text, model=str(model or "")
            ) + token_counter.estimate_tokens(response, model=str(model or ""))
            _cost_per_token = _resolve_cost_per_token_usd(self.config, model=str(model or ""))
            record_routing_cost(_est_tokens * _cost_per_token)

        if (not stream) and user_prompt and isinstance(response, str):
            await self._semantic_cache.set(user_prompt, response)

        return response

    async def list_ollama_models(self) -> list[str]:
        if isinstance(self._client, OllamaClient):
            return await self._client.list_models()
        return []

    async def is_ollama_available(self) -> bool:
        if isinstance(self._client, OllamaClient):
            return await self._client.is_available()
        return False

    async def _stream_gemini_generator(
        self, response_stream: AsyncIterator[Any]
    ) -> AsyncGenerator[str, None]:
        """Test/geri uyumluluk için Gemini stream dönüştürücüsünü dışa aç."""
        if isinstance(self._client, GeminiClient):
            async for chunk in self._client._stream_gemini_generator(response_stream):
                yield chunk
            return

        async for chunk in GeminiClient(self.config)._stream_gemini_generator(response_stream):
            yield chunk
