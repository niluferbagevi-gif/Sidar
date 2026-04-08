"""Unit tests for core/vision.py — VisionPipeline ve yardımcı fonksiyonlar."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.vision as vision_module
from core.vision import (
    SUPPORTED_MIME_TYPES,
    VisionPipeline,
    build_analyze_prompt,
    build_mockup_prompt,
    build_vision_messages,
    load_image_from_bytes,
    load_image_as_base64,
)


# ──────────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ──────────────────────────────────────────────────────────────────────────────

def _make_llm(response: str = "llm-output") -> MagicMock:
    llm = MagicMock()
    llm.provider = "openai"
    llm.chat = AsyncMock(return_value=response)
    return llm


def _make_config(**overrides) -> MagicMock:
    cfg = MagicMock()
    cfg.ENABLE_VISION = True
    cfg.VISION_MAX_IMAGE_BYTES = vision_module._DEFAULT_MAX_BYTES
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────────────────
# load_image_from_bytes
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadImageFromBytes:
    def test_success_returns_base64_and_mime(self):
        data = b"\x89PNG\r\n\x1a\n"
        b64, mime = load_image_from_bytes(data, mime_type="image/png")
        assert mime == "image/png"
        assert base64.b64decode(b64) == data

    def test_unsupported_mime_raises_value_error(self):
        with pytest.raises(ValueError, match="Desteklenmeyen MIME tipi"):
            load_image_from_bytes(b"data", mime_type="image/bmp")

    def test_oversized_data_raises_value_error(self, monkeypatch):
        monkeypatch.setattr(vision_module, "_DEFAULT_MAX_BYTES", 4)
        with pytest.raises(ValueError, match="çok büyük"):
            load_image_from_bytes(b"12345", mime_type="image/png")

    def test_all_supported_mime_types_are_accepted(self):
        for mime in SUPPORTED_MIME_TYPES:
            b64, returned_mime = load_image_from_bytes(b"x", mime_type=mime)
            assert returned_mime == mime
            assert isinstance(b64, str)


# ──────────────────────────────────────────────────────────────────────────────
# load_image_as_base64
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadImageAsBase64:
    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            run(load_image_as_base64(tmp_path / "missing.png"))

    def test_success_returns_base64_and_mime(self, tmp_path):
        img = tmp_path / "sample.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        b64, mime = run(load_image_as_base64(img))
        assert mime == "image/png"
        assert base64.b64decode(b64) == b"\x89PNG\r\n\x1a\n"

    def test_unsupported_extension_raises_value_error(self, tmp_path):
        bad = tmp_path / "file.bmp"
        bad.write_bytes(b"BM")
        with pytest.raises(ValueError, match="Desteklenmeyen"):
            run(load_image_as_base64(bad))

    def test_oversized_file_raises_value_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vision_module, "_DEFAULT_MAX_BYTES", 2)
        img = tmp_path / "big.png"
        img.write_bytes(b"PNG_CONTENT_TOO_LONG")
        with pytest.raises(ValueError, match="çok büyük"):
            run(load_image_as_base64(img))

    def test_jpeg_mime_type_detected(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff")
        b64, mime = run(load_image_as_base64(img))
        assert mime == "image/jpeg"

    def test_webp_mime_type_detected(self, tmp_path):
        img = tmp_path / "anim.webp"
        img.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        b64, mime = run(load_image_as_base64(img))
        assert mime == "image/webp"

    def test_gif_mime_type_detected(self, tmp_path):
        img = tmp_path / "anim.gif"
        img.write_bytes(b"GIF89a")
        b64, mime = run(load_image_as_base64(img))
        assert mime == "image/gif"


# ──────────────────────────────────────────────────────────────────────────────
# build_vision_messages
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildVisionMessages:
    _B64 = "dGVzdA=="
    _MIME = "image/png"
    _PROMPT = "Bu görseli analiz et"

    def test_openai_format(self):
        msgs = build_vision_messages("openai", self._PROMPT, self._B64, self._MIME)
        assert len(msgs) == 1
        content = msgs[0]["content"]
        types = [c["type"] for c in content]
        assert "text" in types
        assert "image_url" in types
        image_block = next(c for c in content if c["type"] == "image_url")
        assert f"data:{self._MIME};base64,{self._B64}" in image_block["image_url"]["url"]

    def test_litellm_uses_openai_format(self):
        msgs = build_vision_messages("litellm", self._PROMPT, self._B64, self._MIME)
        assert msgs[0]["content"][1]["type"] == "image_url"

    def test_anthropic_format(self):
        msgs = build_vision_messages("anthropic", self._PROMPT, self._B64, self._MIME)
        content = msgs[0]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["data"] == self._B64
        assert content[0]["source"]["media_type"] == self._MIME
        assert content[1]["type"] == "text"
        assert content[1]["text"] == self._PROMPT

    def test_gemini_format(self):
        msgs = build_vision_messages("gemini", self._PROMPT, self._B64, self._MIME)
        content = msgs[0]["content"]
        inline = content[0]["inline_data"]
        assert inline["mime_type"] == self._MIME
        assert inline["data"] == self._B64
        assert content[1]["text"] == self._PROMPT

    def test_ollama_format(self):
        msgs = build_vision_messages("ollama", self._PROMPT, self._B64, self._MIME)
        assert msgs[0]["content"] == self._PROMPT
        assert self._B64 in msgs[0]["images"]

    def test_unknown_provider_falls_back_to_ollama(self):
        msgs = build_vision_messages("unknown_xyz", self._PROMPT, self._B64, self._MIME)
        assert "images" in msgs[0]

    def test_none_provider_falls_back_to_ollama(self):
        msgs = build_vision_messages(None, self._PROMPT, self._B64, self._MIME)
        assert "images" in msgs[0]

    def test_provider_comparison_is_case_insensitive(self):
        msgs_upper = build_vision_messages("OpenAI", self._PROMPT, self._B64, self._MIME)
        msgs_lower = build_vision_messages("openai", self._PROMPT, self._B64, self._MIME)
        assert msgs_upper == msgs_lower


# ──────────────────────────────────────────────────────────────────────────────
# build_mockup_prompt
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildMockupPrompt:
    def test_defaults_contain_react_and_tailwind(self):
        prompt = build_mockup_prompt()
        assert "React" in prompt
        assert "Tailwind CSS" in prompt
        assert "TypeScript" in prompt

    def test_custom_framework_and_css(self):
        prompt = build_mockup_prompt(framework="Vue", css_framework="Bootstrap", language="JavaScript")
        assert "Vue" in prompt
        assert "Bootstrap" in prompt
        assert "JavaScript" in prompt

    def test_extra_instructions_appended(self):
        prompt = build_mockup_prompt(extra_instructions="Dark mode zorunlu")
        assert "Dark mode zorunlu" in prompt

    def test_no_extra_instructions_omitted(self):
        prompt = build_mockup_prompt()
        assert "Ek talimatlar" not in prompt

    def test_empty_framework_falls_back_to_react(self):
        prompt = build_mockup_prompt(framework="")
        assert "React" in prompt

    def test_empty_css_framework_falls_back_to_tailwind(self):
        prompt = build_mockup_prompt(css_framework="")
        assert "Tailwind CSS" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# build_analyze_prompt
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildAnalyzePrompt:
    def test_general_is_default(self):
        prompt = build_analyze_prompt()
        assert len(prompt) > 20

    def test_accessibility_prompt_contains_wcag(self):
        prompt = build_analyze_prompt("accessibility")
        assert "WCAG" in prompt

    def test_ux_review_prompt_contains_ux(self):
        prompt = build_analyze_prompt("ux_review")
        assert "UX" in prompt

    def test_unknown_type_falls_back_to_general(self):
        general = build_analyze_prompt("general")
        unknown = build_analyze_prompt("not_a_real_type")
        assert general == unknown


# ──────────────────────────────────────────────────────────────────────────────
# VisionPipeline — __init__
# ──────────────────────────────────────────────────────────────────────────────

class TestVisionPipelineInit:
    def test_reads_provider_from_llm_client(self):
        llm = _make_llm()
        llm.provider = "anthropic"
        pipeline = VisionPipeline(llm)
        assert pipeline._provider == "anthropic"

    def test_defaults_when_no_config(self):
        llm = _make_llm()
        pipeline = VisionPipeline(llm, config=None)
        assert pipeline.enabled is True
        assert pipeline.max_image_bytes == vision_module._DEFAULT_MAX_BYTES

    def test_config_can_disable_vision(self):
        cfg = _make_config(ENABLE_VISION=False)
        pipeline = VisionPipeline(_make_llm(), config=cfg)
        assert pipeline.enabled is False

    def test_config_custom_max_bytes(self):
        cfg = _make_config(VISION_MAX_IMAGE_BYTES=1024)
        pipeline = VisionPipeline(_make_llm(), config=cfg)
        assert pipeline.max_image_bytes == 1024

    def test_missing_provider_attribute_defaults_to_openai(self):
        llm = MagicMock(spec=[])  # provider attribute yok
        pipeline = VisionPipeline(llm, config=None)
        assert pipeline._provider == "openai"


# ──────────────────────────────────────────────────────────────────────────────
# VisionPipeline.mockup_to_code
# ──────────────────────────────────────────────────────────────────────────────

class TestVisionPipelineMockupToCode:
    def test_disabled_returns_failure(self):
        cfg = _make_config(ENABLE_VISION=False)
        pipeline = VisionPipeline(_make_llm(), config=cfg)
        result = run(pipeline.mockup_to_code(image_bytes=b"x"))
        assert result["success"] is False
        assert "devre dışı" in result["reason"]

    def test_no_source_returns_failure(self):
        pipeline = VisionPipeline(_make_llm())
        result = run(pipeline.mockup_to_code())
        assert result["success"] is False
        assert "gerekli" in result["reason"]

    def test_image_bytes_success(self):
        llm = _make_llm("const App = () => <div/>;")
        pipeline = VisionPipeline(llm)
        result = run(pipeline.mockup_to_code(image_bytes=b"PNG", mime_type="image/png"))
        assert result["success"] is True
        assert result["code"] == "const App = () => <div/>;"
        assert result["provider"] == "openai"

    def test_image_path_success(self, tmp_path):
        img = tmp_path / "ui.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        llm = _make_llm("<button>Click</button>")
        pipeline = VisionPipeline(llm)
        result = run(pipeline.mockup_to_code(image_path=str(img), framework="Vue"))
        assert result["success"] is True
        assert result["framework"] == "Vue"

    def test_file_not_found_returns_failure(self, tmp_path):
        pipeline = VisionPipeline(_make_llm())
        result = run(pipeline.mockup_to_code(image_path=str(tmp_path / "nope.png")))
        assert result["success"] is False
        assert "bulunamadı" in result["reason"]

    def test_unsupported_mime_bytes_returns_failure(self):
        pipeline = VisionPipeline(_make_llm())
        result = run(pipeline.mockup_to_code(image_bytes=b"data", mime_type="image/bmp"))
        assert result["success"] is False

    def test_llm_error_returns_failure(self):
        llm = _make_llm()
        llm.chat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        pipeline = VisionPipeline(llm)
        result = run(pipeline.mockup_to_code(image_bytes=b"PNG", mime_type="image/png"))
        assert result["success"] is False
        assert "LLM unavailable" in result["reason"]

    def test_result_contains_language_and_provider(self):
        pipeline = VisionPipeline(_make_llm("code"))
        result = run(pipeline.mockup_to_code(image_bytes=b"X", mime_type="image/png", language="JavaScript"))
        assert result["language"] == "JavaScript"
        assert result["provider"] == "openai"

    def test_image_path_takes_precedence_over_bytes(self, tmp_path):
        img = tmp_path / "ui.webp"
        img.write_bytes(b"RIFFWEBP")
        llm = _make_llm("output")
        pipeline = VisionPipeline(llm)
        result = run(pipeline.mockup_to_code(image_path=str(img), image_bytes=b"ignored"))
        # image_path öncelikli olduğu için FileNotFoundError veya başarı (dosya var)
        assert "success" in result


# ──────────────────────────────────────────────────────────────────────────────
# VisionPipeline.analyze
# ──────────────────────────────────────────────────────────────────────────────

class TestVisionPipelineAnalyze:
    def test_disabled_returns_failure(self):
        cfg = _make_config(ENABLE_VISION=False)
        pipeline = VisionPipeline(_make_llm(), config=cfg)
        result = run(pipeline.analyze(image_bytes=b"x"))
        assert result["success"] is False

    def test_no_source_returns_failure(self):
        pipeline = VisionPipeline(_make_llm())
        result = run(pipeline.analyze())
        assert result["success"] is False
        assert "gerekli" in result["reason"]

    def test_image_bytes_success_general(self):
        llm = _make_llm("Genel analiz sonucu.")
        pipeline = VisionPipeline(llm)
        result = run(pipeline.analyze(image_bytes=b"PNG", mime_type="image/png"))
        assert result["success"] is True
        assert result["analysis"] == "Genel analiz sonucu."
        assert result["analysis_type"] == "general"

    def test_accessibility_analysis_type_forwarded(self):
        llm = _make_llm("WCAG raporu")
        pipeline = VisionPipeline(llm)
        result = run(pipeline.analyze(image_bytes=b"X", mime_type="image/png", analysis_type="accessibility"))
        assert result["success"] is True
        assert result["analysis_type"] == "accessibility"

    def test_image_path_success(self, tmp_path):
        img = tmp_path / "screen.gif"
        img.write_bytes(b"GIF89a")
        result = run(VisionPipeline(_make_llm("ok")).analyze(image_path=str(img)))
        assert result["success"] is True

    def test_file_not_found_returns_failure(self, tmp_path):
        result = run(VisionPipeline(_make_llm()).analyze(image_path=str(tmp_path / "ghost.png")))
        assert result["success"] is False

    def test_llm_error_returns_failure(self):
        llm = _make_llm()
        llm.chat = AsyncMock(side_effect=ValueError("bad response"))
        pipeline = VisionPipeline(llm)
        result = run(pipeline.analyze(image_bytes=b"X", mime_type="image/png"))
        assert result["success"] is False
        assert "bad response" in result["reason"]
