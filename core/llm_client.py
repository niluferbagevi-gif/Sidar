"""
Sidar Project - LLM İstemcisi
Ollama, Google Gemini, OpenAI ve Anthropic API entegrasyonu (Asenkron, OOP tabanlı).
"""

from __future__ import annotations

import codecs
import asyncio
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional, Union

import httpx
from core.llm_metrics import get_current_metrics_user_id, get_llm_metrics_collector

try:
    from opentelemetry import trace
except Exception:  # OpenTelemetry opsiyoneldir
    trace = None

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


def build_provider_json_mode_config(provider: str) -> Dict[str, Any]:
    """Sidar'ın tekil araç JSON formatını sağlayıcıya göre adapte eder."""
    provider = (provider or "").lower()
    if provider == "ollama":
        return {"format": SIDAR_TOOL_JSON_SCHEMA}
    if provider == "openai":
        # Chat Completions endpointi için yaygın JSON object modu.
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


async def _fallback_stream(msg: str) -> AsyncGenerator[str, None]:
    """Hata durumlarında tek elemanlı asenkron akış döndürür."""
    yield msg


def _get_tracer(config):
    if trace and getattr(config, "ENABLE_TRACING", False):
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


class BaseLLMClient(ABC):
    """LLM sağlayıcıları için soyut istemci arayüzü."""

    def __init__(self, config) -> None:
        self.config = config

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
        return self.config.OLLAMA_URL.removesuffix("/api")

    def _build_timeout(self) -> httpx.Timeout:
        timeout_seconds = max(10, int(getattr(self.config, "OLLAMA_TIMEOUT", 120)))
        return httpx.Timeout(timeout_seconds, connect=10.0)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        target_model = model or getattr(self.config, "CODING_MODEL", "qwen2.5-coder:7b")
        url = f"{self.base_url}/api/chat"

        options: dict = {"temperature": temperature}
        if getattr(self.config, "USE_GPU", False):
            options["num_gpu"] = -1

        payload = {
            "model": target_model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }
        if json_mode:
            payload.update(build_provider_json_mode_config("ollama"))

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
                    resp.raise_for_status()
                    return resp.json()

            data = await _retry_with_backoff("ollama", _do_request, config=self.config, retry_hint="Ollama isteği başarısız")
            content = data.get("message", {}).get("content", "")
            if span is not None:
                span.set_attribute("sidar.llm.total_ms", (time.monotonic() - started_at) * 1000)
            return _ensure_json_text(content, "Ollama") if json_mode else content

        except LLMAPIError:
            raise
        except Exception as exc:
            logger.error("Ollama hata: %s", exc)
            raise LLMAPIError("ollama", f"Ollama hata: {exc}", retryable=False) from exc
        finally:
            if span_cm:
                span_cm.__exit__(None, None, None)

    async def _stream_response(
        self,
        url: str,
        payload: dict,
        timeout: httpx.Timeout,
    ) -> AsyncGenerator[str, None]:
        """Ollama stream yanıtını güvenli buffer yaklaşımı ile ayrıştırır."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    buffer = ""
                    utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                    async for raw_bytes in resp.aiter_bytes():
                        decoded = utf8_decoder.decode(raw_bytes, final=False)
                        buffer += decoded
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                body = json.loads(line)
                                chunk = body.get("message", {}).get("content", "")
                                if chunk:
                                    yield chunk
                            except json.JSONDecodeError:
                                continue

                    trailing = utf8_decoder.decode(b"", final=True)
                    if trailing:
                        buffer += trailing
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                body = json.loads(line)
                                chunk = body.get("message", {}).get("content", "")
                                if chunk:
                                    yield chunk
                            except json.JSONDecodeError:
                                continue

                    if buffer.strip():
                        try:
                            body = json.loads(buffer)
                            chunk = body.get("message", {}).get("content", "")
                            if chunk:
                                yield chunk
                        except json.JSONDecodeError:
                            pass
        except Exception as exc:
            yield json.dumps(
                {
                    "tool": "final_answer",
                    "argument": f"\n[HATA] Akış kesildi: {exc}",
                    "thought": "Hata",
                }
            )

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

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        try:
            import google.generativeai as genai
        except ImportError:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": "[HATA] 'google-generativeai' kurulu değil.",
                    "thought": "Paket eksik",
                }
            )
            return _fallback_stream(msg) if stream else msg

        if not self.config.GEMINI_API_KEY:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": "[HATA] GEMINI_API_KEY ayarlanmamış.",
                    "thought": "Key eksik",
                }
            )
            return _fallback_stream(msg) if stream else msg

        genai.configure(api_key=self.config.GEMINI_API_KEY)

        system_text = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                chat_messages.append(m)

        gen_config = {
            "temperature": 0.2 if json_mode else temperature,
            "response_mime_type": "application/json" if json_mode else "text/plain",
        }
        if json_mode:
            gemini_cfg = build_provider_json_mode_config("gemini").get("generation_config", {})
            gen_config.update(gemini_cfg)

        try:
            from google.generativeai.types import HarmBlockThreshold, HarmCategory

            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        except Exception:
            safety_settings = {
                "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            }

        gm = genai.GenerativeModel(
            model_name=model or self.config.GEMINI_MODEL,
            system_instruction=system_text or None,
            generation_config=gen_config,
            safety_settings=safety_settings,
        )

        history = []
        last_user = None
        for m in chat_messages:
            role = "user" if m["role"] == "user" else "model"
            if role == "user":
                last_user = m["content"]
                if history or last_user:
                    history.append({"role": role, "parts": [m["content"]]})
            else:
                history.append({"role": role, "parts": [m["content"]]})

        if not last_user and chat_messages:
            last_user = chat_messages[-1]["content"]
        prompt = last_user or "Merhaba"

        tracer = _get_tracer(self.config)
        span_cm = tracer.start_as_current_span("llm.gemini.chat") if (tracer and not stream) else None
        span = span_cm.__enter__() if span_cm else (tracer.start_span("llm.gemini.chat") if tracer and stream else None)
        started_at = time.monotonic()
        if span is not None:
            span.set_attribute("sidar.llm.provider", "gemini")
            span.set_attribute("sidar.llm.model", model or self.config.GEMINI_MODEL)
            span.set_attribute("sidar.llm.stream", stream)

        try:
            chat_session = gm.start_chat(history=history[:-1] if history else [])
            if stream:
                response_stream = await chat_session.send_message_async(prompt, stream=True)
                stream_iter = self._stream_gemini_generator(response_stream)
                return _trace_stream_metrics(stream_iter, span, started_at)

            response = await chat_session.send_message_async(prompt)
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
                span_cm.__exit__(None, None, None)

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
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload.update(build_provider_json_mode_config("openai"))

        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(max(10, int(getattr(self.config, "OPENAI_TIMEOUT", 60))), connect=10.0)

        started_at = time.monotonic()
        try:
            if stream:
                payload["stream"] = True
                stream_iter = self._stream_openai(payload, headers, timeout, json_mode)
                return _track_stream_completion(stream_iter, provider="openai", model=model_name, started_at=started_at)

            async def _do_request():
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        json=payload,
                        headers=headers,
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
            return _ensure_json_text(content, "OpenAI") if json_mode else content
        except LLMAPIError as exc:
            _record_llm_metric(provider="openai", model=model_name, started_at=started_at, success=False, error=str(exc))
            raise
        except Exception as exc:
            _record_llm_metric(provider="openai", model=model_name, started_at=started_at, success=False, error=str(exc))
            logger.error("OpenAI hata: %s", exc)
            raise LLMAPIError("openai", f"OpenAI hata: {exc}", retryable=False) from exc

    async def _stream_openai(
        self,
        payload: dict,
        headers: dict,
        timeout: httpx.Timeout,
        json_mode: bool,
    ) -> AsyncGenerator[str, None]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                ) as resp:
                    resp.raise_for_status()
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


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude sağlayıcısı istemcisi."""

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
        return max(10, int(getattr(self.config, "ANTHROPIC_TIMEOUT", 60)))

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        api_key = getattr(self.config, "ANTHROPIC_API_KEY", "")
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
        except Exception as exc:
            msg = json.dumps(
                {
                    "tool": "final_answer",
                    "argument": f"[HATA] anthropic paketi kullanılamıyor: {exc}",
                    "thought": "Anthropic istemcisi başlatılamadı.",
                }
            )
            return _fallback_stream(msg) if stream else msg

        model_name = model or getattr(self.config, "ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        system_prompt, conversation = self._split_system_and_messages(messages)
        if not conversation:
            conversation = [{"role": "user", "content": "Merhaba"}]

        if json_mode:
            json_instruction = (
                "Sadece geçerli JSON döndür. JSON şeması: "
                '{"thought": string, "tool": string, "argument": string}. '
                "Ek açıklama yazma."
            )
            system_prompt = f"{system_prompt}\n\n{json_instruction}".strip()

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
        try:
            async with client.messages.stream(
                model=model_name,
                max_tokens=4096,
                temperature=temperature,
                system=system_prompt or None,
                messages=messages,
            ) as stream:
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
                }
            )
            yield _ensure_json_text(msg, "Anthropic") if json_mode else msg


class LLMClient:
    """Factory sınıfı: sağlayıcıya göre doğru istemciyi seçer."""

    def __init__(self, provider: str, config) -> None:
        self.provider = provider.lower()
        self.config = config

        if self.provider == "ollama":
            self._client: BaseLLMClient = OllamaClient(config)
        elif self.provider == "gemini":
            self._client = GeminiClient(config)
        elif self.provider == "openai":
            self._client = OpenAIClient(config)
        elif self.provider == "anthropic":
            self._client = AnthropicClient(config)
        else:
            raise ValueError(f"Bilinmeyen AI sağlayıcısı: {self.provider}")

    @property
    def _ollama_base_url(self) -> str:
        """Geriye dönük uyumluluk: Ollama taban URL bilgisi."""
        if isinstance(self._client, OllamaClient):
            return self._client.base_url
        return self.config.OLLAMA_URL.removesuffix("/api")

    def _build_ollama_timeout(self) -> httpx.Timeout:
        """Geriye dönük uyumluluk: eski timeout yardımcı adı."""
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
        """Test/geri uyumluluk için Gemini stream dönüştürücüsünü dışa aç."""
        if isinstance(self._client, GeminiClient):
            async for chunk in self._client._stream_gemini_generator(response_stream):
                yield chunk
            return

        async for chunk in GeminiClient(self.config)._stream_gemini_generator(response_stream):
            yield chunk