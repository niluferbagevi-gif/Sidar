"""Anthropic provider adapter for the LLM facade."""

from __future__ import annotations

import importlib
import json
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator
from importlib import import_module
from typing import Any

from core.llm_client import BaseLLMClient, LLMAPIError, logger

llm_facade = import_module("core.llm_client")


def _setting(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._setting(*args, **kwargs)


def _extract_usage_tokens(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._extract_usage_tokens(*args, **kwargs)


def _extract_gemini_usage_tokens(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._extract_gemini_usage_tokens(*args, **kwargs)


async def _ensure_json_text_async(text: str, provider: str) -> str:
    return await llm_facade._ensure_json_text_async(text, provider)


def _fallback_stream(msg: str) -> AsyncGenerator[str, None]:
    return llm_facade._fallback_stream(msg)


def _prepare_span_scope(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._prepare_span_scope(*args, **kwargs)


def _record_llm_metric(**kwargs: Any) -> Any:
    return llm_facade._record_llm_metric(**kwargs)


def _retry_with_backoff(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._retry_with_backoff(*args, **kwargs)


def _track_stream_completion(
    stream_iter: AsyncIterator[str],
    *,
    provider: str,
    model: str,
    started_at: float,
) -> AsyncIterator[str]:
    return llm_facade._track_stream_completion(
        stream_iter, provider=provider, model=model, started_at=started_at
    )


def _trace_stream_metrics(
    stream_iter: AsyncIterator[str], span: Any, started_at: float
) -> AsyncGenerator[str, None]:
    return llm_facade._trace_stream_metrics(stream_iter, span, started_at)


async def _close_anthropic_client(client: Any) -> None:
    """Close Anthropic async client instances when the SDK exposes a close hook."""
    close = getattr(client, "aclose", None) or getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result


async def _closing_stream(
    stream_iter: AsyncIterator[str], client: Any
) -> AsyncGenerator[str, None]:
    """Yield a stream and close its Anthropic client when iteration finishes."""
    try:
        async for chunk in stream_iter:
            yield chunk
    finally:
        await _close_anthropic_client(client)


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

    def _get_client(self) -> Any:
        """Geriye dönük uyumluluk: testler/mocking için tek noktadan client üretimi."""
        anthropic_module = importlib.import_module("anthropic")
        AsyncAnthropic = anthropic_module.AsyncAnthropic
        api_key = str(_setting(self.config, "ANTHROPIC_API_KEY", ""))
        return AsyncAnthropic(api_key=api_key, timeout=self._build_timeout())

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
            client = self._get_client()
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
                    closing_stream = _closing_stream(stream_iter, client)
                    tracked_stream: AsyncIterator[str] = _track_stream_completion(
                        closing_stream,
                        provider="anthropic",
                        model=model_name,
                        started_at=started_at,
                    )
                    return _trace_stream_metrics(tracked_stream, span, started_at)

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

                try:
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
                        span.set_attribute(
                            "sidar.llm.total_ms", (time.monotonic() - started_at) * 1000
                        )
                    return await _ensure_json_text_async(text, "Anthropic") if json_mode else text
                finally:
                    await _close_anthropic_client(client)
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
