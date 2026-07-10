"""LiteLLM provider adapter for the LLM facade."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator
from importlib import import_module
from typing import Any, cast

import httpx

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
                                return cast(dict[str, Any], resp.json())

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
