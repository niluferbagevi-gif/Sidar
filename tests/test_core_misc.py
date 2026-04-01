from __future__ import annotations

import pytest

from core.dlp import DLPEngine
from core.multimodal import detect_media_kind, extract_youtube_video_id
from core.vision import build_mockup_prompt, load_image_from_bytes


def test_dlp_masks_password_email_and_valid_tckn():
    engine = DLPEngine(mask_long_hex=True)
    text = "email: test@example.com password=secret123 tckn=10000000146"

    masked, detections = engine.mask(text)

    assert "test@example.com" not in masked
    assert "secret123" not in masked
    assert "10000000146" not in masked
    names = {d.pattern_name for d in detections}
    assert {"email", "password", "tckn"}.issubset(names)


def test_multimodal_helpers_detect_kind_and_youtube_id():
    assert detect_media_kind(mime_type="video/mp4") == "video"
    assert detect_media_kind(path="voice.wav") == "audio"
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_vision_helpers_validate_mime_and_prompt_content():
    b64, mime = load_image_from_bytes(b"abc", mime_type="image/png")
    assert b64
    assert mime == "image/png"

    prompt = build_mockup_prompt(framework="React", css_framework="Tailwind", language="TypeScript")
    assert "React" in prompt
    assert "Tailwind" in prompt

    with pytest.raises(ValueError):
        load_image_from_bytes(b"abc", mime_type="application/pdf")
