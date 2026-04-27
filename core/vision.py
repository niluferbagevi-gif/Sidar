"""Multimodal Vision — UI Mockup → Frontend Kodu (v6.0)

Görsel (PNG/JPEG/WebP/GIF) veya screenshot'tan LLM tabanlı frontend
kodu üretir. Gemini, OpenAI GPT-4o-vision, Anthropic Claude-3 vision
sağlayıcılarını destekler.

Kullanım:
    pipeline = VisionPipeline(llm_client, config)
    result = await pipeline.mockup_to_code(image_path="ui.png", framework="React")
    print(result["code"])
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Desteklenen görsel formatları
SUPPORTED_MIME_TYPES = frozenset(
    [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    ]
)

# Görsel boyut limiti (byte) — varsayılan 10 MB
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024

# ──────────────────────────────────────────────────────────────────────────────
# Görsel Ön İşleme
# ──────────────────────────────────────────────────────────────────────────────


async def load_image_as_base64(path: str | Path) -> tuple[str, str]:
    """
    Görseli okuyup (base64_data, mime_type) döner.
    Hatalı format veya boyut aşımında ValueError fırlatır.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Görsel bulunamadı: {path}")

    mime_type = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"Desteklenmeyen görsel formatı: {mime_type}. Desteklenenler: {SUPPORTED_MIME_TYPES}"
        )

    raw = await asyncio.to_thread(p.read_bytes)
    if len(raw) > _DEFAULT_MAX_BYTES:
        mb = len(raw) / (1024 * 1024)
        raise ValueError(
            f"Görsel çok büyük: {mb:.1f} MB (limit: {_DEFAULT_MAX_BYTES / 1024 / 1024:.0f} MB)"
        )

    return base64.b64encode(raw).decode("utf-8"), mime_type


def load_image_from_bytes(data: bytes, mime_type: str = "image/png") -> tuple[str, str]:
    """Byte dizisini base64'e çevirir."""
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(f"Desteklenmeyen MIME tipi: {mime_type}")
    if len(data) > _DEFAULT_MAX_BYTES:
        raise ValueError("Görsel çok büyük.")
    return base64.b64encode(data).decode("utf-8"), mime_type


# ──────────────────────────────────────────────────────────────────────────────
# Provider-specific mesaj formatları
# ──────────────────────────────────────────────────────────────────────────────


def build_vision_messages(
    provider: str,
    text_prompt: str,
    base64_image: str,
    mime_type: str,
) -> list[dict[str, Any]]:
    """
    Sağlayıcıya özgü çok-parçalı (vision) mesaj listesi üretir.

    Desteklenen sağlayıcılar: openai, anthropic, gemini, ollama (llava)
    """
    provider = (provider or "").lower()

    if provider in ("openai", "litellm"):
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ]

    if provider == "anthropic":
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": base64_image,
                        },
                    },
                    {"type": "text", "text": text_prompt},
                ],
            }
        ]

    if provider == "gemini":
        # google-generativeai SDK için inline_data formatı
        return [
            {
                "role": "user",
                "content": [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64_image,
                        }
                    },
                    {"text": text_prompt},
                ],
            }
        ]

    # Ollama (LLaVA, bakllava vb.) — images alanı ayrı gönderilir
    return [
        {
            "role": "user",
            "content": text_prompt,
            "images": [base64_image],
        }
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Prompt Şablonları
# ──────────────────────────────────────────────────────────────────────────────


def build_mockup_prompt(
    framework: str = "React",
    css_framework: str = "Tailwind CSS",
    language: str = "TypeScript",
    extra_instructions: str = "",
) -> str:
    framework = framework or "React"
    css_framework = css_framework or "Tailwind CSS"
    language = language or "TypeScript"
    prompt = (
        f"Bu UI mockup / wireframe görselini analiz et ve tam çalışan "
        f"{framework} ({language}) kodu üret.\n\n"
        "Kurallar:\n"
        f"- CSS framework olarak {css_framework} kullan\n"
        "- Tüm UI bileşenlerini (butonlar, formlar, kartlar, navigasyon) eksiksiz yansıt\n"
        "- Erişilebilirlik (aria-label, semantic HTML) göz önünde bulundur\n"
        "- Responsive tasarım (mobile-first) uygula\n"
        "- Sahte / placeholder veri kullan (gerçek veri bağlama yok)\n"
        "- Yalnızca kod döndür, açıklama veya markdown blok işaretleri ekleme\n"
    )
    if extra_instructions:
        prompt += f"\nEk talimatlar: {extra_instructions}\n"
    return prompt


def build_analyze_prompt(analysis_type: str = "general") -> str:
    """Görsel analizi için sistem prompt'u."""
    prompts = {
        "general": (
            "Bu görseli detaylıca analiz et. "
            "İçerik, düzen, renkler, bileşenler ve olası geliştirme önerileri hakkında "
            "kapsamlı bir rapor sun."
        ),
        "accessibility": (
            "Bu UI görseli için erişilebilirlik (WCAG 2.1) analizi yap. "
            "Renk kontrastı, metin boyutu, odak göstergeleri ve screen reader uyumluluğu hakkında "
            "somut öneriler ver."
        ),
        "ux_review": (
            "Bu kullanıcı arayüzü için UX analizi yap. "
            "Kullanılabilirlik sorunları, bilgi mimarisi, kullanıcı akışı ve iyileştirme önerileri sun."
        ),
    }
    return prompts.get(analysis_type, prompts["general"])


# ──────────────────────────────────────────────────────────────────────────────
# VisionPipeline
# ──────────────────────────────────────────────────────────────────────────────


class VisionPipeline:
    """
    Görsel → LLM pipeline'ı.

    llm_client: LLMClient örneği (core/llm_client.py)
    config: Config nesnesi
    """

    def __init__(self, llm_client, config=None) -> None:
        self._llm = llm_client
        self._provider: str = getattr(llm_client, "provider", "openai")
        self.enabled: bool = bool(getattr(config, "ENABLE_VISION", True))
        self.max_image_bytes: int = int(
            getattr(config, "VISION_MAX_IMAGE_BYTES", _DEFAULT_MAX_BYTES) or _DEFAULT_MAX_BYTES
        )

    async def mockup_to_code(
        self,
        image_path: str | None = None,
        image_bytes: bytes | None = None,
        mime_type: str = "image/png",
        framework: str = "React",
        css_framework: str = "Tailwind CSS",
        language: str = "TypeScript",
        extra_instructions: str = "",
    ) -> dict[str, Any]:
        """
        UI mockup → frontend kodu üretir.
        image_path veya image_bytes parametrelerinden biri zorunludur.
        """
        if not self.enabled:
            return {"success": False, "reason": "ENABLE_VISION devre dışı"}

        try:
            if image_path:
                b64, mime = await load_image_as_base64(image_path)
            elif image_bytes:
                b64, mime = load_image_from_bytes(image_bytes, mime_type)
            else:
                return {"success": False, "reason": "image_path veya image_bytes gerekli"}
        except (FileNotFoundError, ValueError) as exc:
            return {"success": False, "reason": str(exc)}

        prompt = build_mockup_prompt(framework, css_framework, language, extra_instructions)
        messages = build_vision_messages(self._provider, prompt, b64, mime)

        try:
            code = await self._llm.chat(
                messages=messages,
                json_mode=False,
                stream=False,
            )
            return {
                "success": True,
                "code": code,
                "framework": framework,
                "language": language,
                "provider": self._provider,
            }
        except Exception as exc:
            logger.error("VisionPipeline.mockup_to_code hatası: %s", exc)
            return {"success": False, "reason": str(exc)}

    async def analyze(
        self,
        image_path: str | None = None,
        image_bytes: bytes | None = None,
        mime_type: str = "image/png",
        analysis_type: str = "general",
    ) -> dict[str, Any]:
        """Genel görsel analizi yapar."""
        if not self.enabled:
            return {"success": False, "reason": "ENABLE_VISION devre dışı"}

        try:
            if image_path:
                b64, mime = await load_image_as_base64(image_path)
            elif image_bytes:
                b64, mime = load_image_from_bytes(image_bytes, mime_type)
            else:
                return {"success": False, "reason": "image_path veya image_bytes gerekli"}
        except (FileNotFoundError, ValueError) as exc:
            return {"success": False, "reason": str(exc)}

        prompt = build_analyze_prompt(analysis_type)
        messages = build_vision_messages(self._provider, prompt, b64, mime)

        try:
            analysis = await self._llm.chat(
                messages=messages,
                json_mode=False,
                stream=False,
            )
            return {"success": True, "analysis": analysis, "analysis_type": analysis_type}
        except Exception as exc:
            logger.error("VisionPipeline.analyze hatası: %s", exc)
            return {"success": False, "reason": str(exc)}
