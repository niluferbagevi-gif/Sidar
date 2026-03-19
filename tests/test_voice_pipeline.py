import asyncio

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