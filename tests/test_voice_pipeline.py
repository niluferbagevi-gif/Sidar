
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.voice as voice_mod
from core.voice import VoicePipeline


class _Cfg:
    VOICE_TTS_PROVIDER = "mock"
    VOICE_TTS_VOICE = ""
    VOICE_TTS_SEGMENT_CHARS = 12
    VOICE_TTS_BUFFER_CHARS = 24


def test_base_tts_adapter_requires_override():
    adapter = voice_mod._BaseTTSAdapter()

    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.synthesize("Merhaba"))


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


def test_build_tts_adapter_explicit_pyttsx3_returns_pyttsx3_adapter(monkeypatch):
    class _AvailableAdapter:
        provider = "pyttsx3"

        def __init__(self):
            self._import_error = ""

        @property
        def available(self):
            return True

    monkeypatch.setattr(voice_mod, "_Pyttsx3Adapter", _AvailableAdapter)

    adapter = voice_mod._build_tts_adapter("pyttsx3")

    assert isinstance(adapter, _AvailableAdapter)


def test_build_tts_adapter_auto_prefers_available_pyttsx3(monkeypatch):
    class _AvailableAdapter:
        provider = "pyttsx3"

        def __init__(self):
            self._import_error = ""

        @property
        def available(self):
            return True

    monkeypatch.setattr(voice_mod, "_Pyttsx3Adapter", _AvailableAdapter)

    adapter = voice_mod._build_tts_adapter("auto")

    assert isinstance(adapter, _AvailableAdapter)


def test_pyttsx3_adapter_reports_import_failure(monkeypatch):
    monkeypatch.setattr(voice_mod, "_Pyttsx3Adapter", voice_mod._Pyttsx3Adapter)
    adapter = voice_mod._Pyttsx3Adapter()
    monkeypatch.setattr(adapter, "_import_error", "pyttsx3 missing")

    result = asyncio.run(adapter.synthesize("Merhaba", voice="tr"))

    assert result["success"] is False
    assert result["provider"] == "pyttsx3"
    assert result["reason"] == "pyttsx3 missing"


def test_pyttsx3_adapter_synthesize_uses_to_thread_when_available(monkeypatch):
    adapter = voice_mod._Pyttsx3Adapter()
    monkeypatch.setattr(adapter, "_import_error", "")

    async def _fake_to_thread(func, text, voice):
        assert getattr(func, "__self__", None) is adapter
        assert getattr(func, "__func__", None) is voice_mod._Pyttsx3Adapter._synthesize_sync
        assert text == "Merhaba"
        assert voice == "tr"
        return {"success": True, "provider": "pyttsx3", "voice": voice}

    monkeypatch.setattr(voice_mod.asyncio, "to_thread", _fake_to_thread)

    result = asyncio.run(adapter.synthesize("Merhaba", voice="tr"))

    assert result == {"success": True, "provider": "pyttsx3", "voice": "tr"}


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


def test_voice_pipeline_tracks_duplex_output_buffers_and_interrupts():
    cfg = SimpleNamespace(
        VOICE_TTS_PROVIDER="mock",
        VOICE_TTS_VOICE="",
        VOICE_TTS_SEGMENT_CHARS=12,
        VOICE_TTS_BUFFER_CHARS=24,
        VOICE_VAD_ENABLED=True,
        VOICE_DUPLEX_ENABLED=True,
    )
    pipeline = VoicePipeline(cfg)
    state = pipeline.create_duplex_state()

    turn_id = pipeline.begin_assistant_turn(state)
    assert turn_id == 1

    same_turn, packets = pipeline.buffer_assistant_text(state, "Merhaba", flush=False)
    assert same_turn == 1
    assert packets == []

    same_turn, packets = pipeline.buffer_assistant_text(state, " dünya. Yeni cümle", flush=False)
    assert same_turn == 1
    assert packets[0]["assistant_turn_id"] == 1
    assert packets[0]["audio_sequence"] == 1
    assert packets[0]["text"] == "Merhaba dünya."

    payload = pipeline.build_voice_state_payload(
        event="speech",
        buffered_bytes=320,
        sequence=7,
        duplex_state=state,
    )
    assert payload["assistant_turn_id"] == 1
    assert payload["output_buffer_chars"] == len("Yeni cümle")

    interrupt = pipeline.interrupt_assistant_turn(state, reason="barge_in")
    assert interrupt["assistant_turn_id"] == 1
    assert interrupt["dropped_text_chars"] == len("Yeni cümle")
    assert interrupt["cancelled_audio_sequences"] == 1
    assert state.output_text_buffer == ""
    assert state.last_interrupt_reason == "barge_in"


def test_pyttsx3_adapter_synthesize_sync_selects_voice_and_tolerates_stop_error(monkeypatch, tmp_path):
    class _TrackingTempDir:
        def __init__(self, prefix="sidar-tts-"):
            self.prefix = prefix
            self.path = tmp_path / prefix.rstrip("-")

        def __enter__(self):
            self.path.mkdir(parents=True, exist_ok=True)
            return str(self.path)

        def __exit__(self, exc_type, exc, tb):
            for child in sorted(self.path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            self.path.rmdir()
            return False

    class _Engine:
        def __init__(self):
            self.selected_voice = None
            self.saved_to = None
            self.stopped = False

        def getProperty(self, name):
            assert name == "voices"
            return [
                SimpleNamespace(id="en-us", name="English"),
                SimpleNamespace(id="tr-voice", name="Turkish Voice"),
            ]

        def setProperty(self, name, value):
            assert name == "voice"
            self.selected_voice = value

        def save_to_file(self, text, output_path):
            self.saved_to = output_path
            Path(output_path).write_bytes(f"audio:{text}".encode("utf-8"))

        def runAndWait(self):
            return None

        def stop(self):
            self.stopped = True
            raise RuntimeError("stop failed")

    engine = _Engine()
    monkeypatch.setitem(sys.modules, "pyttsx3", SimpleNamespace(init=lambda: engine))
    monkeypatch.setattr(voice_mod.tempfile, "TemporaryDirectory", _TrackingTempDir)

    adapter = voice_mod._Pyttsx3Adapter()
    result = adapter._synthesize_sync("Merhaba", "turkish")

    assert result["success"] is True
    assert result["audio_bytes"] == b"audio:Merhaba"
    assert result["provider"] == "pyttsx3"
    assert result["voice"] == "turkish"
    assert engine.selected_voice == "tr-voice"
    assert engine.saved_to.endswith("speech.wav")
    assert engine.stopped is True


def test_pyttsx3_adapter_propagates_device_and_permission_errors(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "pyttsx3",
        SimpleNamespace(init=lambda: (_ for _ in ()).throw(OSError("No Default Input Device Available"))),
    )
    adapter = voice_mod._Pyttsx3Adapter()

    with pytest.raises(OSError, match="No Default Input Device Available"):
        adapter._synthesize_sync("Merhaba", "")

    monkeypatch.setitem(
        sys.modules,
        "pyttsx3",
        SimpleNamespace(init=lambda: (_ for _ in ()).throw(PermissionError("Microphone access denied"))),
    )

    with pytest.raises(PermissionError, match="Microphone access denied"):
        adapter._synthesize_sync("Merhaba", "")


def test_pyttsx3_adapter_reports_missing_output_file(monkeypatch, tmp_path):
    class _TrackingTempDir:
        def __init__(self, prefix="sidar-tts-"):
            self.path = tmp_path / prefix.rstrip("-")

        def __enter__(self):
            self.path.mkdir(parents=True, exist_ok=True)
            return str(self.path)

        def __exit__(self, exc_type, exc, tb):
            for child in sorted(self.path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            self.path.rmdir()
            return False

    class _Engine:
        def getProperty(self, _name):
            return []

        def save_to_file(self, _text, _output_path):
            return None

        def runAndWait(self):
            return None

        def stop(self):
            return None

    monkeypatch.setitem(sys.modules, "pyttsx3", SimpleNamespace(init=lambda: _Engine()))
    monkeypatch.setattr(voice_mod.tempfile, "TemporaryDirectory", _TrackingTempDir)

    adapter = voice_mod._Pyttsx3Adapter()
    result = adapter._synthesize_sync("Merhaba", "")

    assert result["success"] is False
    assert result["audio_bytes"] == b""
    assert result["reason"] == "pyttsx3 çıktı üretemedi."


def test_voice_pipeline_covers_none_state_and_disabled_vad_paths():
    cfg = SimpleNamespace(
        VOICE_TTS_PROVIDER="mock",
        VOICE_VAD_ENABLED=False,
        VOICE_DUPLEX_ENABLED=False,
    )
    pipeline = VoicePipeline(cfg)

    assert pipeline.begin_assistant_turn(None) == 0
    turn_id, packets = pipeline.buffer_assistant_text(None, "Parça bir. Parça iki", flush=True)
    assert turn_id == 0
    assert packets == [{"assistant_turn_id": 0, "audio_sequence": 1, "text": "Parça bir. Parça iki"}]

    interrupt = pipeline.interrupt_assistant_turn(None, reason="")
    assert interrupt == {
        "assistant_turn_id": 0,
        "dropped_text_chars": 0,
        "cancelled_audio_sequences": 0,
        "reason": "interrupt",
    }
    assert pipeline.should_commit_audio(2048, event="speech_end") is False
    assert pipeline.should_interrupt_response(2048, event="barge_in") is False


def test_voice_pipeline_extract_ready_segments_returns_empty_for_blank_buffer():
    pipeline = VoicePipeline(_Cfg())

    ready, remainder = pipeline.extract_ready_segments("   ", flush=False)

    assert ready == []
    assert remainder == ""


def test_voice_pipeline_barge_in_clears_buffer_and_tracks_interrupted_turns():
    cfg = SimpleNamespace(
        VOICE_TTS_PROVIDER="mock",
        VOICE_TTS_SEGMENT_CHARS=20,
        VOICE_TTS_BUFFER_CHARS=20,
        VOICE_VAD_ENABLED=True,
        VOICE_DUPLEX_ENABLED=True,
        VOICE_VAD_INTERRUPT_MIN_BYTES=256,
    )
    pipeline = VoicePipeline(cfg)
    state = pipeline.create_duplex_state()

    pipeline.begin_assistant_turn(state)
    same_turn, first_packets = pipeline.buffer_assistant_text(state, "İlk yanıt cümlesi tamam. Devam", flush=False)
    assert same_turn == 1
    assert first_packets[0]["audio_sequence"] == 1
    assert state.output_text_buffer == "Devam"

    state.output_text_buffer = "Kuyrukta kalan yanıt"
    state.output_sequence = 2

    assert pipeline.should_interrupt_response(300, event="barge_in") is True
    interrupt = pipeline.interrupt_assistant_turn(state, reason="barge_in")

    assert interrupt["assistant_turn_id"] == 1
    assert interrupt["dropped_text_chars"] == len("Kuyrukta kalan yanıt")
    assert interrupt["cancelled_audio_sequences"] == 2
    assert state.interrupted_turns == [1]
    assert state.output_text_buffer == ""
    assert state.output_sequence == 0
    assert state.last_interrupt_reason == "barge_in"