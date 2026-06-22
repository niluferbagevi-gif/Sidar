"""Gemini provider adapter for the LLM facade."""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import core.llm_client as llm_facade
from core.llm_client import BaseLLMClient, logger


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
            import importlib

            google_genai = importlib.import_module("google.genai")
            google_genai_types = importlib.import_module("google.genai.types")

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
                config_kwargs: dict[str, Any] = {"temperature": 0.2 if json_mode else temperature}
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
