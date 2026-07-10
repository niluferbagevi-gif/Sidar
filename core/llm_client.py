"""
Sidar Project - LLM İstemcisi
Ollama, Google Gemini, OpenAI ve Anthropic API entegrasyonu (Asenkron, OOP tabanlı).
"""

from __future__ import annotations

import asyncio
import codecs
import importlib
import random
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Any, cast

import httpx

import core.utils.token_counter as token_counter
from core.cache.semantic_cache import SemanticCacheManager
from core.cache_metrics import record_cache_skip
from core.dlp import mask_messages as _dlp_mask_messages
from core.llm.shared import _OLLAMA_GPU_LIMITERS as _OLLAMA_GPU_LIMITERS
from core.llm.shared import _OLLAMA_GPU_LIMITERS_LOCK as _OLLAMA_GPU_LIMITERS_LOCK
from core.llm.shared import MAX_SAFE_TOKEN_COUNT as MAX_SAFE_TOKEN_COUNT
from core.llm.shared import OLLAMA_NUM_BATCH_AUTO_MIN as OLLAMA_NUM_BATCH_AUTO_MIN
from core.llm.shared import OLLAMA_NUM_BATCH_DEFAULT as OLLAMA_NUM_BATCH_DEFAULT
from core.llm.shared import OLLAMA_NUM_BATCH_MAX as OLLAMA_NUM_BATCH_MAX
from core.llm.shared import SIDAR_TOOL_JSON_INSTRUCTION as SIDAR_TOOL_JSON_INSTRUCTION
from core.llm.shared import SIDAR_TOOL_JSON_SCHEMA as SIDAR_TOOL_JSON_SCHEMA

# Bu isimler artık core.llm.shared içinde tanımlanıyor (bkz. döngüsel import
# düzeltmesi: sağlayıcı modülleri facade'ı değil shared'ı import eder).
# Burada `as X` ile tekrar dışa aktarılırlar; hem geriye dönük uyumluluk
# (`core.llm_client.X`) hem de mevcut testlerin doğrudan erişimi için.
from core.llm.shared import BaseLLMClient as BaseLLMClient
from core.llm.shared import LLMAPIError as LLMAPIError
from core.llm.shared import LLMProvider as LLMProvider
from core.llm.shared import _acquire_ollama_gpu_limiter as _acquire_ollama_gpu_limiter
from core.llm.shared import _ensure_json_text as _ensure_json_text
from core.llm.shared import _ensure_json_text_async as _ensure_json_text_async
from core.llm.shared import _extract_gemini_usage_tokens as _extract_gemini_usage_tokens
from core.llm.shared import _extract_status_code as _extract_status_code
from core.llm.shared import _extract_usage_tokens as _extract_usage_tokens
from core.llm.shared import _fallback_stream as _fallback_stream
from core.llm.shared import _format_exception_message as _format_exception_message
from core.llm.shared import _get_tracer as _get_tracer
from core.llm.shared import _is_retryable_exception as _is_retryable_exception
from core.llm.shared import _is_safe_literal_eval_candidate as _is_safe_literal_eval_candidate
from core.llm.shared import (
    _ollama_gpu_backpressure_int_setting as _ollama_gpu_backpressure_int_setting,
)
from core.llm.shared import _ollama_gpu_backpressure_poll_s as _ollama_gpu_backpressure_poll_s
from core.llm.shared import (
    _ollama_gpu_backpressure_timeout_s as _ollama_gpu_backpressure_timeout_s,
)
from core.llm.shared import _ollama_gpu_limiter as _ollama_gpu_limiter
from core.llm.shared import _ollama_gpu_pool_size as _ollama_gpu_pool_size
from core.llm.shared import _prepare_span_scope as _prepare_span_scope
from core.llm.shared import _record_llm_metric as _record_llm_metric
from core.llm.shared import _release_limiter_after_stream as _release_limiter_after_stream
from core.llm.shared import _repair_json_text as _repair_json_text
from core.llm.shared import _retry_with_backoff as _retry_with_backoff
from core.llm.shared import _safe_token_count as _safe_token_count
from core.llm.shared import _setting as _setting
from core.llm.shared import _trace_stream_metrics as _trace_stream_metrics
from core.llm.shared import _track_stream_completion as _track_stream_completion
from core.llm.shared import build_provider_json_mode_config as build_provider_json_mode_config
from core.llm.shared import get_current_metrics_user_id as get_current_metrics_user_id
from core.llm.shared import get_llm_metrics_collector as get_llm_metrics_collector
from core.llm.shared import logger as logger
from core.router import CostAwareRouter, record_routing_cost

# Geriye dönük uyumluluk: testler `llm_client.codecs` / `llm_client.importlib` /
# `llm_client.random` singleton'larını monkeypatch'leyip `core.llm.shared`
# içindeki fonksiyonların davranışını (jitter, dinamik import vb.) sınıyor.
_COMPAT_IMPORTED_MODULES = (codecs, importlib, random)

DEFAULT_COST_PER_TOKEN_USD = 2e-6
MODEL_COSTS_PER_TOKEN_USD: dict[str, float] = {
    "gpt-4o": 5e-6,
    "gpt-4o-mini": 2e-6,
    "claude-3-5-sonnet": 3e-6,
    "claude-3-5-sonnet-latest": 3e-6,
    "gemini-1.5-pro": 3.5e-6,
    "gemini-1.5-flash": 7.5e-7,
}


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
        est_tokens = _estimate_tokens_bounded(prompt_text, model=model) + _estimate_tokens_bounded(
            completion_text, model=model
        )
        if est_tokens > 0:
            cost_per_token = _resolve_cost_per_token_usd(config, model=model)
            record_routing_cost(est_tokens * cost_per_token)


from core.llm.anthropic import AnthropicClient  # noqa: E402
from core.llm.gemini import GeminiClient  # noqa: E402
from core.llm.litellm import LiteLLMClient  # noqa: E402
from core.llm.ollama import OllamaClient  # noqa: E402
from core.llm.openai import OpenAIClient  # noqa: E402


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

    @classmethod
    def register_provider(cls, name: str, provider_cls: type[BaseLLMClient]) -> None:
        """Register a provider strategy without editing the facade dispatch code."""
        provider_name = (name or "").strip().lower()
        if not provider_name:
            raise ValueError("Provider adı boş olamaz.")
        if not isinstance(provider_cls, type) or not issubclass(provider_cls, BaseLLMClient):
            raise TypeError("Provider sınıfı BaseLLMClient alt sınıfı olmalıdır.")
        cls.PROVIDER_REGISTRY[provider_name] = provider_cls

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
