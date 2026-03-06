"""
Sidar Project - LLM İstemcisi
Ollama ve Google Gemini API entegrasyonu (Asenkron).
"""

import json
import logging
import codecs
from typing import AsyncGenerator, AsyncIterator, Dict, List, Optional, Union

import httpx

logger = logging.getLogger(__name__)


class LLMClient:
    """Ollama veya Gemini üzerinden asenkron LLM çağrıları yapar."""

    def __init__(self, provider: str, config) -> None:
        """
        provider: "ollama" | "gemini"
        config  : Config nesnesi
        """
        self.provider = provider.lower()
        self.config = config

    @property
    def _ollama_base_url(self) -> str:
        """Ollama API kök URL'sini normalize eder (sondaki '/api' varsa kaldırır)."""
        return self.config.OLLAMA_URL.removesuffix("/api")

    # ─────────────────────────────────────────────
    #  ANA ÇAĞRI NOKTASI
    # ─────────────────────────────────────────────

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        """
        Sohbet tamamlama isteği gönder (Asenkron).

        Args:
            stream   : True ise yanıt parça parça (AsyncIterator) döner.
            json_mode: True ise modeli JSON çıktıya zorlar (ReAct döngüsü için).
                       Özetleme gibi düz metin gereken çağrılarda False geçin.
        """
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + list(messages)

        if self.provider == "ollama":
            return await self._ollama_chat(messages, model or self.config.CODING_MODEL, temperature, stream, json_mode)
        elif self.provider == "gemini":
            return await self._gemini_chat(messages, temperature, stream, json_mode)
        else:
            raise ValueError(f"Bilinmeyen AI sağlayıcısı: {self.provider}")

    def _build_ollama_timeout(self) -> httpx.Timeout:
        """Ollama istekleri için merkezi timeout profili."""
        timeout_seconds = max(10, int(getattr(self.config, "OLLAMA_TIMEOUT", 120)))
        return httpx.Timeout(timeout_seconds, connect=10.0)

    @staticmethod
    def _ensure_json_text(text: str, provider: str) -> str:
        """json_mode çağrılarında düz metin sızıntısını güvenli JSON'a çevir."""
        try:
            json.loads(text)
            return text
        except Exception:
            return json.dumps({
                "thought": f"{provider} sağlayıcısı JSON dışı içerik döndürdü.",
                "tool": "final_answer",
                "argument": text or "[UYARI] Sağlayıcı boş içerik döndürdü.",
            })

    # ─────────────────────────────────────────────
    #  OLLAMA (ASYNC)
    # ─────────────────────────────────────────────

    async def _ollama_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        stream: bool,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        url = f"{self._ollama_base_url}/api/chat"

        # Ollama options: GPU katman sayısını ilet (USE_GPU=true ise)
        options: dict = {"temperature": temperature}
        use_gpu = getattr(self.config, "USE_GPU", False)
        if use_gpu:
            # num_gpu=-1 → Ollama tüm model katmanlarını GPU'ya atar (0 = CPU-only).
            # GPU_DEVICE, hangi cihazın kullanılacağını belirtir; katman sayısını değil.
            options["num_gpu"] = -1

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }
        # Structured output: Ollama ≥0.4 JSON şeması destekler.
        # ToolCall şeması ile modeli SADECE {thought, tool, argument} üretmeye zorla.
        # Bu hallucination ve yanlış formatlı çıktıların önüne geçer.
        if json_mode:
            payload["format"] = {
                "type": "object",
                "properties": {
                    "thought":  {"type": "string"},
                    "tool":     {"type": "string"},
                    "argument": {"type": "string"},
                },
                "required": ["thought", "tool", "argument"],
                "additionalProperties": False,
            }
        
        timeout = self._build_ollama_timeout()
        
        try:
            # STREAM MODU
            if stream:
                return self._stream_ollama_response(url, payload, timeout=timeout)

            # NORMAL MOD
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                return self._ensure_json_text(content, "Ollama") if json_mode else content

        except httpx.ConnectError:
            logger.error("Ollama bağlantı hatası.")
            msg = json.dumps({"tool": "final_answer", "argument": "[HATA] Ollama'ya bağlanılamadı. 'ollama serve' açık mı?", "thought": "Hata oluştu."})
            return self._fallback_stream(msg) if stream else msg
        except Exception as exc:
            logger.error("Ollama hata: %s", exc)
            msg = json.dumps({"tool": "final_answer", "argument": f"[HATA] Ollama: {exc}", "thought": "Hata oluştu."})
            return self._fallback_stream(msg) if stream else msg

    async def _stream_ollama_response(self, url: str, payload: dict, timeout: int = 120) -> AsyncGenerator[str, None]:
        """
        Ollama stream yanıtını manuel buffer ile güvenli şekilde ayrıştırır.

        Sorun (aiter_lines): TCP paket sınırlarında JSON objesi ikiye bölünebilir;
        JSONDecodeError ile atlanan satır sessizce içerik kaybına yol açar.

        Çözüm: aiter_bytes() ile ham veri okunur, '\\n' karakterine göre satırlara
        bölünür. Tamamlanmamış satır buffer'da bekletilir, tam satır gelince ayrıştırılır.
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    buffer = ""
                    # UTF-8 incremental decoder, paketler arası bölünmüş multibyte
                    # karakterleri güvenli şekilde birleştirir.
                    utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                    async for raw_bytes in resp.aiter_bytes():
                        decoded = utf8_decoder.decode(raw_bytes, final=False)
                        buffer += decoded
                        # Tamamlanmış satırları işle; son (henüz bitmemiş) satır buffer'da kalır
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
                    # Stream bittiğinde decoder içinde kalan parçayı boşalt
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
                    # Akış newline ile bitmezse buffer'da kalan son JSON satırını da işle.
                    if buffer.strip():
                        try:
                            body = json.loads(buffer)
                            chunk = body.get("message", {}).get("content", "")
                            if chunk:
                                yield chunk
                        except json.JSONDecodeError:
                            pass
        except Exception as exc:
            yield json.dumps({"tool": "final_answer", "argument": f"\n[HATA] Akış kesildi: {exc}", "thought": "Hata"})

    # ─────────────────────────────────────────────
    #  GEMINI (ASYNC)
    # ─────────────────────────────────────────────

    async def _gemini_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        stream: bool,
        json_mode: bool = True,
    ) -> Union[str, AsyncIterator[str]]:
        try:
            import google.generativeai as genai
        except ImportError:
            msg = json.dumps({"tool": "final_answer", "argument": "[HATA] 'google-generativeai' kurulu değil.", "thought": "Paket eksik"})
            return self._fallback_stream(msg) if stream else msg

        if not self.config.GEMINI_API_KEY:
            msg = json.dumps({"tool": "final_answer", "argument": "[HATA] GEMINI_API_KEY ayarlanmamış.", "thought": "Key eksik"})
            return self._fallback_stream(msg) if stream else msg

        genai.configure(api_key=self.config.GEMINI_API_KEY)

        # Sistem mesajını ayır
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

        safety_settings = None
        try:
            from google.generativeai.types import HarmBlockThreshold, HarmCategory
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        except Exception:
            # Sürüm uyumsuzluğu durumunda güvenli fallback (SDK string mapping)
            safety_settings = {
                "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            }

        model = genai.GenerativeModel(
            model_name=self.config.GEMINI_MODEL,
            system_instruction=system_text or None,
            generation_config=gen_config,
            safety_settings=safety_settings,
        )

        # Gemini history formatı
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

        try:
            chat_session = model.start_chat(history=history[:-1] if history else [])
            
            if stream:
                # Gemini asenkron çağrısı: send_message_async
                response_stream = await chat_session.send_message_async(prompt, stream=True)
                return self._stream_gemini_generator(response_stream)
            else:
                response = await chat_session.send_message_async(prompt)
                text = getattr(response, "text", "") or ""
                return self._ensure_json_text(text, "Gemini") if json_mode else text

        except Exception as exc:
            logger.error("Gemini hata: %s", exc)
            msg = json.dumps({"tool": "final_answer", "argument": f"[HATA] Gemini: {exc}", "thought": "Hata"})
            return self._fallback_stream(msg) if stream else msg

    async def _stream_gemini_generator(self, response_stream) -> AsyncGenerator[str, None]:
        """Gemini stream yanıtını asenkron dönüştürür."""
        try:
            async for chunk in response_stream:
                text = getattr(chunk, "text", "")
                if text:
                    yield text
        except Exception as exc:
            yield json.dumps({"tool": "final_answer", "argument": f"\n[HATA] Gemini akış hatası: {exc}", "thought": "Hata"})

    async def _fallback_stream(self, msg: str) -> AsyncGenerator[str, None]:
        """Hata durumlarında tek elemanlı asenkron akış döndürür."""
        yield msg

    # ─────────────────────────────────────────────
    #  YARDIMCILAR (ASYNC)
    # ─────────────────────────────────────────────

    async def list_ollama_models(self) -> List[str]:
        url = f"{self._ollama_base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                models = resp.json().get("models", [])
                return [m["name"] for m in models]
        except Exception:
            return []

    async def is_ollama_available(self) -> bool:
        url = f"{self._ollama_base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get(url)
                return True
        except Exception:
            return False  