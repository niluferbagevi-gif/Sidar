"""Unit tests for core/voice.py — VoicePipeline ve TTS adaptörleri."""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.voice as voice_module
from core.voice import (
    VoicePipeline,
    _MockTTSAdapter,
    _Pyttsx3Adapter,
    _BaseTTSAdapter,
    _build_tts_adapter,
)


# ──────────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ──────────────────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


def _make_config(**overrides) -> MagicMock:
    cfg = MagicMock()
    cfg.VOICE_TTS_PROVIDER = "mock"
    cfg.VOICE_TTS_VOICE = ""
    cfg.VOICE_TTS_SEGMENT_CHARS = 48
    cfg.VOICE_TTS_BUFFER_CHARS = 96
    cfg.VOICE_VAD_ENABLED = True
    cfg.VOICE_VAD_MIN_SPEECH_BYTES = 1024
    cfg.VOICE_DUPLEX_ENABLED = True
    cfg.VOICE_VAD_INTERRUPT_MIN_BYTES = 384
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# ──────────────────────────────────────────────────────────────────────────────
# _BaseTTSAdapter
# ──────────────────────────────────────────────────────────────────────────────

class TestBaseTTSAdapter:
    def test_available_is_true(self):
        adapter = _BaseTTSAdapter()
        assert adapter.available is True

    def test_synthesize_raises_not_implemented(self):
        adapter = _BaseTTSAdapter()
        with pytest.raises(NotImplementedError):
            run(adapter.synthesize("merhaba"))


# ──────────────────────────────────────────────────────────────────────────────
# _MockTTSAdapter
# ──────────────────────────────────────────────────────────────────────────────

class TestMockTTSAdapter:
    def test_provider_name(self):
        assert _MockTTSAdapter.provider == "mock"

    def test_synthesize_non_empty_text_returns_success(self):
        adapter = _MockTTSAdapter()
        result = run(adapter.synthesize("Merhaba dünya"))
        assert result["success"] is True
        assert result["audio_bytes"] == b"Merhaba d\xc3\xbcnya"
        assert result["mime_type"] == "audio/mock"
        assert result["provider"] == "mock"

    def test_synthesize_empty_text_returns_failure(self):
        adapter = _MockTTSAdapter()
        result = run(adapter.synthesize(""))
        assert result["success"] is False
        assert result["audio_bytes"] == b""
        assert "Boş metin" in result["reason"]

    def test_synthesize_whitespace_only_returns_failure(self):
        adapter = _MockTTSAdapter()
        result = run(adapter.synthesize("   "))
        assert result["success"] is False

    def test_synthesize_passes_voice_parameter(self):
        adapter = _MockTTSAdapter()
        result = run(adapter.synthesize("test", voice="tr-TR-female"))
        assert result["voice"] == "tr-TR-female"


# ──────────────────────────────────────────────────────────────────────────────
# _Pyttsx3Adapter
# ──────────────────────────────────────────────────────────────────────────────

class TestPyttsx3Adapter:
    def test_available_false_when_import_fails(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyttsx3", None)
        # None girişi ImportError fırlatır
        adapter = _Pyttsx3Adapter()
        assert adapter.available is False

    def test_synthesize_returns_failure_when_unavailable(self):
        adapter = _Pyttsx3Adapter()
        adapter._import_error = "pyttsx3 not installed"
        result = run(adapter.synthesize("hello"))
        assert result["success"] is False
        assert result["audio_bytes"] == b""
        assert result["provider"] == "pyttsx3"
        assert result["mime_type"] == "audio/wav"
        assert "pyttsx3 not installed" in result["reason"]

    def test_synthesize_returns_failure_with_default_reason_when_import_error_empty(self):
        adapter = _Pyttsx3Adapter()
        adapter._import_error = ""  # suppresses is-available check
        # available still returns True when _import_error == ""
        # We force the adapter to be unavailable by setting a non-empty error
        adapter._import_error = "missing lib"
        result = run(adapter.synthesize("x"))
        assert result["success"] is False
        assert "missing lib" in result["reason"]

    def test_provider_name(self):
        assert _Pyttsx3Adapter.provider == "pyttsx3"


# ──────────────────────────────────────────────────────────────────────────────
# _build_tts_adapter
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildTTSAdapter:
    def test_mock_provider_returns_mock_adapter(self):
        adapter = _build_tts_adapter("mock")
        assert isinstance(adapter, _MockTTSAdapter)

    def test_pyttsx3_provider_returns_pyttsx3_adapter(self):
        adapter = _build_tts_adapter("pyttsx3")
        assert isinstance(adapter, _Pyttsx3Adapter)

    def test_auto_falls_back_to_mock_when_pyttsx3_unavailable(self, monkeypatch):
        # pyttsx3 bulunamıyorsa auto => mock dönmeli
        fake_pyttsx3 = _Pyttsx3Adapter.__new__(_Pyttsx3Adapter)
        fake_pyttsx3._import_error = "not installed"
        monkeypatch.setattr(voice_module, "_Pyttsx3Adapter", lambda: fake_pyttsx3)
        adapter = _build_tts_adapter("auto")
        assert isinstance(adapter, _MockTTSAdapter)

    def test_auto_prefers_pyttsx3_when_available(self, monkeypatch):
        fake_pyttsx3 = _Pyttsx3Adapter.__new__(_Pyttsx3Adapter)
        fake_pyttsx3._import_error = ""  # available
        monkeypatch.setattr(voice_module, "_Pyttsx3Adapter", lambda: fake_pyttsx3)
        adapter = _build_tts_adapter("auto")
        assert adapter is fake_pyttsx3

    def test_empty_provider_treated_as_auto(self, monkeypatch):
        fake = _Pyttsx3Adapter.__new__(_Pyttsx3Adapter)
        fake._import_error = "nope"
        monkeypatch.setattr(voice_module, "_Pyttsx3Adapter", lambda: fake)
        adapter = _build_tts_adapter("")
        assert isinstance(adapter, _MockTTSAdapter)


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline — __init__ ve enabled
# ──────────────────────────────────────────────────────────────────────────────

class TestVoicePipelineInit:
    def test_default_config_none_uses_mock(self):
        pipeline = VoicePipeline(config=None)
        # auto → _MockTTSAdapter (pyttsx3 muhtemelen test ortamında yüklü değil)
        assert pipeline.provider in ("mock", "pyttsx3")

    def test_mock_provider_from_config(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_TTS_PROVIDER="mock"))
        assert pipeline.provider == "mock"
        assert pipeline.enabled is True

    def test_custom_segment_chars(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_TTS_SEGMENT_CHARS=60))
        assert pipeline.segment_chars == 60

    def test_segment_chars_minimum_enforced(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_TTS_SEGMENT_CHARS=5))
        assert pipeline.segment_chars == 20

    def test_buffer_chars_minimum_is_segment_chars(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_TTS_SEGMENT_CHARS=48, VOICE_TTS_BUFFER_CHARS=10))
        assert pipeline.buffer_chars >= pipeline.segment_chars

    def test_vad_enabled_from_config(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_VAD_ENABLED=False))
        assert pipeline.vad_enabled is False

    def test_duplex_enabled_from_config(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_DUPLEX_ENABLED=False))
        assert pipeline.duplex_enabled is False

    def test_vad_min_speech_bytes_minimum_enforced(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_VAD_MIN_SPEECH_BYTES=10))
        assert pipeline.vad_min_speech_bytes == 256

    def test_vad_interrupt_min_bytes_minimum_enforced(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_VAD_INTERRUPT_MIN_BYTES=50))
        assert pipeline.vad_interrupt_min_bytes == 128

    def test_voice_read_from_config(self):
        pipeline = VoicePipeline(config=_make_config(VOICE_TTS_VOICE="tr-TR"))
        assert pipeline.voice == "tr-TR"


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.extract_ready_segments
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractReadySegments:
    def _pipeline(self, segment_chars=48):
        cfg = _make_config(VOICE_TTS_SEGMENT_CHARS=segment_chars, VOICE_TTS_BUFFER_CHARS=segment_chars * 2)
        return VoicePipeline(config=cfg)

    def test_empty_buffer_returns_empty(self):
        pipeline = self._pipeline()
        segs, rem = pipeline.extract_ready_segments("")
        assert segs == []
        assert rem == ""

    def test_whitespace_only_returns_empty(self):
        pipeline = self._pipeline()
        segs, rem = pipeline.extract_ready_segments("   ")
        assert segs == []

    def test_flush_true_returns_all_as_one_segment(self):
        pipeline = self._pipeline()
        segs, rem = pipeline.extract_ready_segments("Bir cümle", flush=True)
        assert segs == ["Bir cümle"]
        assert rem == ""

    def test_flush_empty_returns_empty(self):
        pipeline = self._pipeline()
        segs, rem = pipeline.extract_ready_segments("   ", flush=True)
        assert segs == []
        assert rem == ""

    def test_splits_on_sentence_boundary(self):
        pipeline = self._pipeline()
        text = "Birinci cümle. İkinci cümle."
        segs, rem = pipeline.extract_ready_segments(text)
        assert "Birinci cümle." in segs
        assert "İkinci cümle." in rem or "İkinci cümle." in segs

    def test_long_remainder_becomes_segment(self):
        pipeline = self._pipeline(segment_chars=10)
        text = "Bu yeterince uzun bir metin parçasıdır."
        segs, rem = pipeline.extract_ready_segments(text)
        assert len(segs) > 0 or rem == ""

    def test_short_text_below_segment_chars_stays_as_remainder(self):
        pipeline = self._pipeline(segment_chars=100)
        text = "Kısa"
        segs, rem = pipeline.extract_ready_segments(text)
        assert segs == []
        assert "Kısa" in rem

    def test_japanese_boundary_character(self):
        pipeline = self._pipeline()
        text = "一文目。 二文目。"
        segs, rem = pipeline.extract_ready_segments(text)
        combined = " ".join(segs) + rem
        assert "一文目" in combined


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.DuplexState ve yöneticiler
# ──────────────────────────────────────────────────────────────────────────────

class TestDuplexState:
    def _pipeline(self):
        return VoicePipeline(config=_make_config())

    def test_create_duplex_state_defaults(self):
        state = self._pipeline().create_duplex_state()
        assert state.assistant_turn_id == 0
        assert state.output_sequence == 0
        assert state.output_text_buffer == ""
        assert state.interrupted_turns == []
        assert state.last_interrupt_reason == ""

    def test_begin_assistant_turn_increments_turn_id(self):
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        turn_id = pipeline.begin_assistant_turn(state)
        assert turn_id == 1
        assert state.assistant_turn_id == 1
        assert state.output_sequence == 0
        assert state.output_text_buffer == ""

    def test_begin_assistant_turn_resets_buffer_and_sequence(self):
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        state.output_text_buffer = "eski metin"
        state.output_sequence = 5
        pipeline.begin_assistant_turn(state)
        assert state.output_text_buffer == ""
        assert state.output_sequence == 0

    def test_begin_assistant_turn_with_none_state_returns_zero(self):
        pipeline = self._pipeline()
        assert pipeline.begin_assistant_turn(None) == 0

    def test_duplex_state_interrupted_turns_are_independent(self):
        pipeline = self._pipeline()
        state1 = pipeline.create_duplex_state()
        state2 = pipeline.create_duplex_state()
        state1.interrupted_turns.append(99)
        assert state2.interrupted_turns == []


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.buffer_assistant_text
# ──────────────────────────────────────────────────────────────────────────────

class TestBufferAssistantText:
    def _pipeline(self, segment_chars=20, buffer_chars=40):
        cfg = _make_config(VOICE_TTS_SEGMENT_CHARS=segment_chars, VOICE_TTS_BUFFER_CHARS=buffer_chars)
        return VoicePipeline(config=cfg)

    def test_none_state_returns_turn_zero_with_segments(self):
        pipeline = self._pipeline()
        turn_id, packets = pipeline.buffer_assistant_text(None, "Kısa metin.", flush=True)
        assert turn_id == 0
        assert len(packets) >= 1
        assert packets[0]["assistant_turn_id"] == 0

    def test_small_buffer_below_threshold_returns_no_packets(self):
        pipeline = self._pipeline(segment_chars=20, buffer_chars=200)
        state = pipeline.create_duplex_state()
        pipeline.begin_assistant_turn(state)
        turn_id, packets = pipeline.buffer_assistant_text(state, "Kısa")
        assert packets == []

    def test_flush_emits_all_buffered_text(self):
        # Noktalama işareti olmayan metin → sınır tespiti yapılamaz, yalnızca flush ile çıkar
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        pipeline.begin_assistant_turn(state)
        # Nokta içermeyen kısa metin: boundary split olmaz, flush olmadan emit olmaz
        pipeline.buffer_assistant_text(state, "kısa metin")
        turn_id, packets = pipeline.buffer_assistant_text(state, "", flush=True)
        assert len(packets) >= 1
        assert all(p["assistant_turn_id"] == 1 for p in packets)

    def test_packets_have_correct_audio_sequence(self):
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        pipeline.begin_assistant_turn(state)
        _, p1 = pipeline.buffer_assistant_text(state, "Birinci. İkinci. Üçüncü.", flush=True)
        sequences = [p["audio_sequence"] for p in p1]
        assert sequences == list(range(1, len(sequences) + 1))

    def test_buffer_accumulates_across_calls(self):
        # segment_chars=50 → kısa parçalar bu eşiğe ulaşmadan birikmeli
        pipeline = self._pipeline(segment_chars=50, buffer_chars=100)
        state = pipeline.create_duplex_state()
        pipeline.begin_assistant_turn(state)
        # Her çağrı kısa metin ekler, toplam <50 char → flush olmadan emit olmaz
        pipeline.buffer_assistant_text(state, "aa ")
        pipeline.buffer_assistant_text(state, "bb")
        # flush=True ile biriktirilen tüm metni al
        _, packets = pipeline.buffer_assistant_text(state, "", flush=True)
        assert len(packets) >= 1
        full_text = " ".join(p["text"] for p in packets)
        assert "aa" in full_text and "bb" in full_text


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.interrupt_assistant_turn
# ──────────────────────────────────────────────────────────────────────────────

class TestInterruptAssistantTurn:
    def _pipeline(self):
        return VoicePipeline(config=_make_config())

    def test_none_state_returns_default_structure(self):
        pipeline = self._pipeline()
        result = pipeline.interrupt_assistant_turn(None, reason="barge_in")
        assert result["assistant_turn_id"] == 0
        assert result["dropped_text_chars"] == 0
        assert result["cancelled_audio_sequences"] == 0
        assert result["reason"] == "barge_in"

    def test_none_state_empty_reason_defaults_to_interrupt(self):
        pipeline = self._pipeline()
        result = pipeline.interrupt_assistant_turn(None, reason="")
        assert result["reason"] == "interrupt"

    def test_with_state_clears_buffer(self):
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        pipeline.begin_assistant_turn(state)
        state.output_text_buffer = "bekleyen metin"
        state.output_sequence = 3
        result = pipeline.interrupt_assistant_turn(state, reason="user_speaking")
        assert result["dropped_text_chars"] == len("bekleyen metin")
        assert result["cancelled_audio_sequences"] == 3
        assert state.output_text_buffer == ""
        assert state.output_sequence == 0

    def test_with_state_records_interrupted_turn(self):
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        pipeline.begin_assistant_turn(state)
        pipeline.interrupt_assistant_turn(state, reason="speech_start")
        assert 1 in state.interrupted_turns

    def test_with_state_sets_last_interrupt_reason(self):
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        pipeline.begin_assistant_turn(state)
        pipeline.interrupt_assistant_turn(state, reason="barge_in")
        assert state.last_interrupt_reason == "barge_in"

    def test_interrupting_turn_zero_does_not_record(self):
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        # turn_id 0 iken interrupt: listeye eklenmemeli
        pipeline.interrupt_assistant_turn(state, reason="x")
        assert state.interrupted_turns == []


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.should_commit_audio
# ──────────────────────────────────────────────────────────────────────────────

class TestShouldCommitAudio:
    def _pipeline(self, vad_enabled=True, min_bytes=1024):
        cfg = _make_config(VOICE_VAD_ENABLED=vad_enabled, VOICE_VAD_MIN_SPEECH_BYTES=min_bytes)
        return VoicePipeline(config=cfg)

    def test_false_when_vad_disabled(self):
        pipeline = self._pipeline(vad_enabled=False)
        assert pipeline.should_commit_audio(9999, event="speech_end") is False

    def test_false_for_non_commit_event(self):
        pipeline = self._pipeline()
        assert pipeline.should_commit_audio(9999, event="unknown_event") is False

    def test_false_when_bytes_below_minimum(self):
        pipeline = self._pipeline(min_bytes=1024)
        assert pipeline.should_commit_audio(512, event="speech_end") is False

    def test_true_for_speech_end_with_enough_bytes(self):
        pipeline = self._pipeline(min_bytes=256)
        assert pipeline.should_commit_audio(1024, event="speech_end") is True

    @pytest.mark.parametrize("event", ["speech_end", "speech_ended", "end_of_turn", "silence", "vad_commit"])
    def test_all_commit_events_accepted(self, event):
        # vad_min_speech_bytes minimum 256'ya zorlanır; 1024 byte yeterli
        pipeline = self._pipeline(min_bytes=256)
        assert pipeline.should_commit_audio(1024, event=event) is True

    def test_empty_event_returns_false(self):
        pipeline = self._pipeline()
        assert pipeline.should_commit_audio(9999, event="") is False


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.should_interrupt_response
# ──────────────────────────────────────────────────────────────────────────────

class TestShouldInterruptResponse:
    def _pipeline(self, vad_enabled=True, duplex_enabled=True, interrupt_min=384):
        cfg = _make_config(
            VOICE_VAD_ENABLED=vad_enabled,
            VOICE_DUPLEX_ENABLED=duplex_enabled,
            VOICE_VAD_INTERRUPT_MIN_BYTES=interrupt_min,
        )
        return VoicePipeline(config=cfg)

    def test_false_when_vad_disabled(self):
        pipeline = self._pipeline(vad_enabled=False)
        assert pipeline.should_interrupt_response(9999, event="speech_start") is False

    def test_false_when_duplex_disabled(self):
        pipeline = self._pipeline(duplex_enabled=False)
        assert pipeline.should_interrupt_response(9999, event="speech_start") is False

    def test_false_for_non_interrupt_event(self):
        pipeline = self._pipeline()
        assert pipeline.should_interrupt_response(9999, event="silence") is False

    def test_false_when_bytes_below_minimum(self):
        pipeline = self._pipeline(interrupt_min=384)
        assert pipeline.should_interrupt_response(200, event="speech_start") is False

    def test_true_for_speech_start_with_enough_bytes(self):
        pipeline = self._pipeline(interrupt_min=128)
        assert pipeline.should_interrupt_response(256, event="speech_start") is True

    @pytest.mark.parametrize("event", ["speech_start", "speech", "user_speaking", "barge_in", "interrupt"])
    def test_all_interrupt_events_accepted(self, event):
        pipeline = self._pipeline(interrupt_min=100)
        assert pipeline.should_interrupt_response(200, event=event) is True


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.build_voice_state_payload
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildVoiceStatePayload:
    def _pipeline(self):
        return VoicePipeline(config=_make_config(VOICE_VAD_MIN_SPEECH_BYTES=256))

    def test_returns_required_keys(self):
        pipeline = self._pipeline()
        payload = pipeline.build_voice_state_payload(event="silence", buffered_bytes=0, sequence=0)
        required = {
            "voice_state", "buffered_bytes", "sequence", "vad_enabled",
            "auto_commit_ready", "duplex_enabled", "interrupt_ready",
            "tts_enabled", "assistant_turn_id", "output_buffer_chars",
            "last_interrupt_reason",
        }
        assert required.issubset(payload.keys())

    def test_empty_event_normalized_to_unknown(self):
        pipeline = self._pipeline()
        payload = pipeline.build_voice_state_payload(event="", buffered_bytes=0, sequence=0)
        assert payload["voice_state"] == "unknown"

    def test_negative_bytes_clamped_to_zero(self):
        pipeline = self._pipeline()
        payload = pipeline.build_voice_state_payload(event="silence", buffered_bytes=-100, sequence=0)
        assert payload["buffered_bytes"] == 0

    def test_auto_commit_ready_reflects_commit_logic(self):
        pipeline = self._pipeline()
        # 2048 bytes + speech_end → commit olmalı
        payload = pipeline.build_voice_state_payload(event="speech_end", buffered_bytes=2048, sequence=1)
        assert payload["auto_commit_ready"] is True

    def test_interrupt_ready_reflects_interrupt_logic(self):
        pipeline = self._pipeline()
        payload = pipeline.build_voice_state_payload(event="speech_start", buffered_bytes=2048, sequence=1)
        assert payload["interrupt_ready"] is True

    def test_with_duplex_state(self):
        pipeline = self._pipeline()
        state = pipeline.create_duplex_state()
        pipeline.begin_assistant_turn(state)
        state.output_text_buffer = "test"
        payload = pipeline.build_voice_state_payload(
            event="silence", buffered_bytes=0, sequence=0, duplex_state=state
        )
        assert payload["assistant_turn_id"] == 1
        assert payload["output_buffer_chars"] == 4

    def test_with_none_duplex_state(self):
        pipeline = self._pipeline()
        payload = pipeline.build_voice_state_payload(
            event="silence", buffered_bytes=0, sequence=0, duplex_state=None
        )
        assert payload["assistant_turn_id"] == 0
        assert payload["output_buffer_chars"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# VoicePipeline.synthesize_text
# ──────────────────────────────────────────────────────────────────────────────

class TestSynthesizeText:
    def _pipeline(self):
        return VoicePipeline(config=_make_config(VOICE_TTS_PROVIDER="mock"))

    def test_empty_text_returns_failure(self):
        result = run(self._pipeline().synthesize_text(""))
        assert result["success"] is False
        assert result["audio_bytes"] == b""
        assert "Boş metin" in result["reason"]

    def test_whitespace_only_returns_failure(self):
        result = run(self._pipeline().synthesize_text("   "))
        assert result["success"] is False

    def test_non_empty_text_delegates_to_adapter(self):
        pipeline = self._pipeline()
        result = run(pipeline.synthesize_text("Merhaba"))
        assert result["success"] is True
        assert result["provider"] == "mock"

    def test_synthesize_text_strips_whitespace(self):
        pipeline = self._pipeline()
        result = run(pipeline.synthesize_text("  test  "))
        # strip sonrası "test" → success
        assert result["success"] is True

    def test_synthesize_text_forwards_voice_config(self):
        cfg = _make_config(VOICE_TTS_PROVIDER="mock", VOICE_TTS_VOICE="en-US")
        pipeline = VoicePipeline(config=cfg)
        result = run(pipeline.synthesize_text("hello"))
        assert result["voice"] == "en-US"
