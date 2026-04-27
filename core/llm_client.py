"""
Sidar Project - LLM İstemcisi
Ollama, Google Gemini, OpenAI ve Anthropic API entegrasyonu (Asenkron, OOP tabanlı).
"""

from __future__ import annotations

import codecs
import inspect
import hashlib
import asyncio
import json
import math
import sys
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional, Union

import httpx
try:
    from redis.asyncio import Redis
except ImportError:
    Redis = None  # type: ignore[assignment]
from core.llm_metrics import get_current_metrics_user_id, get_llm_metrics_collector
from core.dlp import mask_messages as _dlp_mask_messages
from core.router import CostAwareRouter, record_routing_cost
from core.cache_metrics import (
    observe_cache_redis_latency,
    record_cache_eviction,
    record_cache_hit,
    record_cache_miss,
    record_cache_redis_error,
    record_cache_skip,
    set_cache_items,
)

from opentelemetry import trace

logger = logging.getLogger(__name__)


SIDAR_TOOL_JSON_SCHEMA: Dict[str, Any] = {
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


def _setting(config: Any, key: str, default: Any) -> Any:
    return getattr(config, key, default)


def build_provider_json_mode_config(provider: str) -> Dict[str, Any]:
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

    def __init__(self, provider: str, message: str, *, status_code: Optional[int] = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


def _is_retryable_exception(exc: Exception) -> tuple[bool, Optional[int]]:
    status_code = getattr(exc, "status_code", None)
    http_status_error = getattr(httpx, "HTTPStatusError", None)
    if http_status_error and isinstance(exc, http_status_error):
        status_code = exc.response.status_code
    if status_code == 429 or (status_code is not None and 500 <= int(status_code) < 600):
        return True, int(status_code)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, asyncio.TimeoutError)):
        return True, status_code
    return False, status_code


async def _retry_with_backoff(provider: str, operation, *, config, retry_hint: str) -> Any:
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
                raise LLMAPIError(provider, message, status_code=status_code, retryable=retryable) from exc

            jitter_cap = min(0.5, base_delay)
            delay = min(max_delay, base_delay * (2 ** attempt)) + random.uniform(0, jitter_cap)
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
    try:
        json.loads(text)
        return text
    except Exception:
        logger.warning("%s: JSON dışı yanıt alındı, fallback uygulanıyor.", provider)
        return json.dumps(
            {
                "thought": f"{provider} sağlayıcısı JSON dışı içerik döndürdü.",
                "tool": "final_answer",
                "argument": text or "[UYARI] Sağlayıcı boş içerik döndürdü.",
            }
        )


async def _fallback_stream(msg: str) -> AsyncGenerator[str, None]:
    """Hata durumlarında tek elemanlı asenkron akış döndürür."""
    yield msg


def _get_tracer(config):
    if getattr(config, "ENABLE_TRACING", False):
        return trace.get_tracer(__name__)
    return None


def _extract_usage_tokens(data: dict) -> tuple[int, int]:
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
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
    try:
        async for chunk in stream_iter:
            yield chunk
        _record_llm_metric(provider=provider, model=model, started_at=started_at, success=True)
    except Exception as exc:
        _record_llm_metric(provider=provider, model=model, started_at=started_at, success=False, error=str(exc))
        raise


async def _trace_stream_metrics(stream_iter: AsyncIterator[str], span, started_at: float):
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




class _SemanticCacheManager:
    """Redis tabanlı semantik LLM yanıt önbelleği."""

    def __init__(self, config) -> None:
        self.config = config
        self.enabled = bool(getattr(config, "ENABLE_SEMANTIC_CACHE", False))
        self.threshold = max(0.0, float(_setting(config, "SEMANTIC_CACHE_THRESHOLD", 0.90)))
        self.ttl = max(1, int(_setting(config, "SEMANTIC_CACHE_TTL", 3600)))
        self.max_items = max(1, int(_setting(config, "SEMANTIC_CACHE_MAX_ITEMS", 500)))
        self.redis_cb_fail_threshold = max(1, int(_setting(config, "SEMANTIC_CACHE_REDIS_CB_FAIL_THRESHOLD", 3)))
        self.redis_cb_cooldown_seconds = max(1, int(_setting(config, "SEMANTIC_CACHE_REDIS_CB_COOLDOWN_SECONDS", 30)))
        self.index_key = "sidar:semantic_cache:index"
        self._redis: Redis | None = None
        self._redis_failures = 0
        self._redis_circuit_open_until = 0.0

    def _redis_circuit_open(self) -> bool:
        if self._redis_circuit_open_until <= 0.0:
            return False
        if time.monotonic() >= self._redis_circuit_open_until:
            self._redis_circuit_open_until = 0.0
            self._redis_failures = 0
            return False
        return True

    def _mark_redis_failure(self) -> None:
        self._redis_failures += 1
        if self._redis_failures >= self.redis_cb_fail_threshold:
            self._redis_circuit_open_until = time.monotonic() + float(self.redis_cb_cooldown_seconds)
            logger.warning(
                "Semantic cache circuit breaker açıldı (failures=%d, cooldown=%ss).",
                self._redis_failures,
                self.redis_cb_cooldown_seconds,
            )

    def _mark_redis_success(self) -> None:
        self._redis_failures = 0
        self._redis_circuit_open_until = 0.0

    async def _get_redis(self) -> Redis | None:
        if not self.enabled or Redis is None:
            return None
        if self._redis_circuit_open():
            record_cache_skip()
            return None
        if self._redis is not None:
            return self._redis
        started = time.perf_counter()
        try:
            self._redis = Redis.from_url(
                getattr(self.config, "REDIS_URL", "redis://localhost:6379/0"),
                encoding="utf-8",
                decode_responses=True,
                max_connections=max(1, int(_setting(self.config, "REDIS_MAX_CONNECTIONS", 50))),
            )
            await self._redis.ping()
            self._mark_redis_success()
            observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
            return self._redis
        except Exception as exc:
            logger.debug("Semantic cache Redis bağlantısı kurulamadı: %s", exc)
            record_cache_redis_error()
            self._mark_redis_failure()
            self._redis = None
            return None

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        an = math.sqrt(sum(x * x for x in a))
        bn = math.sqrt(sum(y * y for y in b))
        if an == 0 or bn == 0:
            return 0.0
        return dot / (an * bn)

    def _embed_prompt(self, prompt: str) -> List[float]:
        try:
            from core.rag import embed_texts_for_semantic_cache

            vectors = embed_texts_for_semantic_cache([prompt], cfg=self.config)
            if vectors:
                return [float(v) for v in vectors[0]]
        except Exception as exc:
            logger.debug("Semantic cache embedding hatası: %s", exc)
        return []

    async def get(self, prompt: str) -> Optional[str]:
        redis = await self._get_redis()
        if redis is None or not prompt:
            return None

        query_vector = self._embed_prompt(prompt)
        if not query_vector:
            return None

        started = time.perf_counter()
        try:
            keys = await redis.lrange(self.index_key, 0, -1)
            if not keys:
                set_cache_items(0)
                observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
                return None
            set_cache_items(len(keys))

            best_sim = -1.0
            best_response: Optional[str] = None
            for key in keys:
                raw = await redis.hgetall(key)
                if not raw:
                    continue
                try:
                    emb = json.loads(raw.get("embedding", "[]"))
                except Exception:
                    continue
                sim = self._cosine_similarity(query_vector, emb)
                if sim > best_sim:
                    best_sim = sim
                    best_response = raw.get("response")

            if best_response is not None and best_sim >= self.threshold:
                logger.info("Semantic cache HIT (similarity=%.4f)", best_sim)
                record_cache_hit()
                self._mark_redis_success()
                observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
                return best_response
            logger.debug("Semantic cache MISS (best_similarity=%.4f)", max(best_sim, 0.0))
            record_cache_miss()
            self._mark_redis_success()
            observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
            return None
        except Exception as exc:
            logger.debug("Semantic cache okuma hatası: %s", exc)
            record_cache_redis_error()
            self._mark_redis_failure()
            self._redis = None
            return None

    async def set(self, prompt: str, response: str) -> None:
        redis = await self._get_redis()
        if redis is None or not prompt or not response:
            return

        vector = self._embed_prompt(prompt)
        if not vector:
            return

        item_key = f"sidar:semantic_cache:item:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}"
        payload = {
            "prompt": prompt,
            "response": response,
            "embedding": json.dumps(vector),
            "created_at": str(time.time()),
        }
        started = time.perf_counter()
        try:
            keys_before = await redis.lrange(self.index_key, 0, self.max_items - 1)
            had_existing = item_key in keys_before
            async with redis.pipeline(transaction=True) as pipe:
                pipe.hset(item_key, mapping=payload)
                pipe.expire(item_key, self.ttl)
                pipe.lrem(self.index_key, 0, item_key)
                pipe.lpush(self.index_key, item_key)
                pipe.ltrim(self.index_key, 0, self.max_items - 1)
                await pipe.execute()
            current_items = await redis.llen(self.index_key)
            set_cache_items(current_items)
            if not had_existing and len(keys_before) >= self.max_items:
                record_cache_eviction()
            self._mark_redis_success()
            observe_cache_redis_latency((time.perf_counter() - started) * 1000.0)
        except Exception as exc:
            logger.debug("Semantic cache yazma hatası: %s", exc)
            record_cache_redis_error()
            self._mark_redis_failure()
            self._redis = None


class BaseLLMClient(ABC):
    """LLM sağlayıcıları için soyut istemci arayüzü."""

    def __init__(self, config) -> None:
        self.config = config

    @abstractmethod
    def json_mode_config(self) -> Dict[str, Any]:
        """json_mode=True çağrısında payload'a eklenecek sağlayıcıya özel ayarları döndürür."""

    @staticmethod
    def _inject_json_instruction(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Mesaj listesindeki system mesajına JSON şema talimatını ekler (system yoksa başa ekler)."""
        result = list(messages)
        for i, msg in enumerate(result):
            if msg.get("role") == "system":
                existing = (msg.get("content") or "").strip()
                result[i] = {**msg, "content": f"{existing}\n\n{SIDAR_TOOL_JSON_INSTRUCTION}".strip()}
                return result
        return [{"role": "system", "content": SIDAR_TOOL_JSON_INSTRUCTION}] + result

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        """Sağlayıcıya özel chat çağrısı."""


class OllamaClient(BaseLLMClient):
    """Ollama sağlayıcısı istemcisi."""

    @property
    def base_url(self) -> str:
        return str(_setting(self.config, "OLLAMA_URL", "http://localhost:11434")).removesuffix("/api")

    def _build_timeout(self) -> httpx.Timeout:
        timeout_seconds = max(10, int(_setting(self.config, "OLLAMA_TIMEOUT", 120)))
        return httpx.Timeout(timeout_seconds, connect=10.0)

    def json_mode_config(self) -> Dict[str, Any]:
        return {"format": SIDAR_TOOL_JSON_SCHEMA}

    @staticmethod
    def _build_missing_model_guidance(target_model: str, error_text: str) -> Optional[str]:
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
    ) -> AsyncGenerator[Dict[str, Any], None]:
        buffer = ""
        utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        async for raw_bytes in response.aiter_bytes():
            decoded = utf8_decoder.decode(raw_bytes, final=False)
            if not decoded:
                continue
            buffer += decoded
            if len(buffer) > max_buffer_chars:
                # Bellek taşmasını önlemek için güvenli pencereleme.
                buffer = buffer[-max_buffer_chars:]
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
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        target_model = str(model or _setting(self.config, "CODING_MODEL", "qwen2.5-coder:7b"))
        url = f"{self.base_url}/api/chat"

        options: dict = {"temperature": temperature}
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
        tracer = _get_tracer(self.config)
        span_cm = tracer.start_as_current_span("llm.ollama.chat") if (tracer and not stream) else None
        span = span_cm.__enter__() if span_cm else (tracer.start_span("llm.ollama.chat") if tracer and stream else None)
        started_at = time.monotonic()
        if span is not None:
            span.set_attribute("sidar.llm.provider", "ollama")
            span.set_attribute("sidar.llm.model", target_model)
            span.set_attribute("sidar.llm.stream", stream)
        try:
            if stream:
                stream_iter = self._stream_response(url, payload, timeout=timeout)
                return _trace_stream_metrics(stream_iter, span, started_at)

            async def _do_request():
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

            data = await _retry_with_backoff("ollama", _do_request, config=self.config, retry_hint="Ollama isteği başarısız")
            content = data.get("message", {}).get("content", "")
            if span is not None:
                span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
            return _ensure_json_text(content, "Ollama") if json_mode else content

        except LLMAPIError as exc:
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
            guidance = self._build_missing_model_guidance(target_model, str(exc))
            if guidance:
                logger.warning("Ollama eksik model: %s", guidance)
                raise LLMAPIError("ollama", guidance, retryable=False) from exc
            logger.error("Ollama hata: %s", exc)
            raise LLMAPIError("ollama", f"Ollama hata: {exc}", retryable=False) from exc
        finally:
            if span_cm:
                span_cm.__exit__(*sys.exc_info())

    async def _stream_response(
        self,
        url: str,
        payload: dict,
        timeout: httpx.Timeout,
    ) -> AsyncGenerator[str, None]:
        """Ollama stream yanıtını güvenli buffer yaklaşımı ile ayrıştırır."""
        client = None
        stream_cm = None
        resp = None
        try:
            async def _open_stream():
                stream_client = httpx.AsyncClient(timeout=timeout)
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
            max_buffer_chars = max(1024, int(_setting(self.config, "OLLAMA_STREAM_MAX_BUFFER_CHARS", 1_000_000)))
            async for body in self._iter_ollama_json_lines(resp, max_buffer_chars=max_buffer_chars):
                err = str(body.get("error", "") or "")
                if err:
                    guidance = self._build_missing_model_guidance(str(payload.get("model", "") or ""), err)
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

    async def list_models(self) -> List[str]:
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

    def json_mode_config(self) -> Dict[str, Any]:
        return {"generation_config": {"response_mime_type": "application/json"}}

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        genai_client = None
        genai_types = None
        try:
            from google import genai as google_genai  # type: ignore[import-not-found]
            from google.genai import types as google_genai_types  # type: ignore[import-not-found]
            genai_client = google_genai.Client(api_key=str(_setting(self.config, "GEMINI_API_KEY", "")))
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

        history = [{"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]} for m in chat_messages]

        tracer = _get_tracer(self.config)
        span_cm = tracer.start_as_current_span("llm.gemini.chat") if (tracer and not stream) else None
        span = span_cm.__enter__() if span_cm else (tracer.start_span("llm.gemini.chat") if tracer and stream else None)
        started_at = time.monotonic()
        if span is not None:
            span.set_attribute("sidar.llm.provider", "gemini")
            span.set_attribute("sidar.llm.model", model or str(_setting(self.config, "GEMINI_MODEL", "gemini-2.0-flash")))
            span.set_attribute("sidar.llm.stream", stream)

        try:
            config_kwargs = {"temperature": 0.2 if json_mode else temperature}
            if json_mode:
                config_kwargs["response_mime_type"] = "application/json"
            if system_text:
                config_kwargs["system_instruction"] = system_text
            generate_config = genai_types.GenerateContentConfig(**config_kwargs)
            model_name = str(model or _setting(self.config, "GEMINI_MODEL", "gemini-2.0-flash"))
            contents = history or [{"role": "user", "parts": ["Merhaba"]}]
            if stream:
                async def _start_stream():
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

            async def _send_non_stream():
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
            if span is not None:
                span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
            return _ensure_json_text(text, "Gemini") if json_mode else text

        except Exception as exc:
            logger.error("Gemini hata: %s", exc)
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": f"[HATA] Gemini: {exc}",
                    "thought": "Hata",
                }
            )
            return _fallback_stream(msg) if stream else msg
        finally:
            if span_cm:
                span_cm.__exit__(*sys.exc_info())

    async def _stream_gemini_generator(self, response_stream) -> AsyncGenerator[str, None]:
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
                }
            )


class OpenAIClient(BaseLLMClient):
    """OpenAI Chat Completions istemcisi (opsiyonel sağlayıcı)."""

    def json_mode_config(self) -> Dict[str, Any]:
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
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
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
        timeout = httpx.Timeout(max(10, int(getattr(self.config, "OPENAI_TIMEOUT", 60))), connect=10.0)

        started_at = time.monotonic()
        tracer = _get_tracer(self.config)
        span_cm = tracer.start_as_current_span("llm.openai.chat") if (tracer and not stream) else None
        span = span_cm.__enter__() if span_cm else (tracer.start_span("llm.openai.chat") if tracer and stream else None)
        if span is not None:
            span.set_attribute("sidar.llm.provider", "openai")
            span.set_attribute("sidar.llm.model", model_name)
            span.set_attribute("sidar.llm.stream", stream)
        try:
            if stream:
                payload["stream"] = True
                stream_iter = self._stream_openai(payload, headers, timeout, json_mode)
                return _trace_stream_metrics(_track_stream_completion(stream_iter, provider="openai", model=model_name, started_at=started_at), span, started_at)

            async def _do_request():
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

            data = await _retry_with_backoff("openai", _do_request, config=self.config, retry_hint="OpenAI isteği başarısız")
            prompt_tokens, completion_tokens = _extract_usage_tokens(data)
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            _record_llm_metric(
                provider="openai",
                model=model_name,
                started_at=started_at,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=True,
            )
            if span is not None:
                span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
            result = _ensure_json_text(content, "OpenAI") if json_mode else content
            if span_cm:
                span_cm.__exit__(None, None, None)
            return result
        except LLMAPIError as exc:
            _record_llm_metric(provider="openai", model=model_name, started_at=started_at, success=False, error=str(exc))
            if span_cm:
                span_cm.__exit__(*sys.exc_info())
            raise
        except Exception as exc:
            _record_llm_metric(provider="openai", model=model_name, started_at=started_at, success=False, error=str(exc))
            logger.error("OpenAI hata: %s", exc)
            if span_cm:
                span_cm.__exit__(*sys.exc_info())
            raise LLMAPIError("openai", f"OpenAI hata: {exc}", retryable=False) from exc

    async def _stream_openai(
        self,
        payload: dict,
        headers: dict,
        timeout: httpx.Timeout,
        json_mode: bool,
    ) -> AsyncGenerator[str, None]:
        client = None
        stream_cm = None
        resp = None
        try:
            async def _open_stream():
                stream_client = httpx.AsyncClient(timeout=timeout)
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
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    body = json.loads(data)
                    delta = body.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text
                except json.JSONDecodeError:
                    continue
        except Exception as exc:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": f"\n[HATA] OpenAI akış hatası: {exc}",
                    "thought": "Hata",
                }
            )
            yield _ensure_json_text(msg, "OpenAI") if json_mode else msg

        finally:
            if stream_cm is not None:
                await stream_cm.__aexit__(*sys.exc_info())
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()


class LiteLLMClient(BaseLLMClient):
    """LiteLLM Gateway istemcisi (OpenAI uyumlu Chat Completions)."""

    def json_mode_config(self) -> Dict[str, Any]:
        return {"response_format": {"type": "json_object"}}

    def _candidate_models(self, requested_model: Optional[str]) -> List[str]:
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
        dedup: List[str] = []
        for m in ordered:
            if m and m not in dedup:
                dedup.append(m)
        return dedup

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        base_url = str(_setting(self.config, "LITELLM_GATEWAY_URL", "")).strip().rstrip("/")
        api_key = str(_setting(self.config, "LITELLM_API_KEY", "")).strip()
        if not base_url:
            msg = json.dumps({
                "tool": "final_answer",
                "argument": "[HATA] LITELLM_GATEWAY_URL ayarlanmamış.",
                "thought": "Gateway URL eksik",
            })
            return _fallback_stream(msg) if stream else msg

        if json_mode:
            messages = self._inject_json_instruction(messages)

        headers: Dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = httpx.Timeout(max(10, int(getattr(self.config, "LITELLM_TIMEOUT", 60))), connect=10.0)
        models = self._candidate_models(model)
        started_at = time.monotonic()
        last_error: Optional[Exception] = None
        tracer = _get_tracer(self.config)
        span_cm = tracer.start_as_current_span("llm.litellm.chat") if (tracer and not stream) else None
        span = span_cm.__enter__() if span_cm else (tracer.start_span("llm.litellm.chat") if tracer and stream else None)
        if span is not None:
            span.set_attribute("sidar.llm.provider", "litellm")
            span.set_attribute("sidar.llm.stream", stream)

        for idx, model_name in enumerate(models):
            payload: Dict[str, Any] = {
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
                    stream_iter = self._stream_openai_compatible(endpoint, payload, headers, timeout, json_mode)
                    return _track_stream_completion(stream_iter, provider="litellm", model=model_name, started_at=started_at)

                async def _do_request():
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        resp = await client.post(endpoint, json=payload, headers=headers)
                        resp.raise_for_status()
                        return resp.json()

                data = await _retry_with_backoff("litellm", _do_request, config=self.config, retry_hint="LiteLLM isteği başarısız")
                prompt_tokens, completion_tokens = _extract_usage_tokens(data)
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                _record_llm_metric(provider="litellm", model=model_name, started_at=started_at, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, success=True)
                if span is not None:
                    span.set_attribute("sidar.llm.model", model_name)
                    span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
                result = _ensure_json_text(content, "LiteLLM") if json_mode else content
                if span_cm:
                    span_cm.__exit__(None, None, None)
                return result
            except Exception as exc:
                last_error = exc
                logger.warning("LiteLLM modeli başarısız oldu (%s): %s", model_name, exc)
                if idx == len(models) - 1:
                    break

        _record_llm_metric(provider="litellm", model=models[0] if models else "unknown", started_at=started_at, success=False, error=str(last_error or "unknown"))
        if span_cm:
            span_cm.__exit__(None, None, None)
        raise LLMAPIError("litellm", f"LiteLLM hata: {last_error}", retryable=False)

    async def _stream_openai_compatible(
        self,
        endpoint: str,
        payload: dict,
        headers: dict,
        timeout: httpx.Timeout,
        json_mode: bool,
    ) -> AsyncGenerator[str, None]:
        client = None
        stream_cm = None
        try:
            async def _open_stream():
                stream_client = httpx.AsyncClient(timeout=timeout)
                cm = stream_client.stream("POST", endpoint, json=payload, headers=headers)
                response = await cm.__aenter__()
                response.raise_for_status()
                return stream_client, cm, response

            client, stream_cm, resp = await _retry_with_backoff("litellm", _open_stream, config=self.config, retry_hint="LiteLLM stream başlatma başarısız")
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    body = json.loads(data)
                    delta = body.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text
                except json.JSONDecodeError:
                    continue
        except Exception as exc:
            msg = json.dumps({"tool": "final_answer", "argument": f"\n[HATA] LiteLLM akış hatası: {exc}", "thought": "Hata"})
            yield _ensure_json_text(msg, "LiteLLM") if json_mode else msg
        finally:
            if stream_cm is not None:
                await stream_cm.__aexit__(*sys.exc_info())
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude sağlayıcısı istemcisi."""

    def json_mode_config(self) -> Dict[str, Any]:
        # Anthropic için yerel JSON modu bulunmaz; şema talimatı system prompt'a enjekte edilir
        return {}

    @staticmethod
    def _split_system_and_messages(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, str]]]:
        system_parts: List[str] = []
        conversation: List[Dict[str, str]] = []
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
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
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

        model_name = str(model or _setting(self.config, "ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"))
        if json_mode:
            messages = self._inject_json_instruction(messages)
        system_prompt, conversation = self._split_system_and_messages(messages)
        if not conversation:
            conversation = [{"role": "user", "content": "Merhaba"}]

        client = AsyncAnthropic(api_key=api_key, timeout=self._build_timeout())
        tracer = _get_tracer(self.config)
        span_cm = tracer.start_as_current_span("llm.anthropic.chat") if (tracer and not stream) else None
        span = span_cm.__enter__() if span_cm else (tracer.start_span("llm.anthropic.chat") if tracer and stream else None)
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
                stream_iter = _track_stream_completion(
                    stream_iter,
                    provider="anthropic",
                    model=model_name,
                    started_at=started_at,
                )
                return _trace_stream_metrics(stream_iter, span, started_at)

            async def _do_request():
                return await client.messages.create(
                    model=model_name,
                    max_tokens=4096,
                    temperature=temperature,
                    system=system_prompt or None,
                    messages=conversation,
                )

            response = await _retry_with_backoff("anthropic", _do_request, config=self.config, retry_hint="Anthropic isteği başarısız")
            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            text = "".join(
                getattr(block, "text", "")
                for block in getattr(response, "content", [])
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
                span.end()
            return _ensure_json_text(text, "Anthropic") if json_mode else text
        except LLMAPIError as exc:
            _record_llm_metric(provider="anthropic", model=model_name, started_at=started_at, success=False, error=str(exc))
            if span is not None:
                span.end()
            raise
        except Exception as exc:
            _record_llm_metric(provider="anthropic", model=model_name, started_at=started_at, success=False, error=str(exc))
            if span is not None:
                span.end()
            logger.error("Anthropic hata: %s", exc)
            raise LLMAPIError("anthropic", f"Anthropic hata: {exc}", retryable=False) from exc

    async def _stream_anthropic(
        self,
        client,
        model_name: str,
        messages: List[Dict[str, str]],
        system_prompt: str,
        temperature: float,
        json_mode: bool,
    ) -> AsyncGenerator[str, None]:
        stream_cm = None
        stream = None
        try:
            async def _open_stream():
                cm = client.messages.stream(
                    model=model_name,
                    max_tokens=4096,
                    temperature=temperature,
                    system=system_prompt or None,
                    messages=messages,
                )
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
            yield _ensure_json_text(msg, "Anthropic") if json_mode else msg
        finally:
            if stream_cm is not None:
                await stream_cm.__aexit__(*sys.exc_info())


class LLMClient:
    """Factory sınıfı: sağlayıcıya göre doğru istemciyi seçer."""

    PROVIDER_REGISTRY: Dict[str, type[BaseLLMClient]] = {
        "ollama": OllamaClient,
        "gemini": GeminiClient,
        "openai": OpenAIClient,
        "anthropic": AnthropicClient,
        "litellm": LiteLLMClient,
    }

    def __init__(self, provider: str, config) -> None:
        self.provider = provider.lower()
        self.config = config
        self._semantic_cache = _SemanticCacheManager(config)
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
        return str(_setting(self.config, "OLLAMA_URL", "http://localhost:11434")).removesuffix("/api")

    def _build_ollama_timeout(self) -> httpx.Timeout:
        """Geriye dönük uyumluluk: eski timeout yardımcı adı."""
        if isinstance(self._client, OllamaClient):
            return self._client._build_timeout()
        timeout_seconds = max(10, int(_setting(self.config, "OLLAMA_TIMEOUT", 120)))
        return httpx.Timeout(timeout_seconds, connect=10.0)

    def _truncate_messages_for_local_model(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Yerel modellerde bağlam taşmasını azaltmak için mesajları karakter bazlı kırp."""
        max_chars = max(1200, int(_setting(self.config, "OLLAMA_CONTEXT_MAX_CHARS", 12000)))
        if not messages:
            return messages

        normalized: List[Dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = str(msg.get("content") or "")
            normalized.append({"role": role, "content": content})

        total = sum(len(m["content"]) for m in normalized)
        if total <= max_chars:
            return normalized

        # Önce en son mesajı tam tutmaya çalış, ardından system mesajını sınırlı tut,
        # sonra geçmişi sondan başa doğru doldur.
        result: List[Dict[str, str]] = []
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

        for msg in reversed(normalized[:-1]):
            if used >= max_chars:
                break
            if msg["role"] == "system":
                continue
            remaining = max_chars - used
            content = msg["content"]
            if len(content) > remaining:
                content = content[-remaining:]
            if content:
                result.insert(1 if result and result[0]["role"] == "system" else 0, {"role": msg["role"], "content": content})
                used += len(content)

        return result

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + list(messages)

        # Cost-Aware Routing: karmaşıklık + bütçeye göre provider/model seç
        routed_provider, routed_model = self._router.select(
            messages, self.provider, model
        )
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
                logger.warning("CostRouter yönlendirme başarısız (%s): %s — varsayılana dönülüyor.", routed_provider, exc)
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

        # Bulgu Y-6: Günlük bütçe izleyicisine maliyet kaydı — yalnızca bulut sağlayıcıları için
        if (not stream) and isinstance(response, str) and self.provider != "ollama":
            _msg_chars = sum(len(m.get("content") or "") for m in messages)
            _est_tokens = (_msg_chars + len(response)) // 4
            _cost_per_token = float(
                getattr(self.config, "COST_ROUTING_TOKEN_COST_USD", 2e-6) or 2e-6
            )
            record_routing_cost(_est_tokens * _cost_per_token)

        if (not stream) and user_prompt and isinstance(response, str):
            await self._semantic_cache.set(user_prompt, response)

        return response

    async def list_ollama_models(self) -> List[str]:
        if isinstance(self._client, OllamaClient):
            return await self._client.list_models()
        return []

    async def is_ollama_available(self) -> bool:
        if isinstance(self._client, OllamaClient):
            return await self._client.is_available()
        return False

    async def _stream_gemini_generator(self, response_stream) -> AsyncGenerator[str, None]:
        """Test/geri uyumluluk için Gemini stream dönüştürücüsünü dışa aç."""
        if isinstance(self._client, GeminiClient):
            async for chunk in self._client._stream_gemini_generator(response_stream):
                yield chunk
            return

        async for chunk in GeminiClient(self.config)._stream_gemini_generator(response_stream):
            yield chunk
