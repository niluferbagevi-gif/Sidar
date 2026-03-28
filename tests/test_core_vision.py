"""
core/vision.py için birim testleri.
load_image_from_bytes, build_vision_messages, build_mockup_prompt,
build_analyze_prompt ve VisionPipeline (disabled path) testlerini kapsar.
"""
from __future__ import annotations

import asyncio
import base64
import sys
import tempfile
from pathlib import Path


def _get_vision():
    if "core.vision" in sys.modules:
        del sys.modules["core.vision"]
    import core.vision as vision
    return vision


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════
# load_image_from_bytes
# ══════════════════════════════════════════════════════════════

class TestLoadImageFromBytes:
    def test_valid_png_returns_base64_and_mime(self):
        vision = _get_vision()
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        b64, mime = vision.load_image_from_bytes(data, "image/png")
        assert base64.b64decode(b64) == data
        assert mime == "image/png"

    def test_valid_jpeg_accepted(self):
        vision = _get_vision()
        data = b"\xff\xd8\xff" + b"\x00" * 50
        b64, mime = vision.load_image_from_bytes(data, "image/jpeg")
        assert mime == "image/jpeg"

    def test_valid_webp_accepted(self):
        vision = _get_vision()
        data = b"RIFF....WEBP" + b"\x00" * 50
        b64, mime = vision.load_image_from_bytes(data, "image/webp")
        assert mime == "image/webp"

    def test_invalid_mime_raises_value_error(self):
        vision = _get_vision()
        import pytest
        with pytest.raises(ValueError, match="Desteklenmeyen"):
            vision.load_image_from_bytes(b"\x00" * 10, "image/bmp")

    def test_oversized_raises_value_error(self):
        vision = _get_vision()
        import pytest
        with pytest.raises(ValueError, match="büyük"):
            vision.load_image_from_bytes(b"\x00" * (11 * 1024 * 1024), "image/png")

    def test_empty_bytes_encodes_to_empty_base64(self):
        vision = _get_vision()
        b64, _ = vision.load_image_from_bytes(b"", "image/png")
        assert b64 == ""


# ══════════════════════════════════════════════════════════════
# load_image_as_base64
# ══════════════════════════════════════════════════════════════

class TestLoadImageAsBase64:
    def test_file_not_found_raises(self):
        vision = _get_vision()
        import pytest
        with pytest.raises(FileNotFoundError):
            _run(vision.load_image_as_base64("/nonexistent/image.png"))

    def test_unsupported_extension_raises(self):
        vision = _get_vision()
        import pytest
        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            f.write(b"BM" + b"\x00" * 50)
            path = f.name
        with pytest.raises(ValueError):
            _run(vision.load_image_as_base64(path))

    def test_valid_png_file_returns_base64(self):
        vision = _get_vision()
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_data)
            path = f.name
        b64, mime = _run(vision.load_image_as_base64(path))
        assert base64.b64decode(b64) == png_data
        assert mime == "image/png"


# ══════════════════════════════════════════════════════════════
# build_vision_messages
# ══════════════════════════════════════════════════════════════

class TestBuildVisionMessages:
    def test_openai_format(self):
        vision = _get_vision()
        msgs = vision.build_vision_messages("openai", "Describe this", "base64data", "image/png")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        content = msgs[0]["content"]
        assert any(item.get("type") == "text" for item in content)
        assert any(item.get("type") == "image_url" for item in content)

    def test_openai_image_url_contains_mime(self):
        vision = _get_vision()
        msgs = vision.build_vision_messages("openai", "Prompt", "b64", "image/jpeg")
        image_url = next(item for item in msgs[0]["content"] if item.get("type") == "image_url")
        assert "image/jpeg" in image_url["image_url"]["url"]

    def test_litellm_same_as_openai(self):
        vision = _get_vision()
        msgs_openai = vision.build_vision_messages("openai", "P", "b64", "image/png")
        msgs_litellm = vision.build_vision_messages("litellm", "P", "b64", "image/png")
        assert msgs_openai[0]["role"] == msgs_litellm[0]["role"]
        assert len(msgs_openai[0]["content"]) == len(msgs_litellm[0]["content"])

    def test_anthropic_format(self):
        vision = _get_vision()
        msgs = vision.build_vision_messages("anthropic", "Describe", "b64data", "image/png")
        assert len(msgs) == 1
        content = msgs[0]["content"]
        image_item = next(item for item in content if item.get("type") == "image")
        assert image_item["source"]["data"] == "b64data"
        assert image_item["source"]["media_type"] == "image/png"

    def test_gemini_format(self):
        vision = _get_vision()
        msgs = vision.build_vision_messages("gemini", "Describe", "b64data", "image/webp")
        assert len(msgs) == 1
        content = msgs[0]["content"]
        inline = next(item for item in content if "inline_data" in item)
        assert inline["inline_data"]["data"] == "b64data"
        assert inline["inline_data"]["mime_type"] == "image/webp"

    def test_ollama_format(self):
        vision = _get_vision()
        msgs = vision.build_vision_messages("ollama", "Describe", "b64data", "image/png")
        assert len(msgs) == 1
        msg = msgs[0]
        assert msg["role"] == "user"
        assert "images" in msg
        assert msg["images"] == ["b64data"]

    def test_unknown_provider_falls_back_to_ollama_format(self):
        vision = _get_vision()
        msgs = vision.build_vision_messages("unknown_provider", "Prompt", "b64", "image/png")
        assert "images" in msgs[0]

    def test_case_insensitive_provider(self):
        vision = _get_vision()
        msgs_upper = vision.build_vision_messages("OPENAI", "P", "b64", "image/png")
        msgs_lower = vision.build_vision_messages("openai", "P", "b64", "image/png")
        assert len(msgs_upper[0]["content"]) == len(msgs_lower[0]["content"])


# ══════════════════════════════════════════════════════════════
# build_mockup_prompt
# ══════════════════════════════════════════════════════════════

class TestBuildMockupPrompt:
    def test_default_framework_react(self):
        vision = _get_vision()
        prompt = vision.build_mockup_prompt()
        assert "React" in prompt

    def test_custom_framework(self):
        vision = _get_vision()
        prompt = vision.build_mockup_prompt(framework="Vue")
        assert "Vue" in prompt

    def test_css_framework_included(self):
        vision = _get_vision()
        prompt = vision.build_mockup_prompt(css_framework="Bootstrap")
        assert "Bootstrap" in prompt

    def test_language_included(self):
        vision = _get_vision()
        prompt = vision.build_mockup_prompt(language="JavaScript")
        assert "JavaScript" in prompt

    def test_extra_instructions_included(self):
        vision = _get_vision()
        prompt = vision.build_mockup_prompt(extra_instructions="dark mode")
        assert "dark mode" in prompt

    def test_empty_extra_instructions_no_trailing_text(self):
        vision = _get_vision()
        prompt = vision.build_mockup_prompt(extra_instructions="")
        assert "Ek talimatlar" not in prompt

    def test_none_framework_falls_back_to_react(self):
        vision = _get_vision()
        prompt = vision.build_mockup_prompt(framework=None)
        assert "React" in prompt

    def test_returns_string(self):
        vision = _get_vision()
        assert isinstance(vision.build_mockup_prompt(), str)


# ══════════════════════════════════════════════════════════════
# build_analyze_prompt
# ══════════════════════════════════════════════════════════════

class TestBuildAnalyzePrompt:
    def test_general_prompt_returned(self):
        vision = _get_vision()
        prompt = vision.build_analyze_prompt("general")
        assert isinstance(prompt, str)
        assert len(prompt) > 10

    def test_accessibility_prompt(self):
        vision = _get_vision()
        prompt = vision.build_analyze_prompt("accessibility")
        assert "WCAG" in prompt or "erişilebilirlik" in prompt.lower()

    def test_ux_review_prompt(self):
        vision = _get_vision()
        prompt = vision.build_analyze_prompt("ux_review")
        assert "UX" in prompt or "kullanılabilirlik" in prompt.lower()

    def test_unknown_type_falls_back_to_general(self):
        vision = _get_vision()
        prompt_unknown = vision.build_analyze_prompt("nonexistent_type")
        prompt_general = vision.build_analyze_prompt("general")
        assert prompt_unknown == prompt_general


# ══════════════════════════════════════════════════════════════
# VisionPipeline
# ══════════════════════════════════════════════════════════════

def _make_config(**kwargs):
    class _Cfg:
        ENABLE_VISION = True
        VISION_MAX_IMAGE_BYTES = 10 * 1024 * 1024

    for k, v in kwargs.items():
        setattr(_Cfg, k, v)
    return _Cfg()


class TestVisionPipelineInit:
    def test_enabled_true_by_default(self):
        vision = _get_vision()
        mock_client = type("C", (), {"provider": "openai"})()
        vp = vision.VisionPipeline(mock_client, _make_config())
        assert vp.enabled is True

    def test_enabled_false_when_config_disabled(self):
        vision = _get_vision()
        mock_client = type("C", (), {"provider": "openai"})()
        vp = vision.VisionPipeline(mock_client, _make_config(ENABLE_VISION=False))
        assert vp.enabled is False

    def test_provider_from_llm_client(self):
        vision = _get_vision()
        mock_client = type("C", (), {"provider": "anthropic"})()
        vp = vision.VisionPipeline(mock_client, _make_config())
        assert vp._provider == "anthropic"

    def test_none_config_defaults(self):
        vision = _get_vision()
        mock_client = type("C", (), {"provider": "openai"})()
        vp = vision.VisionPipeline(mock_client, None)
        assert vp.enabled is True


class TestVisionPipelineDisabled:
    def test_mockup_to_code_returns_failure_when_disabled(self):
        vision = _get_vision()
        mock_client = type("C", (), {"provider": "openai"})()
        vp = vision.VisionPipeline(mock_client, _make_config(ENABLE_VISION=False))
        result = _run(vp.mockup_to_code(image_bytes=b"\x89PNG" + b"\x00" * 50))
        assert result["success"] is False
