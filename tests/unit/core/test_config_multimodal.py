"""Tests for multimodal vision/voice/STT-TTS settings resolution."""

from core.config_multimodal import load_multimodal_settings

_ALL_KEYS = (
    "ENABLE_VISION",
    "VISION_MAX_IMAGE_BYTES",
    "ENABLE_MULTIMODAL",
    "MULTIMODAL_MAX_FILE_BYTES",
    "VOICE_STT_PROVIDER",
    "VOICE_TTS_PROVIDER",
    "VOICE_TTS_VOICE",
    "VOICE_TTS_SEGMENT_CHARS",
    "VOICE_TTS_BUFFER_CHARS",
    "VOICE_VAD_ENABLED",
    "VOICE_VAD_MIN_SPEECH_BYTES",
    "VOICE_DUPLEX_ENABLED",
    "VOICE_VAD_INTERRUPT_MIN_BYTES",
    "WHISPER_MODEL",
    "VOICE_WS_MAX_BYTES",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_multimodal_settings()

    assert settings.enable_vision is True
    assert settings.vision_max_image_bytes == 10485760
    assert settings.enable_multimodal is True
    assert settings.multimodal_max_file_bytes == 52428800
    assert settings.voice_stt_provider == "whisper"
    assert settings.voice_tts_provider == "auto"
    assert settings.voice_tts_voice == ""
    assert settings.voice_tts_segment_chars == 48
    assert settings.voice_tts_buffer_chars == 96
    assert settings.voice_vad_enabled is True
    assert settings.voice_vad_min_speech_bytes == 1024
    assert settings.voice_duplex_enabled is True
    assert settings.voice_vad_interrupt_min_bytes == 384
    assert settings.whisper_model == "base"
    assert settings.voice_ws_max_bytes == 10485760


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("ENABLE_VISION", "false")
    monkeypatch.setenv("VISION_MAX_IMAGE_BYTES", "2000000")
    monkeypatch.setenv("ENABLE_MULTIMODAL", "false")
    monkeypatch.setenv("MULTIMODAL_MAX_FILE_BYTES", "1000000")
    monkeypatch.setenv("VOICE_STT_PROVIDER", "custom-stt")
    monkeypatch.setenv("VOICE_TTS_PROVIDER", "pyttsx3")
    monkeypatch.setenv("VOICE_TTS_VOICE", "tr-TR-female")
    monkeypatch.setenv("VOICE_TTS_SEGMENT_CHARS", "64")
    monkeypatch.setenv("VOICE_TTS_BUFFER_CHARS", "128")
    monkeypatch.setenv("VOICE_VAD_ENABLED", "false")
    monkeypatch.setenv("VOICE_VAD_MIN_SPEECH_BYTES", "2048")
    monkeypatch.setenv("VOICE_DUPLEX_ENABLED", "false")
    monkeypatch.setenv("VOICE_VAD_INTERRUPT_MIN_BYTES", "512")
    monkeypatch.setenv("WHISPER_MODEL", "large-v3")
    monkeypatch.setenv("VOICE_WS_MAX_BYTES", "5242880")

    settings = load_multimodal_settings()

    assert settings.enable_vision is False
    assert settings.vision_max_image_bytes == 2000000
    assert settings.enable_multimodal is False
    assert settings.multimodal_max_file_bytes == 1000000
    assert settings.voice_stt_provider == "custom-stt"
    assert settings.voice_tts_provider == "pyttsx3"
    assert settings.voice_tts_voice == "tr-TR-female"
    assert settings.voice_tts_segment_chars == 64
    assert settings.voice_tts_buffer_chars == 128
    assert settings.voice_vad_enabled is False
    assert settings.voice_vad_min_speech_bytes == 2048
    assert settings.voice_duplex_enabled is False
    assert settings.voice_vad_interrupt_min_bytes == 512
    assert settings.whisper_model == "large-v3"
    assert settings.voice_ws_max_bytes == 5242880


def test_malformed_integer_envs_fall_back_to_defaults(monkeypatch):
    """Non-integer byte-limit/char-count env values fall back to their defaults."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("VISION_MAX_IMAGE_BYTES", "not-an-int")
    monkeypatch.setenv("MULTIMODAL_MAX_FILE_BYTES", "not-an-int")
    monkeypatch.setenv("VOICE_TTS_SEGMENT_CHARS", "not-an-int")
    monkeypatch.setenv("VOICE_TTS_BUFFER_CHARS", "not-an-int")
    monkeypatch.setenv("VOICE_VAD_MIN_SPEECH_BYTES", "not-an-int")
    monkeypatch.setenv("VOICE_VAD_INTERRUPT_MIN_BYTES", "not-an-int")
    monkeypatch.setenv("VOICE_WS_MAX_BYTES", "not-an-int")

    settings = load_multimodal_settings()

    assert settings.vision_max_image_bytes == 10485760
    assert settings.multimodal_max_file_bytes == 52428800
    assert settings.voice_tts_segment_chars == 48
    assert settings.voice_tts_buffer_chars == 96
    assert settings.voice_vad_min_speech_bytes == 1024
    assert settings.voice_vad_interrupt_min_bytes == 384
    assert settings.voice_ws_max_bytes == 10485760
