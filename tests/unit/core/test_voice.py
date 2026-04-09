"""core/voice.py için unit testler."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from core.voice import (
    VoicePipeline,
    _BaseTTSAdapter,
    _MockTTSAdapter,
    _Pyttsx3Adapter,
    _build_tts_adapter,
)


# ──────────────────────────────────────────────────────────────────────────────
# _MockTTSAdapter
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_adapter_synthesize_success():
    adapter = _MockTTSAdapter()
    result = await adapter.synthesize("Merhaba")
    assert result["success"] is True
    assert result["audio_bytes"] == b"Merhaba"
    assert result["mime_type"] == "audio/mock"
    assert result["provider"] == "mock"


@pytest.mark.asyncio
async def test_mock_adapter_synthesize_empty_text():
    adapter = _MockTTSAdapter()
    result = await adapter.synthesize("")
    assert result["success"] is False
    assert b"" == result["audio_bytes"]
    assert "Boş metin" in result["reason"]


@pytest.mark.asyncio
async def test_mock_adapter_synthesize_with_voice():
    adapter = _MockTTSAdapter()
    result = await adapter.synthesize("test", voice="tr-TR")
    assert result["voice"] == "tr-TR"


def test_mock_adapter_available():
    assert _MockTTSAdapter().available is True


# ──────────────────────────────────────────────────────────────────────────────
# _Pyttsx3Adapter (pyttsx3 yokken)
# ──────────────────────────────────────────────────────────────────────────────

def test_pyttsx3_adapter_not_available_when_import_fails(monkeypatch):
    # pyttsx3'ü import edilemez hale getir
    if "pyttsx3" not in sys.modules:
        sys.modules["pyttsx3"] = types.ModuleType("pyttsx3")
    real = sys.modules.pop("pyttsx3", None)
    monkeypatch.setitem(sys.modules, "pyttsx3", None)
    try:
        adapter = _Pyttsx3Adapter()
        assert adapter.available is False
    finally:
        if real is not None:
            sys.modules["pyttsx3"] = real
        else:
            sys.modules.pop("pyttsx3", None)


@pytest.mark.asyncio
async def test_pyttsx3_adapter_synthesize_when_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyttsx3", None)
    adapter = _Pyttsx3Adapter()
    result = await adapter.synthesize("test")
    assert result["success"] is False
    assert result["provider"] == "pyttsx3"


# ──────────────────────────────────────────────────────────────────────────────
# _build_tts_adapter
# ──────────────────────────────────────────────────────────────────────────────

def test_build_tts_adapter_mock():
    adapter = _build_tts_adapter("mock")
    assert isinstance(adapter, _MockTTSAdapter)


def test_build_tts_adapter_pyttsx3():
    adapter = _build_tts_adapter("pyttsx3")
    assert isinstance(adapter, _Pyttsx3Adapter)


def test_build_tts_adapter_auto_falls_back_to_mock(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyttsx3", None)
    adapter = _build_tts_adapter("auto")
    # pyttsx3 yoksa mock'a düşmeli
    assert isinstance(adapter, _MockTTSAdapter)


def test_build_tts_adapter_empty_string_treated_as_auto(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyttsx3", None)
    adapter = _build_tts_adapter("")
    assert isinstance(adapter, _MockTTSAdapter)


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline — başlatma
# ──────────────────────────────────────────────────────────────────────────────

def _make_pipeline(**cfg_attrs):
    cfg = MagicMock()
    cfg.VOICE_TTS_PROVIDER = cfg_attrs.get("provider", "mock")
    cfg.VOICE_TTS_VOICE = cfg_attrs.get("voice", "")
    cfg.VOICE_TTS_SEGMENT_CHARS = cfg_attrs.get("segment_chars", 48)
    cfg.VOICE_TTS_BUFFER_CHARS = cfg_attrs.get("buffer_chars", 96)
    cfg.VOICE_VAD_ENABLED = cfg_attrs.get("vad_enabled", True)
    cfg.VOICE_VAD_MIN_SPEECH_BYTES = cfg_attrs.get("vad_min_speech_bytes", 1024)
    cfg.VOICE_DUPLEX_ENABLED = cfg_attrs.get("duplex_enabled", True)
    cfg.VOICE_VAD_INTERRUPT_MIN_BYTES = cfg_attrs.get("vad_interrupt_min_bytes", 384)
    return VoicePipeline(cfg)


def test_pipeline_init_mock_provider():
    p = _make_pipeline(provider="mock")
    assert p.provider == "mock"
    assert p.enabled is True


def test_pipeline_init_no_config():
    p = VoicePipeline(None)
    assert p.provider in ("mock", "pyttsx3")


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.extract_ready_segments
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_ready_segments_empty():
    p = _make_pipeline()
    segs, remainder = p.extract_ready_segments("")
    assert segs == []
    assert remainder == ""


def test_extract_ready_segments_flush():
    p = _make_pipeline()
    segs, remainder = p.extract_ready_segments("Merhaba dünya", flush=True)
    assert segs == ["Merhaba dünya"]
    assert remainder == ""


def test_extract_ready_segments_sentence_boundary():
    p = _make_pipeline(segment_chars=5)
    text = "Birinci cümle. İkinci kısım"
    segs, remainder = p.extract_ready_segments(text)
    assert any("Birinci cümle" in s for s in segs)


def test_extract_ready_segments_long_remainder():
    p = _make_pipeline(segment_chars=5)
    # Noktalama olmadan ama yeterince uzun
    text = "Bu bir uzun metin parçasıdır"
    segs, remainder = p.extract_ready_segments(text)
    assert isinstance(segs, list)


def test_extract_ready_segments_whitespace_only():
    p = _make_pipeline()
    segs, remainder = p.extract_ready_segments("   ")
    assert segs == []


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.DuplexState ve turn yönetimi
# ──────────────────────────────────────────────────────────────────────────────

def test_create_duplex_state():
    p = _make_pipeline()
    state = p.create_duplex_state()
    assert state.assistant_turn_id == 0
    assert state.output_sequence == 0
    assert state.output_text_buffer == ""
    assert state.interrupted_turns == []


def test_begin_assistant_turn_increments_id():
    p = _make_pipeline()
    state = p.create_duplex_state()
    turn_id = p.begin_assistant_turn(state)
    assert turn_id == 1
    assert state.assistant_turn_id == 1
    assert state.output_sequence == 0
    assert state.output_text_buffer == ""


def test_begin_assistant_turn_none_state():
    p = _make_pipeline()
    result = p.begin_assistant_turn(None)
    assert result == 0


def test_begin_assistant_turn_clears_buffer():
    p = _make_pipeline()
    state = p.create_duplex_state()
    state.output_text_buffer = "eski metin"
    state.last_interrupt_reason = "barge_in"
    p.begin_assistant_turn(state)
    assert state.output_text_buffer == ""
    assert state.last_interrupt_reason == ""


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.buffer_assistant_text
# ──────────────────────────────────────────────────────────────────────────────

def test_buffer_assistant_text_no_state():
    p = _make_pipeline(segment_chars=5)
    turn_id, packets = p.buffer_assistant_text(None, "Merhaba. Test.", flush=True)
    assert turn_id == 0
    assert isinstance(packets, list)


def test_buffer_assistant_text_flush_emits_all():
    p = _make_pipeline(segment_chars=5)
    state = p.create_duplex_state()
    p.begin_assistant_turn(state)
    turn_id, packets = p.buffer_assistant_text(state, "Son cümle.", flush=True)
    assert turn_id == 1
    assert any("Son cümle" in pkt["text"] for pkt in packets)


def test_buffer_assistant_text_short_stays_buffered():
    p = _make_pipeline(segment_chars=200, buffer_chars=400)
    state = p.create_duplex_state()
    p.begin_assistant_turn(state)
    _, packets = p.buffer_assistant_text(state, "Kısa.", flush=False)
    assert packets == []
    assert "Kısa." in state.output_text_buffer


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.interrupt_assistant_turn
# ──────────────────────────────────────────────────────────────────────────────

def test_interrupt_assistant_turn_with_state():
    p = _make_pipeline()
    state = p.create_duplex_state()
    p.begin_assistant_turn(state)
    state.output_text_buffer = "Kesilecek metin"
    result = p.interrupt_assistant_turn(state, reason="barge_in")
    assert result["assistant_turn_id"] == 1
    assert result["dropped_text_chars"] == len("Kesilecek metin")
    assert result["reason"] == "barge_in"
    assert state.output_text_buffer == ""
    assert 1 in state.interrupted_turns


def test_interrupt_assistant_turn_none_state():
    p = _make_pipeline()
    result = p.interrupt_assistant_turn(None, reason="interrupt")
    assert result["assistant_turn_id"] == 0
    assert result["dropped_text_chars"] == 0


def test_interrupt_assistant_turn_empty_reason():
    p = _make_pipeline()
    state = p.create_duplex_state()
    p.begin_assistant_turn(state)
    result = p.interrupt_assistant_turn(state, reason="")
    assert result["reason"] == "interrupt"


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.should_commit_audio
# ──────────────────────────────────────────────────────────────────────────────

def test_should_commit_audio_true():
    p = _make_pipeline(vad_enabled=True, vad_min_speech_bytes=512)
    assert p.should_commit_audio(1024, event="speech_end") is True


def test_should_commit_audio_too_small():
    p = _make_pipeline(vad_enabled=True, vad_min_speech_bytes=1024)
    assert p.should_commit_audio(100, event="speech_end") is False


def test_should_commit_audio_wrong_event():
    p = _make_pipeline(vad_enabled=True)
    assert p.should_commit_audio(2048, event="speech_start") is False


def test_should_commit_audio_vad_disabled():
    p = _make_pipeline(vad_enabled=False)
    assert p.should_commit_audio(4096, event="speech_end") is False


def test_should_commit_audio_all_commit_events():
    # vad_min_speech_bytes kaynak kodda max(256, ...) ile en az 256 olarak zorlanır
    p = _make_pipeline(vad_enabled=True, vad_min_speech_bytes=256)
    for event in ("speech_end", "speech_ended", "end_of_turn", "silence", "vad_commit"):
        assert p.should_commit_audio(512, event=event) is True


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.should_interrupt_response
# ──────────────────────────────────────────────────────────────────────────────

def test_should_interrupt_response_true():
    p = _make_pipeline(vad_enabled=True, duplex_enabled=True, vad_interrupt_min_bytes=256)
    assert p.should_interrupt_response(512, event="speech_start") is True


def test_should_interrupt_response_duplex_disabled():
    p = _make_pipeline(vad_enabled=True, duplex_enabled=False)
    assert p.should_interrupt_response(1024, event="speech_start") is False


def test_should_interrupt_response_not_interrupt_event():
    p = _make_pipeline(vad_enabled=True, duplex_enabled=True)
    assert p.should_interrupt_response(1024, event="silence") is False


def test_should_interrupt_response_all_interrupt_events():
    p = _make_pipeline(vad_enabled=True, duplex_enabled=True, vad_interrupt_min_bytes=100)
    for event in ("speech_start", "speech", "user_speaking", "barge_in", "interrupt"):
        assert p.should_interrupt_response(200, event=event) is True


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.build_voice_state_payload
# ──────────────────────────────────────────────────────────────────────────────

def test_build_voice_state_payload_with_state():
    p = _make_pipeline(vad_enabled=True, duplex_enabled=True)
    state = p.create_duplex_state()
    payload = p.build_voice_state_payload(event="speech_end", buffered_bytes=2048, sequence=3, duplex_state=state)
    assert payload["voice_state"] == "speech_end"
    assert payload["buffered_bytes"] == 2048
    assert payload["sequence"] == 3
    assert payload["vad_enabled"] is True
    assert payload["duplex_enabled"] is True
    assert "auto_commit_ready" in payload
    assert "interrupt_ready" in payload
    assert "tts_enabled" in payload


def test_build_voice_state_payload_without_state():
    p = _make_pipeline()
    payload = p.build_voice_state_payload(event="silence", buffered_bytes=0, sequence=0)
    assert payload["voice_state"] == "silence"
    assert payload["assistant_turn_id"] == 0
    assert payload["output_buffer_chars"] == 0


def test_build_voice_state_payload_empty_event():
    p = _make_pipeline()
    payload = p.build_voice_state_payload(event="", buffered_bytes=0, sequence=0)
    assert payload["voice_state"] == "unknown"


def test_build_voice_state_payload_negative_values():
    p = _make_pipeline()
    payload = p.build_voice_state_payload(event="test", buffered_bytes=-5, sequence=-1)
    assert payload["buffered_bytes"] == 0
    assert payload["sequence"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.synthesize_text
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_synthesize_text_success():
    p = _make_pipeline(provider="mock")
    result = await p.synthesize_text("Merhaba dünya")
    assert result["success"] is True
    assert result["audio_bytes"] == b"Merhaba d\xc3\xbcnya"


@pytest.mark.asyncio
async def test_synthesize_text_empty():
    p = _make_pipeline(provider="mock")
    result = await p.synthesize_text("")
    assert result["success"] is False
    assert "Boş metin" in result["reason"]


@pytest.mark.asyncio
async def test_synthesize_text_whitespace_only():
    p = _make_pipeline(provider="mock")
    result = await p.synthesize_text("   ")
    assert result["success"] is False
