"""Ollama provider adapter for the LLM facade."""

from __future__ import annotations

import codecs
import json
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

import httpx

import core.llm_client as llm_facade
from config import OLLAMA_BATCH_POLICY
from core.llm_client import (
    OLLAMA_NUM_BATCH_DEFAULT,
    SIDAR_TOOL_JSON_SCHEMA,
    BaseLLMClient,
    LLMAPIError,
    logger,
)


def _setting(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._setting(*args, **kwargs)


def _extract_usage_tokens(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._extract_usage_tokens(*args, **kwargs)


def _extract_gemini_usage_tokens(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._extract_gemini_usage_tokens(*args, **kwargs)


def _ollama_gpu_limiter(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._ollama_gpu_limiter(*args, **kwargs)


def _ollama_gpu_pool_size(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._ollama_gpu_pool_size(*args, **kwargs)


def _acquire_ollama_gpu_limiter(*args: Any, **kwargs: Any) -> Any:
    return llm_facade._acquire_ollama_gpu_limiter(*args, **kwargs)


def _release_limiter_after_stream(
    stream: AsyncIterator[str], limiter: Any
) -> AsyncGenerator[str, None]:
    return llm_facade._release_limiter_after_stream(stream, limiter)


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
        ollama_coding_num_ctx = int(_setting(self.config, "OLLAMA_CODING_NUM_CTX", 8192))
        if ollama_coding_num_ctx > 0:
            options["num_ctx"] = ollama_coding_num_ctx
        configured_num_batch = int(
            _setting(self.config, "OLLAMA_NUM_BATCH", OLLAMA_NUM_BATCH_DEFAULT)
        )
        ollama_num_batch = OLLAMA_BATCH_POLICY.clamp(configured_num_batch)
        if ollama_num_batch <= 0:
            ollama_num_batch = OLLAMA_BATCH_POLICY.auto_batch_for_context(ollama_coding_num_ctx)
        if ollama_num_batch > 0:
            options["num_batch"] = ollama_num_batch
        if bool(_setting(self.config, "USE_GPU", False)):
            options["num_gpu"] = -1

        payload = {
            "model": target_model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }
        keep_alive = str(_setting(self.config, "OLLAMA_KEEP_ALIVE", "")).strip()
        if keep_alive:
            payload["keep_alive"] = keep_alive
        if json_mode:
            payload.update(self.json_mode_config())

        timeout = self._build_timeout()
        span_scope, stream_span = _prepare_span_scope(self.config, "llm.ollama.chat", stream)
        with span_scope as scoped_span:
            span = scoped_span or stream_span
            started_at = time.monotonic()
            gpu_limiter = await _ollama_gpu_limiter(
                self.base_url, _ollama_gpu_pool_size(self.config)
            )
            gpu_limiter_acquired = False
            gpu_limiter_released_by_stream = False
            gpu_limiter_wait_ms = 0.0
            if span is not None:
                span.set_attribute("sidar.llm.provider", "ollama")
                span.set_attribute("sidar.llm.model", target_model)
                span.set_attribute("sidar.llm.stream", stream)
                if gpu_limiter is not None:
                    span.set_attribute(
                        "sidar.llm.gpu_pool_size", _ollama_gpu_pool_size(self.config)
                    )
            try:
                if gpu_limiter is not None:
                    gpu_limiter_wait_ms = await _acquire_ollama_gpu_limiter(
                        gpu_limiter, self.config
                    )
                    gpu_limiter_acquired = True
                    if span is not None:
                        span.set_attribute("sidar.llm.gpu_backpressure_wait_ms", gpu_limiter_wait_ms)
                    wait_warn_ms = int(
                        _setting(self.config, "OLLAMA_GPU_BACKPRESSURE_WARN_MS", 250) or 250
                    )
                    if wait_warn_ms > 0 and gpu_limiter_wait_ms >= wait_warn_ms:
                        logger.warning(
                            "Ollama GPU request pool backpressure waited %.1f ms "
                            "(pool_size=%s).",
                            gpu_limiter_wait_ms,
                            _ollama_gpu_pool_size(self.config),
                        )
                if stream:
                    stream_iter = self._stream_response(url, payload, req_timeout=timeout)
                    traced_stream = _trace_stream_metrics(stream_iter, span, started_at)
                    if gpu_limiter is not None:
                        gpu_limiter_released_by_stream = True
                        return _release_limiter_after_stream(traced_stream, gpu_limiter)
                    return traced_stream

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
                        return cast(dict[str, Any], resp.json())

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
            finally:
                if (
                    gpu_limiter is not None
                    and gpu_limiter_acquired
                    and not gpu_limiter_released_by_stream
                ):
                    gpu_limiter.release()

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
