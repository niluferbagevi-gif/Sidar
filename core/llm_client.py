"""Sidar Project - LLM Gateway istemcisi (LiteLLM/OpenRouter merkezli)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from abc import ABC
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional, Union

import httpx
from core.llm_metrics import get_current_metrics_user_id, get_llm_metrics_collector

try:
    from opentelemetry import trace
except Exception:  # OpenTelemetry opsiyoneldir
    trace = None

logger = logging.getLogger(__name__)


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
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, asyncio.TimeoutError)):
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

            delay = min(max_delay, base_delay * (2 ** attempt)) + random.uniform(0, 0.15)
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
        return json.dumps(
            {
                "thought": f"{provider} sağlayıcısı JSON dışı içerik döndürdü.",
                "tool": "final_answer",
                "argument": text or "[UYARI] Sağlayıcı boş içerik döndürdü.",
            }
        )


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


class BaseLLMClient(ABC):
    def __init__(self, config) -> None:
        self.config = config

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        raise NotImplementedError


class GatewayLLMClient(BaseLLMClient):
    """Merkezi gateway katmanı: LiteLLM varsa onu, yoksa OpenAI-compatible HTTP yolunu kullanır."""

    provider_name = "gateway"

    def _default_model(self) -> str:
        return getattr(self.config, "CODING_MODEL", "gpt-4o-mini")

    def _provider_model(self, model: Optional[str]) -> str:
        return model or self._default_model()

    def _gateway_base_url(self) -> str:
        if self.provider_name == "ollama":
            return str(getattr(self.config, "OLLAMA_URL", "http://localhost:11434/api")).removesuffix("/api")
        return str(getattr(self.config, "OPENROUTER_BASE_URL", os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")))

    def _gateway_api_key(self) -> str:
        if self.provider_name == "openai":
            return str(getattr(self.config, "OPENAI_API_KEY", ""))
        if self.provider_name == "anthropic":
            return str(getattr(self.config, "ANTHROPIC_API_KEY", ""))
        if self.provider_name == "gemini":
            return str(getattr(self.config, "GEMINI_API_KEY", ""))
        return str(getattr(self.config, "OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", "")))

    async def _chat_litellm(self, *, messages: List[Dict[str, str]], model: str, temperature: float, stream: bool, json_mode: bool):
        import litellm  # type: ignore

        response_format = {"type": "json_object"} if json_mode else None
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if response_format:
            kwargs["response_format"] = response_format

        # provider hintleri
        if self.provider_name == "ollama":
            kwargs["api_base"] = self._gateway_base_url()
        elif self.provider_name in {"openai", "anthropic", "gemini"}:
            api_key = self._gateway_api_key()
            if api_key:
                kwargs["api_key"] = api_key
        else:
            kwargs["api_base"] = self._gateway_base_url()
            api_key = self._gateway_api_key()
            if api_key:
                kwargs["api_key"] = api_key

        return await litellm.acompletion(**kwargs)

    async def _chat_http_compat(self, *, messages: List[Dict[str, str]], model: str, temperature: float, stream: bool, json_mode: bool):
        base = self._gateway_base_url().rstrip("/")
        api_key = self._gateway_api_key()
        timeout = max(10, int(getattr(self.config, "OPENAI_TIMEOUT", getattr(self.config, "ANTHROPIC_TIMEOUT", 60))))

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=timeout) as client:
            if stream:
                async with client.stream("POST", f"{base}/chat/completions", headers=headers, json=payload) as resp:
                    resp.raise_for_status()

                    async def _iter() -> AsyncIterator[str]:
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                obj = json.loads(data)
                                delta = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            except Exception:
                                delta = ""
                            if delta:
                                yield delta

                    return _iter()

            r = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        target_model = self._provider_model(model)
        started = time.monotonic()

        async def _op():
            try:
                import litellm  # noqa: F401
                return await self._chat_litellm(
                    messages=messages,
                    model=target_model,
                    temperature=temperature,
                    stream=stream,
                    json_mode=json_mode,
                )
            except Exception:
                return await self._chat_http_compat(
                    messages=messages,
                    model=target_model,
                    temperature=temperature,
                    stream=stream,
                    json_mode=json_mode,
                )

        out = await _retry_with_backoff(self.provider_name, _op, config=self.config, retry_hint="Gateway chat başarısız")

        if stream:
            async def _stream() -> AsyncIterator[str]:
                try:
                    if hasattr(out, "__aiter__"):
                        async for chunk in out:
                            text = ""
                            try:
                                choices = chunk.choices if hasattr(chunk, "choices") else []
                                if choices:
                                    delta = getattr(choices[0], "delta", None)
                                    text = getattr(delta, "content", "") or ""
                            except Exception:
                                text = str(chunk) if chunk else ""
                            if text:
                                yield _ensure_json_text(text, self.provider_name) if json_mode else text
                    else:
                        return
                    _record_llm_metric(provider=self.provider_name, model=target_model, started_at=started, success=True)
                except Exception as exc:
                    _record_llm_metric(provider=self.provider_name, model=target_model, started_at=started, success=False, error=str(exc))
                    msg = json.dumps({"tool": "final_answer", "argument": f"[HATA] {exc}", "thought": "Hata"})
                    yield _ensure_json_text(msg, self.provider_name) if json_mode else msg

            return _stream()

        text = str(out)
        text = _ensure_json_text(text, self.provider_name) if json_mode else text
        _record_llm_metric(provider=self.provider_name, model=target_model, started_at=started, success=True)
        return text


class OllamaClient(GatewayLLMClient):
    provider_name = "ollama"

    @property
    def base_url(self) -> str:
        return self._gateway_base_url()

    def _build_timeout(self) -> httpx.Timeout:
        timeout_seconds = max(10, int(getattr(self.config, "OLLAMA_TIMEOUT", 120)))
        return httpx.Timeout(timeout_seconds, connect=10.0)

    async def list_models(self) -> List[str]:
        try:
            async with httpx.AsyncClient(timeout=self._build_timeout()) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                payload = resp.json()
                models = payload.get("models", []) if isinstance(payload, dict) else []
                return [str(m.get("name", "")) for m in models if isinstance(m, dict) and m.get("name")]
        except Exception:
            return []

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._build_timeout()) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False


class GeminiClient(GatewayLLMClient):
    provider_name = "gemini"

    def _default_model(self) -> str:
        return getattr(self.config, "GEMINI_MODEL", "gemini-2.5-flash")

    async def _stream_gemini_generator(self, response_stream) -> AsyncGenerator[str, None]:
        async for chunk in response_stream:
            yield str(chunk)


class OpenAIClient(GatewayLLMClient):
    provider_name = "openai"

    def _default_model(self) -> str:
        return getattr(self.config, "OPENAI_MODEL", "gpt-4o-mini")


class AnthropicClient(GatewayLLMClient):
    provider_name = "anthropic"

    def _default_model(self) -> str:
        return getattr(self.config, "ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

    @staticmethod
    def _split_system_and_messages(messages: List[Dict[str, str]]) -> tuple[Optional[str], List[Dict[str, str]]]:
        system = None
        converted: List[Dict[str, str]] = []
        for msg in messages:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            if role == "system" and system is None:
                system = content
                continue
            converted.append({"role": role, "content": content})
        return system, converted


class LLMClient:
    """Factory sınıfı: sağlayıcıya göre doğru istemciyi seçer."""

    def __init__(self, provider: str, config) -> None:
        self.provider = provider.lower()
        self.config = config

        provider_registry = {
            "ollama": OllamaClient,
            "gemini": GeminiClient,
            "openai": OpenAIClient,
            "anthropic": AnthropicClient,
        }
        client_cls = provider_registry.get(self.provider)
        if client_cls is None:
            raise ValueError(f"Bilinmeyen AI sağlayıcısı: {self.provider}")
        self._client: BaseLLMClient = client_cls(config)

    @property
    def _ollama_base_url(self) -> str:
        if isinstance(self._client, OllamaClient):
            return self._client.base_url
        return self.config.OLLAMA_URL.removesuffix("/api")

    def _build_ollama_timeout(self) -> httpx.Timeout:
        if isinstance(self._client, OllamaClient):
            return self._client._build_timeout()
        timeout_seconds = max(10, int(getattr(self.config, "OLLAMA_TIMEOUT", 120)))
        return httpx.Timeout(timeout_seconds, connect=10.0)

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
        return await self._client.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            stream=stream,
            json_mode=json_mode,
        )

    async def list_ollama_models(self) -> List[str]:
        if isinstance(self._client, OllamaClient):
            return await self._client.list_models()
        return []

    async def is_ollama_available(self) -> bool:
        if isinstance(self._client, OllamaClient):
            return await self._client.is_available()
        return False

    async def _stream_gemini_generator(self, response_stream) -> AsyncGenerator[str, None]:
        if isinstance(self._client, GeminiClient):
            async for chunk in self._client._stream_gemini_generator(response_stream):
                yield chunk
            return

        async for chunk in GeminiClient(self.config)._stream_gemini_generator(response_stream):
            yield chunk