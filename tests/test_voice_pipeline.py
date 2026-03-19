import asyncio
from types import SimpleNamespace

import core.voice as voice_mod
from core.voice import VoicePipeline


class _Cfg:
    VOICE_TTS_PROVIDER = "mock"
    VOICE_TTS_VOICE = ""
    VOICE_TTS_SEGMENT_CHARS = 12


def test_voice_pipeline_mock_synthesizes_audio_bytes():
    pipeline = VoicePipeline(_Cfg())
    result = asyncio.run(pipeline.synthesize_text("Merhaba dünya"))

    assert pipeline.enabled is True
    assert result["success"] is True
    assert result["mime_type"] == "audio/mock"
    assert result["audio_bytes"] == "Merhaba dünya".encode("utf-8")


def test_voice_pipeline_extracts_ready_segments_on_punctuation_and_flush():
    pipeline = VoicePipeline(_Cfg())

    ready, remainder = pipeline.extract_ready_segments("İlk cümle. İkinci", flush=False)
    assert ready == ["İlk cümle."]
    assert remainder == "İkinci"

    flushed, remainder_after_flush = pipeline.extract_ready_segments(remainder, flush=True)
    assert flushed == ["İkinci"]
    assert remainder_after_flush == ""


def test_voice_pipeline_enforces_minimum_segment_chars_and_flushes_long_buffers():
    cfg = SimpleNamespace(VOICE_TTS_PROVIDER="mock", VOICE_TTS_VOICE="tr-TR", VOICE_TTS_SEGMENT_CHARS=1)
    pipeline = VoicePipeline(cfg)

    assert pipeline.segment_chars == 20

    ready, remainder = pipeline.extract_ready_segments("x" * 20, flush=False)
    assert ready == ["x" * 20]
    assert remainder == ""


def test_voice_pipeline_returns_failure_for_blank_text():
    pipeline = VoicePipeline(_Cfg())

    result = asyncio.run(pipeline.synthesize_text("   "))

    assert result == {
        "success": False,
        "audio_bytes": b"",
        "mime_type": "audio/mock",
        "provider": "mock",
        "voice": "",
        "reason": "Boş metin için TTS üretilmedi.",
    }


def test_build_tts_adapter_auto_falls_back_to_mock(monkeypatch):
    class _UnavailableAdapter:
        provider = "pyttsx3"

        def __init__(self):
            self._import_error = "missing dependency"

        @property
        def available(self):
            return False

    monkeypatch.setattr(voice_mod, "_Pyttsx3Adapter", _UnavailableAdapter)

    adapter = voice_mod._build_tts_adapter("auto")

    assert isinstance(adapter, voice_mod._MockTTSAdapter)


def test_pyttsx3_adapter_reports_import_failure(monkeypatch):
    monkeypatch.setattr(voice_mod, "_Pyttsx3Adapter", voice_mod._Pyttsx3Adapter)
    adapter = voice_mod._Pyttsx3Adapter()
    monkeypatch.setattr(adapter, "_import_error", "pyttsx3 missing")

    result = asyncio.run(adapter.synthesize("Merhaba", voice="tr"))

    assert result["success"] is False
    assert result["provider"] == "pyttsx3"
    assert result["reason"] == "pyttsx3 missing"


def test_voice_pipeline_builds_vad_state_and_auto_commit_signal():
    cfg = SimpleNamespace(
        VOICE_TTS_PROVIDER="mock",
        VOICE_TTS_VOICE="",
        VOICE_TTS_SEGMENT_CHARS=24,
        VOICE_VAD_ENABLED=True,
        VOICE_VAD_MIN_SPEECH_BYTES=512,
        VOICE_DUPLEX_ENABLED=True,
        VOICE_VAD_INTERRUPT_MIN_BYTES=256,
    )
    pipeline = VoicePipeline(cfg)

    payload = pipeline.build_voice_state_payload(event="speech_end", buffered_bytes=1024, sequence=3)

    assert payload["voice_state"] == "speech_end"
    assert payload["buffered_bytes"] == 1024
    assert payload["sequence"] == 3
    assert payload["vad_enabled"] is True
    assert payload["auto_commit_ready"] is True
    assert payload["duplex_enabled"] is True
    assert payload["interrupt_ready"] is False
    assert pipeline.should_commit_audio(1024, event="speech_end") is True
    assert pipeline.should_commit_audio(128, event="speech_end") is False


def test_voice_pipeline_detects_barge_in_interrupt_signal():
    cfg = SimpleNamespace(
        VOICE_TTS_PROVIDER="mock",
        VOICE_TTS_VOICE="",
        VOICE_VAD_ENABLED=True,
        VOICE_DUPLEX_ENABLED=True,
        VOICE_VAD_INTERRUPT_MIN_BYTES=300,
    )
    pipeline = VoicePipeline(cfg)

    payload = pipeline.build_voice_state_payload(event="speech_start", buffered_bytes=384, sequence=4)

    assert payload["voice_state"] == "speech_start"
    assert payload["interrupt_ready"] is True
    assert pipeline.should_interrupt_response(384, event="speech_start") is True
    assert pipeline.should_interrupt_response(128, event="speech_start") is False
