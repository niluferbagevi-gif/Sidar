"""core/vision.py için unit testler."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.vision import (
    _DEFAULT_MAX_BYTES,
    SUPPORTED_MIME_TYPES,
    VisionPipeline,
    build_analyze_prompt,
    build_mockup_prompt,
    build_vision_messages,
    load_image_as_base64,
    load_image_from_bytes,
)

# ──────────────────────────────────────────────────────────────────────────────
# load_image_from_bytes
# ──────────────────────────────────────────────────────────────────────────────


def test_load_image_from_bytes_valid():
    data = b"\x89PNG\r\n"
    b64, mime = load_image_from_bytes(data, "image/png")
    assert mime == "image/png"
    assert base64.b64decode(b64) == data


def test_load_image_from_bytes_jpeg():
    data = b"\xff\xd8\xff"
    b64, mime = load_image_from_bytes(data, "image/jpeg")
    assert mime == "image/jpeg"


def test_load_image_from_bytes_unsupported_mime():
    with pytest.raises(ValueError, match="Desteklenmeyen MIME"):
        load_image_from_bytes(b"data", "application/pdf")


def test_load_image_from_bytes_too_large():
    huge = b"x" * (_DEFAULT_MAX_BYTES + 1)
    with pytest.raises(ValueError, match="Görsel çok büyük"):
        load_image_from_bytes(huge, "image/png")


# ──────────────────────────────────────────────────────────────────────────────
# load_image_as_base64 (async)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_image_as_base64_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        await load_image_as_base64(tmp_path / "missing.png")


@pytest.mark.asyncio
async def test_load_image_as_base64_unsupported_format(tmp_path):
    f = tmp_path / "file.bmp"
    f.write_bytes(b"BM data")
    with pytest.raises(ValueError, match="Desteklenmeyen"):
        await load_image_as_base64(f)


@pytest.mark.asyncio
async def test_load_image_as_base64_too_large(tmp_path):
    f = tmp_path / "big.png"
    f.write_bytes(b"x" * (_DEFAULT_MAX_BYTES + 1))
    with pytest.raises(ValueError, match="Görsel çok büyük"):
        await load_image_as_base64(f)


@pytest.mark.asyncio
async def test_load_image_as_base64_success(tmp_path):
    f = tmp_path / "img.png"
    raw = b"\x89PNG\r\n"
    f.write_bytes(raw)
    b64, mime = await load_image_as_base64(f)
    assert mime == "image/png"
    assert base64.b64decode(b64) == raw


# ──────────────────────────────────────────────────────────────────────────────
# build_vision_messages
# ──────────────────────────────────────────────────────────────────────────────


def _b64():
    return base64.b64encode(b"img").decode()


def test_build_vision_messages_openai():
    msgs = build_vision_messages("openai", "prompt", _b64(), "image/png")
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert any(p.get("type") == "text" for p in content)
    assert any(p.get("type") == "image_url" for p in content)


def test_build_vision_messages_litellm():
    msgs = build_vision_messages("litellm", "p", _b64(), "image/png")
    assert msgs[0]["role"] == "user"
    assert any(p.get("type") == "image_url" for p in msgs[0]["content"])


def test_build_vision_messages_anthropic():
    msgs = build_vision_messages("anthropic", "prompt", _b64(), "image/webp")
    content = msgs[0]["content"]
    img_block = next(p for p in content if p.get("type") == "image")
    assert img_block["source"]["type"] == "base64"
    assert img_block["source"]["media_type"] == "image/webp"


def test_build_vision_messages_gemini():
    msgs = build_vision_messages("gemini", "prompt", _b64(), "image/jpeg")
    content = msgs[0]["content"]
    inline = next(p for p in content if "inline_data" in p)
    assert inline["inline_data"]["mime_type"] == "image/jpeg"


def test_build_vision_messages_ollama_default():
    msgs = build_vision_messages("ollama", "prompt", _b64(), "image/png")
    assert msgs[0]["role"] == "user"
    assert _b64() in msgs[0]["images"]


def test_build_vision_messages_unknown_provider_fallback():
    msgs = build_vision_messages("unknown_xyz", "prompt", _b64(), "image/png")
    # Bilinmeyen provider ollama formatına düşer
    assert "images" in msgs[0]


def test_build_vision_messages_case_insensitive():
    msgs_upper = build_vision_messages("OpenAI", "p", _b64(), "image/png")
    msgs_lower = build_vision_messages("openai", "p", _b64(), "image/png")
    assert msgs_upper == msgs_lower


# ──────────────────────────────────────────────────────────────────────────────
# build_mockup_prompt
# ──────────────────────────────────────────────────────────────────────────────


def test_build_mockup_prompt_defaults():
    prompt = build_mockup_prompt()
    assert "React" in prompt
    assert "Tailwind CSS" in prompt
    assert "TypeScript" in prompt


def test_build_mockup_prompt_custom():
    prompt = build_mockup_prompt(framework="Vue", css_framework="Bootstrap", language="JavaScript")
    assert "Vue" in prompt
    assert "Bootstrap" in prompt
    assert "JavaScript" in prompt


def test_build_mockup_prompt_extra_instructions():
    prompt = build_mockup_prompt(extra_instructions="Dark mode zorunlu")
    assert "Dark mode zorunlu" in prompt


def test_build_mockup_prompt_empty_strings_use_defaults():
    prompt = build_mockup_prompt(framework="", css_framework="", language="")
    assert "React" in prompt
    assert "Tailwind CSS" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# build_analyze_prompt
# ──────────────────────────────────────────────────────────────────────────────


def test_build_analyze_prompt_general():
    p = build_analyze_prompt("general")
    assert "analiz" in p.lower()


def test_build_analyze_prompt_accessibility():
    p = build_analyze_prompt("accessibility")
    assert "WCAG" in p or "erişilebilirlik" in p.lower()


def test_build_analyze_prompt_ux_review():
    p = build_analyze_prompt("ux_review")
    assert "UX" in p or "kullanıcı" in p.lower()


def test_build_analyze_prompt_unknown_falls_back_to_general():
    p_unknown = build_analyze_prompt("nonexistent_type")
    p_general = build_analyze_prompt("general")
    assert p_unknown == p_general


# ──────────────────────────────────────────────────────────────────────────────
# VisionPipeline
# ──────────────────────────────────────────────────────────────────────────────


def _make_pipeline(provider="openai", enabled=True):
    llm = AsyncMock()
    llm.provider = provider
    llm.chat = AsyncMock(return_value="<button>Click</button>")
    cfg = MagicMock()
    cfg.ENABLE_VISION = enabled
    cfg.VISION_MAX_IMAGE_BYTES = _DEFAULT_MAX_BYTES
    return VisionPipeline(llm, cfg), llm


@pytest.mark.asyncio
async def test_pipeline_disabled_returns_error():
    pipeline, _ = _make_pipeline(enabled=False)
    result = await pipeline.mockup_to_code(image_bytes=b"x", mime_type="image/png")
    assert result["success"] is False
    assert "devre dışı" in result["reason"]


@pytest.mark.asyncio
async def test_pipeline_no_input_returns_error():
    pipeline, _ = _make_pipeline()
    result = await pipeline.mockup_to_code()
    assert result["success"] is False
    assert "gerekli" in result["reason"]


@pytest.mark.asyncio
async def test_pipeline_mockup_to_code_from_bytes():
    pipeline, llm = _make_pipeline()
    raw = b"\x89PNG\r\n"
    result = await pipeline.mockup_to_code(image_bytes=raw, mime_type="image/png")
    assert result["success"] is True
    assert result["code"] == "<button>Click</button>"
    assert result["framework"] == "React"
    llm.chat.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_mockup_to_code_from_path(tmp_path):
    pipeline, llm = _make_pipeline()
    f = tmp_path / "ui.png"
    f.write_bytes(b"\x89PNG\r\n")
    result = await pipeline.mockup_to_code(image_path=str(f), framework="Vue")
    assert result["success"] is True
    assert result["framework"] == "Vue"


@pytest.mark.asyncio
async def test_pipeline_mockup_to_code_file_not_found():
    pipeline, _ = _make_pipeline()
    result = await pipeline.mockup_to_code(image_path="/nonexistent/ui.png")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_pipeline_mockup_to_code_llm_error():
    pipeline, llm = _make_pipeline()
    llm.chat.side_effect = RuntimeError("LLM quota exceeded")
    raw = b"\x89PNG\r\n"
    result = await pipeline.mockup_to_code(image_bytes=raw, mime_type="image/png")
    assert result["success"] is False
    assert "LLM quota" in result["reason"]


@pytest.mark.asyncio
async def test_pipeline_analyze_from_bytes():
    pipeline, llm = _make_pipeline()
    llm.chat.return_value = "Bu bir analiz."
    raw = b"\x89PNG\r\n"
    result = await pipeline.analyze(image_bytes=raw, mime_type="image/png", analysis_type="general")
    assert result["success"] is True
    assert result["analysis"] == "Bu bir analiz."
    assert result["analysis_type"] == "general"


@pytest.mark.asyncio
async def test_pipeline_analyze_from_path(tmp_path):
    pipeline, llm = _make_pipeline()
    llm.chat.return_value = "Path üzerinden analiz."
    f = tmp_path / "screen.png"
    f.write_bytes(b"\x89PNG\r\n")
    result = await pipeline.analyze(image_path=str(f), analysis_type="ux_review")
    assert result["success"] is True
    assert result["analysis"] == "Path üzerinden analiz."
    assert result["analysis_type"] == "ux_review"


@pytest.mark.asyncio
async def test_pipeline_analyze_disabled():
    pipeline, _ = _make_pipeline(enabled=False)
    result = await pipeline.analyze(image_bytes=b"x", mime_type="image/png")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_pipeline_analyze_no_input():
    pipeline, _ = _make_pipeline()
    result = await pipeline.analyze()
    assert result["success"] is False
    assert "gerekli" in result["reason"]


@pytest.mark.asyncio
async def test_pipeline_analyze_file_not_found():
    pipeline, _ = _make_pipeline()
    result = await pipeline.analyze(image_path="/nonexistent/analysis.png")
    assert result["success"] is False
    assert "bulunamadı" in result["reason"].lower()


@pytest.mark.asyncio
async def test_pipeline_analyze_llm_error():
    pipeline, llm = _make_pipeline()
    llm.chat.side_effect = Exception("timeout")
    result = await pipeline.analyze(image_bytes=b"\x89PNG\r\n", mime_type="image/png")
    assert result["success"] is False
    assert "timeout" in result["reason"]


def test_pipeline_provider_from_llm():
    pipeline, _ = _make_pipeline(provider="anthropic")
    assert pipeline._provider == "anthropic"


def test_supported_mime_types_constant():
    assert "image/png" in SUPPORTED_MIME_TYPES
    assert "image/jpeg" in SUPPORTED_MIME_TYPES
    assert "image/webp" in SUPPORTED_MIME_TYPES
    assert "image/gif" in SUPPORTED_MIME_TYPES
