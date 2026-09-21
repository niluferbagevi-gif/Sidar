"""Multimodal vision/voice/STT-TTS settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_int_env


@dataclass(frozen=True)
class MultimodalSettings:
    """Vision, video/audio ingest and voice pipeline feature-flag/limit settings."""

    enable_vision: bool
    vision_max_image_bytes: int
    enable_multimodal: bool
    multimodal_max_file_bytes: int
    voice_stt_provider: str
    voice_tts_provider: str
    voice_tts_voice: str
    voice_tts_segment_chars: int
    voice_tts_buffer_chars: int
    voice_vad_enabled: bool
    voice_vad_min_speech_bytes: int
    voice_duplex_enabled: bool
    voice_vad_interrupt_min_bytes: int
    whisper_model: str
    voice_ws_max_bytes: int


def load_multimodal_settings() -> MultimodalSettings:
    """Load multimodal vision/voice/STT-TTS settings from environment variables."""
    return MultimodalSettings(
        enable_vision=get_bool_env("ENABLE_VISION", True),
        vision_max_image_bytes=get_int_env("VISION_MAX_IMAGE_BYTES", 10485760),
        enable_multimodal=get_bool_env("ENABLE_MULTIMODAL", True),
        multimodal_max_file_bytes=get_int_env("MULTIMODAL_MAX_FILE_BYTES", 52428800),
        voice_stt_provider=os.getenv("VOICE_STT_PROVIDER", "whisper"),
        voice_tts_provider=os.getenv("VOICE_TTS_PROVIDER", "auto"),
        voice_tts_voice=os.getenv("VOICE_TTS_VOICE", ""),
        voice_tts_segment_chars=get_int_env("VOICE_TTS_SEGMENT_CHARS", 48),
        voice_tts_buffer_chars=get_int_env("VOICE_TTS_BUFFER_CHARS", 96),
        voice_vad_enabled=get_bool_env("VOICE_VAD_ENABLED", True),
        voice_vad_min_speech_bytes=get_int_env("VOICE_VAD_MIN_SPEECH_BYTES", 1024),
        voice_duplex_enabled=get_bool_env("VOICE_DUPLEX_ENABLED", True),
        voice_vad_interrupt_min_bytes=get_int_env("VOICE_VAD_INTERRUPT_MIN_BYTES", 384),
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        voice_ws_max_bytes=get_int_env("VOICE_WS_MAX_BYTES", 10485760),
    )
