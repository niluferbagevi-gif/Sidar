"""Testler: Multimodal Vision Pipeline (Özellik 9)"""
from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.vision import (
    SUPPORTED_MIME_TYPES,
    VisionPipeline,
    build_analyze_prompt,
    build_mockup_prompt,
    build_vision_messages,
    load_image_as_base64,
    load_image_from_bytes,
)


def _run(coro):
    return asyncio.run(coro)


# ─── Yardımcı: küçük PNG oluştur ─────────────────────────────────────────────

def _tiny_png_bytes() -> bytes:
    """1×1 piksel geçerli PNG (minimal)."""
    return (
        b"\x89PNG\r\n\x1a\n"        # imza
        b"\x00\x00\x00\rIHDR"       # IHDR chunk uzunluğu
        b"\x00\x00\x00\x01"         # genişlik=1
        b"\x00\x00\x00\x01"         # yükseklik=1
        b"\x08\x02"                  # bit depth=8, color type=2 (RGB)
        b"\x00\x00\x00"              # compression/filter/interlace
        b"\x90wS\xde"               # CRC
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


# ─── load_image_as_base64 ─────────────────────────────────────────────────────

class TestLoadImageAsBase64:
    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _run(load_image_as_base64(tmp_path / "nonexistent.png"))

    def test_unsupported_format_raises(self, tmp_path):
        p = tmp_path / "img.bmp"
        p.write_bytes(b"\x00" * 10)
        with pytest.raises(ValueError, match="Desteklenmeyen"):
            _run(load_image_as_base64(p))

    def test_file_too_large_raises(self, tmp_path):
        p = tmp_path / "big.png"
        # 11 MB
        p.write_bytes(b"\x00" * (11 * 1024 * 1024))
        with pytest.raises(ValueError, match="büyük"):
            _run(load_image_as_base64(p))

    def test_valid_png_returns_base64(self, tmp_path):
        p = tmp_path / "test.png"
        raw = _tiny_png_bytes()
        p.write_bytes(raw)
        b64, mime = _run(load_image_as_base64(p))
        assert mime == "image/png"
        assert base64.b64decode(b64) == raw

    def test_valid_jpeg_returns_correct_mime(self, tmp_path):
        p = tmp_path / "test.jpg"
        raw = b"\xff\xd8\xff\xe0" + b"\x00" * 20  # minimal JPEG header
        p.write_bytes(raw)
        b64, mime = _run(load_image_as_base64(p))
        assert mime == "image/jpeg"


# ─── load_image_from_bytes ────────────────────────────────────────────────────

class TestLoadImageFromBytes:
    def test_unsupported_mime_raises(self):
        with pytest.raises(ValueError, match="MIME"):
            load_image_from_bytes(b"\x00" * 10, "image/bmp")

    def test_too_large_raises(self):
        with pytest.raises(ValueError, match="büyük"):
            load_image_from_bytes(b"\x00" * (11 * 1024 * 1024), "image/png")

    def test_valid_data_returns_base64(self):
        data = b"\x89PNG test"
        b64, mime = load_image_from_bytes(data, "image/png")
        assert mime == "image/png"
        assert base64.b64decode(b64) == data

    def test_webp_mime_accepted(self):
        data = b"RIFF" + b"\x00" * 20
        b64, mime = load_image_from_bytes(data, "image/webp")
        assert mime == "image/webp"

    def test_gif_mime_accepted(self):
        data = b"GIF89a" + b"\x00" * 10
        b64, mime = load_image_from_bytes(data, "image/gif")
        assert mime == "image/gif"


# ─── build_vision_messages ────────────────────────────────────────────────────

class TestBuildVisionMessages:
    B64 = "dGVzdA=="
    MIME = "image/png"
    PROMPT = "Analiz et"

    def test_openai_format(self):
        msgs = build_vision_messages("openai", self.PROMPT, self.B64, self.MIME)
        assert len(msgs) == 1
        content = msgs[0]["content"]
        types = [c["type"] for c in content]
        assert "text" in types
        assert "image_url" in types

    def test_litellm_format_same_as_openai(self):
        msgs_oi = build_vision_messages("openai", self.PROMPT, self.B64, self.MIME)
        msgs_ll = build_vision_messages("litellm", self.PROMPT, self.B64, self.MIME)
        assert msgs_oi == msgs_ll

    def test_openai_image_url_contains_base64(self):
        msgs = build_vision_messages("openai", self.PROMPT, self.B64, self.MIME)
        image_part = next(c for c in msgs[0]["content"] if c["type"] == "image_url")
        assert self.B64 in image_part["image_url"]["url"]
        assert self.MIME in image_part["image_url"]["url"]

    def test_anthropic_format(self):
        msgs = build_vision_messages("anthropic", self.PROMPT, self.B64, self.MIME)
        assert len(msgs) == 1
        content = msgs[0]["content"]
        # İlk parça: image source
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["data"] == self.B64
        # İkinci parça: text
        assert content[1]["type"] == "text"
        assert content[1]["text"] == self.PROMPT

    def test_gemini_format(self):
        msgs = build_vision_messages("gemini", self.PROMPT, self.B64, self.MIME)
        assert len(msgs) == 1
        content = msgs[0]["content"]
        inline = content[0]
        assert "inline_data" in inline
        assert inline["inline_data"]["data"] == self.B64
        assert inline["inline_data"]["mime_type"] == self.MIME

    def test_ollama_format(self):
        msgs = build_vision_messages("ollama", self.PROMPT, self.B64, self.MIME)
        assert len(msgs) == 1
        msg = msgs[0]
        assert msg["content"] == self.PROMPT
        assert msg["images"] == [self.B64]

    def test_unknown_provider_falls_back_to_ollama(self):
        msgs = build_vision_messages("unknown_provider", self.PROMPT, self.B64, self.MIME)
        assert "images" in msgs[0]

    def test_empty_provider_falls_back(self):
        msgs = build_vision_messages("", self.PROMPT, self.B64, self.MIME)
        assert "images" in msgs[0]


# ─── build_mockup_prompt ──────────────────────────────────────────────────────

class TestBuildMockupPrompt:
    def test_default_values_present(self):
        p = build_mockup_prompt()
        assert "React" in p
        assert "TypeScript" in p
        assert "Tailwind CSS" in p

    def test_custom_framework(self):
        p = build_mockup_prompt(framework="Vue", language="JavaScript")
        assert "Vue" in p
        assert "JavaScript" in p

    def test_extra_instructions_included(self):
        p = build_mockup_prompt(extra_instructions="Dark mode zorunlu")
        assert "Dark mode zorunlu" in p

    def test_no_extra_instructions_no_suffix(self):
        p = build_mockup_prompt(extra_instructions="")
        assert "Ek talimatlar" not in p

    def test_empty_framework_uses_default(self):
        p = build_mockup_prompt(framework="")
        assert "React" in p


# ─── build_analyze_prompt ─────────────────────────────────────────────────────

class TestBuildAnalyzePrompt:
    def test_general_type(self):
        p = build_analyze_prompt("general")
        assert len(p) > 10

    def test_accessibility_type(self):
        p = build_analyze_prompt("accessibility")
        assert "WCAG" in p or "erişilebilirlik" in p.lower()

    def test_ux_review_type(self):
        p = build_analyze_prompt("ux_review")
        assert "UX" in p or "kullanılabilirlik" in p.lower()

    def test_unknown_type_falls_back_to_general(self):
        p1 = build_analyze_prompt("unknown")
        p2 = build_analyze_prompt("general")
        assert p1 == p2


# ─── VisionPipeline ───────────────────────────────────────────────────────────

def _make_pipeline(enabled=True, provider="openai"):
    cfg = MagicMock()
    cfg.ENABLE_VISION = enabled
    cfg.VISION_MAX_IMAGE_BYTES = 10 * 1024 * 1024
    llm = MagicMock()
    llm.provider = provider
    llm.chat = AsyncMock(return_value="<button>Click me</button>")
    return VisionPipeline(llm_client=llm, config=cfg)


class TestVisionPipelineDisabled:
    def test_mockup_to_code_disabled(self):
        vp = _make_pipeline(enabled=False)
        result = _run(vp.mockup_to_code(image_bytes=b"\x00", mime_type="image/png"))
        assert result["success"] is False
        assert "devre dışı" in result["reason"]

    def test_analyze_disabled(self):
        vp = _make_pipeline(enabled=False)
        result = _run(vp.analyze(image_bytes=b"\x00", mime_type="image/png"))
        assert result["success"] is False


class TestVisionPipelineNoImage:
    def test_mockup_no_image_returns_error(self):
        vp = _make_pipeline()
        result = _run(vp.mockup_to_code())
        assert result["success"] is False
        assert "gerekli" in result["reason"]

    def test_analyze_no_image_returns_error(self):
        vp = _make_pipeline()
        result = _run(vp.analyze())
        assert result["success"] is False


class TestVisionPipelineFromBytes:
    def test_mockup_to_code_from_bytes_success(self):
        vp = _make_pipeline(provider="openai")
        data = _tiny_png_bytes()
        result = _run(vp.mockup_to_code(image_bytes=data, mime_type="image/png", framework="Vue"))
        assert result["success"] is True
        assert result["code"] == "<button>Click me</button>"
        assert result["framework"] == "Vue"
        assert result["provider"] == "openai"

    def test_analyze_unsupported_mime_returns_error(self):
        vp = _make_pipeline()
        result = _run(vp.analyze(image_bytes=b"\x00" * 10, mime_type="image/bmp"))
        assert result["success"] is False
        assert "Desteklenmeyen" in result["reason"]


    def test_analyze_from_bytes_success(self):
        vp = _make_pipeline()
        data = _tiny_png_bytes()
        result = _run(vp.analyze(image_bytes=data, mime_type="image/png", analysis_type="accessibility"))
        assert result["success"] is True
        assert result["analysis_type"] == "accessibility"

    def test_unsupported_mime_returns_error(self):
        vp = _make_pipeline()
        result = _run(vp.mockup_to_code(image_bytes=b"\x00" * 10, mime_type="image/bmp"))
        assert result["success"] is False

    def test_too_large_bytes_returns_error(self):
        vp = _make_pipeline()
        big = b"\x00" * (11 * 1024 * 1024)
        result = _run(vp.mockup_to_code(image_bytes=big, mime_type="image/png"))
        assert result["success"] is False


class TestVisionPipelineFromFile:
    def test_mockup_to_code_from_file(self, tmp_path):
        p = tmp_path / "ui.png"
        p.write_bytes(_tiny_png_bytes())
        vp = _make_pipeline()
        result = _run(vp.mockup_to_code(image_path=str(p)))
        assert result["success"] is True

    def test_file_not_found_returns_error(self, tmp_path):
        vp = _make_pipeline()
        result = _run(vp.mockup_to_code(image_path=str(tmp_path / "ghost.png")))
        assert result["success"] is False

    def test_analyze_from_file(self, tmp_path):
        p = tmp_path / "screen.png"
        p.write_bytes(_tiny_png_bytes())
        vp = _make_pipeline()
        result = _run(vp.analyze(image_path=str(p)))
        assert result["success"] is True
        assert "analysis" in result


class TestVisionPipelineLLMError:
    def test_mockup_llm_exception_returns_error(self):
        cfg = MagicMock()
        cfg.ENABLE_VISION = True
        cfg.VISION_MAX_IMAGE_BYTES = 10 * 1024 * 1024
        llm = MagicMock()
        llm.provider = "anthropic"
        llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        vp = VisionPipeline(llm_client=llm, config=cfg)
        result = _run(vp.mockup_to_code(image_bytes=_tiny_png_bytes(), mime_type="image/png"))
        assert result["success"] is False
        assert "LLM down" in result["reason"]

    def test_analyze_llm_exception_returns_error(self):
        cfg = MagicMock()
        cfg.ENABLE_VISION = True
        cfg.VISION_MAX_IMAGE_BYTES = 10 * 1024 * 1024
        llm = MagicMock()
        llm.provider = "gemini"
        llm.chat = AsyncMock(side_effect=RuntimeError("vision provider failed"))
        vp = VisionPipeline(llm_client=llm, config=cfg)

        result = _run(vp.analyze(image_bytes=_tiny_png_bytes(), analysis_type="ux_review"))

        assert result["success"] is False
        assert "vision provider failed" in result["reason"]


    def test_analyze_anthropic_provider(self):
        vp = _make_pipeline(provider="anthropic")
        vp._llm.chat = AsyncMock(return_value="Erişilebilirlik raporu")
        result = _run(vp.analyze(image_bytes=_tiny_png_bytes(), analysis_type="ux_review"))
        assert result["success"] is True
        assert result["analysis"] == "Erişilebilirlik raporu"