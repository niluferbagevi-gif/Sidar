"""OpenAI provider adapter for the LLM facade."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator
from importlib import import_module
from typing import Any, cast

import httpx

from core.llm_client import SIDAR_TOOL_JSON_SCHEMA, BaseLLMClient, LLMAPIError, logger

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


class OpenAIClient(BaseLLMClient):
    """OpenAI Chat Completions istemcisi (opsiyonel sağlayıcı)."""

    @staticmethod
    def _is_test_profile(config: Any) -> bool:
        env_name = (
            str(getattr(config, "SIDAR_ENV", "") or os.getenv("SIDAR_ENV", "") or "")
            .strip()
            .lower()
        )
        return env_name in {"test", "testing"} or bool(os.getenv("PYTEST_CURRENT_TEST"))

    @classmethod
    def _is_dummy_test_api_key(cls, api_key: str, config: Any) -> bool:
        return cls._is_test_profile(config) and str(api_key or "").startswith("sk-test")

    @staticmethod
    def _dummy_api_key_response(api_key: str) -> str:
        return json.dumps(
            {
                "tool": "final_answer",
                "argument": (
                    "[HATA] Test OpenAI API anahtarı algılandı; gerçek OpenAI isteği gönderilmedi."
                ),
                "thought": f"Dummy key guard ({api_key[:7]}...)",
            }
        )

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
        if self._is_dummy_test_api_key(str(api_key), self.config):
            msg = self._dummy_api_key_response(str(api_key))
            return _fallback_stream(msg) if stream else msg

        model_name = str(model or getattr(self.config, "OPENAI_MODEL", "gpt-4o-mini"))
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
                    stream_iter = self._stream_openai(
                        payload, headers, req_timeout=timeout, json_mode=json_mode
                    )
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
                        return cast(dict[str, Any], resp.json())

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
