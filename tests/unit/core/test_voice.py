"""core/voice.py için unit testler."""
from __future__ import annotations

import types
import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.voice import (
    BrowserAudioPacket,
    VoicePipeline,
    WebRTCAudioIngress,
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
# _Pyttsx3Adapter
# ──────────────────────────────────────────────────────────────────────────────

def test_pyttsx3_adapter_available():
    adapter = _Pyttsx3Adapter()
    assert adapter.available is True


def test_pyttsx3_adapter_synthesize_sync_selects_voice_and_reads_audio(monkeypatch, tmp_path):
    class FakeVoice:
        def __init__(self, voice_id, name):
            self.id = voice_id
            self.name = name

    class FakeEngine:
        def __init__(self):
            self.selected_voice = None

        def getProperty(self, key):
            if key == "voices":
                return [FakeVoice("en-US-1", "English"), FakeVoice("tr-TR-1", "Turkish")]
            return None

        def setProperty(self, key, value):
            if key == "voice":
                self.selected_voice = value

        def save_to_file(self, _text, output):
            Path(output).write_bytes(b"wav-bytes")

        def runAndWait(self):
            return None

        def stop(self):
            return None

    fake_engine = FakeEngine()
    fake_module = types.SimpleNamespace(init=lambda: fake_engine)
    monkeypatch.setattr("core.voice.pyttsx3", fake_module)

    class _TmpDir:
        def __init__(self, _prefix):
            self.path = tmp_path / "ttsdir"

        def __enter__(self):
            self.path.mkdir(parents=True, exist_ok=True)
            return str(self.path)

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("core.voice.tempfile.TemporaryDirectory", lambda prefix: _TmpDir(prefix))

    adapter = _Pyttsx3Adapter()
    result = adapter._synthesize_sync("Merhaba", "tr-tr")

    assert result["success"] is True
    assert result["audio_bytes"] == b"wav-bytes"
    assert result["voice"] == "tr-tr"
    assert fake_engine.selected_voice == "tr-TR-1"


def test_pyttsx3_adapter_synthesize_sync_handles_stop_exception(monkeypatch, tmp_path):
    class FakeEngine:
        def getProperty(self, _key):
            return []

        def setProperty(self, _key, _value):
            return None

        def save_to_file(self, _text, output):
            Path(output).write_bytes(b"ok")

        def runAndWait(self):
            return None

        def stop(self):
            raise RuntimeError("cannot stop")

    fake_module = types.SimpleNamespace(init=lambda: FakeEngine())
    monkeypatch.setattr("core.voice.pyttsx3", fake_module)

    class _TmpDir:
        def __init__(self, _prefix):
            self.path = tmp_path / "ttsdir2"

        def __enter__(self):
            self.path.mkdir(parents=True, exist_ok=True)
            return str(self.path)

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("core.voice.tempfile.TemporaryDirectory", lambda prefix: _TmpDir(prefix))

    adapter = _Pyttsx3Adapter()
    result = adapter._synthesize_sync("Selam", "x-voice")
    assert result["success"] is True
    assert result["audio_bytes"] == b"ok"


def test_pyttsx3_adapter_synthesize_sync_without_voice_skips_voice_selection(monkeypatch, tmp_path):
    class FakeEngine:
        def __init__(self):
            self.get_property_called = False

        def getProperty(self, _key):
            self.get_property_called = True
            return []

        def setProperty(self, _key, _value):
            return None

        def save_to_file(self, _text, output):
            Path(output).write_bytes(b"ok")

        def runAndWait(self):
            return None

        def stop(self):
            return None

    engine = FakeEngine()
    fake_module = types.SimpleNamespace(init=lambda: engine)
    monkeypatch.setattr("core.voice.pyttsx3", fake_module)

    class _TmpDir:
        def __init__(self, _prefix):
            self.path = tmp_path / "ttsdir3"

        def __enter__(self):
            self.path.mkdir(parents=True, exist_ok=True)
            return str(self.path)

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("core.voice.tempfile.TemporaryDirectory", lambda prefix: _TmpDir(prefix))

    adapter = _Pyttsx3Adapter()
    result = adapter._synthesize_sync("Selam", "")

    assert result["success"] is True
    assert engine.get_property_called is False


@pytest.mark.asyncio
async def test_pyttsx3_adapter_synthesize_available_path_uses_to_thread(monkeypatch):
    class FakeModule:
        @staticmethod
        def init():
            raise AssertionError("init should not be called in this test")

    monkeypatch.setattr("core.voice.pyttsx3", FakeModule())
    adapter = _Pyttsx3Adapter()
    assert adapter.available is True

    called = {}

    async def fake_to_thread(fn, text, voice):
        called["args"] = (fn, text, voice)
        return {"success": True, "provider": "pyttsx3"}

    monkeypatch.setattr("core.voice.asyncio.to_thread", fake_to_thread)
    result = await adapter.synthesize("hello", voice="v1")

    assert result["success"] is True
    assert called["args"][0] == adapter._synthesize_sync
    assert called["args"][1:] == ("hello", "v1")


# ──────────────────────────────────────────────────────────────────────────────
# _build_tts_adapter
# ──────────────────────────────────────────────────────────────────────────────

def test_build_tts_adapter_mock():
    adapter = _build_tts_adapter("mock")
    assert isinstance(adapter, _MockTTSAdapter)


def test_build_tts_adapter_pyttsx3():
    adapter = _build_tts_adapter("pyttsx3")
    assert isinstance(adapter, _Pyttsx3Adapter)


def test_build_tts_adapter_auto_returns_pyttsx3():
    adapter = _build_tts_adapter("auto")
    assert isinstance(adapter, _Pyttsx3Adapter)


def test_build_tts_adapter_auto_prefers_available_pyttsx3(monkeypatch):
    monkeypatch.setattr(_Pyttsx3Adapter, "available", property(lambda self: True))
    adapter = _build_tts_adapter("auto")
    assert isinstance(adapter, _Pyttsx3Adapter)


def test_build_tts_adapter_empty_string_treated_as_auto():
    adapter = _build_tts_adapter("")
    assert isinstance(adapter, _Pyttsx3Adapter)


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
    cfg.ENABLE_MULTIMODAL = cfg_attrs.get("enable_multimodal", True)
    cfg.VOICE_ENABLED = cfg_attrs.get("voice_enabled", True)
    return VoicePipeline(cfg)


def test_pipeline_init_mock_provider():
    p = _make_pipeline(provider="mock")
    assert p.provider == "mock"
    assert p.enabled is True


def test_pipeline_init_no_config():
    p = VoicePipeline(None)
    assert p.provider == "pyttsx3"


def test_pipeline_init_respects_disable_flags():
    p = _make_pipeline(enable_multimodal=False)
    assert p.enabled is False
    assert "ENABLE_MULTIMODAL" in p.voice_disabled_reason


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


def test_extract_ready_segments_skips_empty_parts_from_split(monkeypatch):
    p = _make_pipeline(segment_chars=500)

    class _FakeBoundary:
        @staticmethod
        def split(_text):
            return ["İlk", "   ", "Son"]

    monkeypatch.setattr("core.voice.re.compile", lambda _pattern: _FakeBoundary())
    segs, remainder = p.extract_ready_segments("dummy")
    assert segs == ["İlk"]
    assert remainder == "Son"


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


def test_buffer_assistant_text_empty_delta_keeps_buffer_and_emits_when_probe_ready():
    p = _make_pipeline(segment_chars=5, buffer_chars=500)
    state = p.create_duplex_state()
    p.begin_assistant_turn(state)
    state.output_text_buffer = "Uzun birikmiş metin kesinlikle yirmi karakterden fazladır."

    turn_id, packets = p.buffer_assistant_text(state, "", flush=False)

    assert turn_id == 1
    assert packets
    assert state.output_text_buffer == ""


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


def test_interrupt_assistant_turn_does_not_track_zero_turn_id():
    p = _make_pipeline()
    state = p.create_duplex_state()
    state.output_text_buffer = "abc"
    result = p.interrupt_assistant_turn(state, reason="stop")

    assert result["assistant_turn_id"] == 0
    assert state.interrupted_turns == []


def test_should_interrupt_response_voice_event_below_threshold():
    p = _make_pipeline(vad_enabled=True, duplex_enabled=True, vad_interrupt_min_bytes=300)
    assert p.should_interrupt_response(100, event="speech") is False


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


@pytest.mark.asyncio
async def test_synthesize_text_degrades_gracefully_on_adapter_error():
    p = _make_pipeline(provider="mock")

    async def _boom(_text: str, *, voice: str = "") -> dict:
        _ = voice
        raise RuntimeError("device lost")

    p.adapter.synthesize = _boom  # type: ignore[assignment]
    first = await p.synthesize_text("Merhaba")
    assert first["success"] is False
    assert "Voice Disabled" in first["reason"]
    assert p.enabled is False

    second = await p.synthesize_text("Tekrar")
    assert second["success"] is False
    assert second["reason"] == p.voice_disabled_reason


def test_webrtc_audio_ingress_decode_packet_success():
    ingress = WebRTCAudioIngress()
    packet = ingress.decode_packet(
        {
            "audio_chunk": base64.b64encode(b"abc123").decode("ascii"),
            "mime_type": "audio/webm",
            "sequence": 5,
            "sample_rate_hz": 16000,
            "channels": 1,
            "duration_ms": 120,
            "session_id": "s1",
            "client_id": "c1",
        }
    )
    assert isinstance(packet, BrowserAudioPacket)
    assert packet.audio_bytes == b"abc123"
    assert packet.sequence == 5
    assert packet.mime_type == "audio/webm"


def test_webrtc_audio_ingress_decode_packet_rejects_invalid_base64():
    ingress = WebRTCAudioIngress()
    with pytest.raises(ValueError, match="base64"):
        ingress.decode_packet({"audio_chunk": "***not-base64***", "mime_type": "audio/webm"})


def test_webrtc_audio_ingress_decode_packet_rejects_unsupported_mime():
    ingress = WebRTCAudioIngress()
    payload = {"audio_chunk": base64.b64encode(b"raw").decode("ascii"), "mime_type": "application/octet-stream"}
    with pytest.raises(ValueError, match="Desteklenmeyen"):
        ingress.decode_packet(payload)


# ──────────────────────────────────────────────────────────────────────────────
# Eksik Kapsam (Coverage) Testleri: WebRTCAudioIngress Edge Caseleri
# ──────────────────────────────────────────────────────────────────────────────

def test_webrtc_audio_ingress_decode_packet_empty_audio_data():
    """Satır 356 ve 385'i kapsar: Ses verisi boş veya anlamsız gönderildiğinde."""
    ingress = WebRTCAudioIngress()

    # 1) 'audio_chunk' string ama boşluklardan ibaret.
    with pytest.raises(ValueError, match="boş ses verisi içeriyor"):
        ingress.decode_packet({"audio_chunk": "   ", "mime_type": "audio/webm"})

    # 2) 'audio_chunk' string değil.
    with pytest.raises(ValueError, match="boş ses verisi içeriyor"):
        ingress.decode_packet({"audio_chunk": None, "mime_type": "audio/webm"})


def test_webrtc_audio_ingress_decode_packet_exceeds_max_bytes():
    """Satır 358'i kapsar: Ses verisi belirtilen byte limitini aştığında."""
    ingress = WebRTCAudioIngress()
    ingress.max_chunk_bytes = 10

    payload = {"audio_bytes": b"123456789012345", "mime_type": "audio/webm"}
    with pytest.raises(ValueError, match="limiti aşıldı"):
        ingress.decode_packet(payload)


def test_webrtc_audio_ingress_decode_packet_direct_bytes():
    """Satır 381'i kapsar: 'audio_bytes' doğrudan byte/bytearray formatında gelirse."""
    ingress = WebRTCAudioIngress()
    payload = {"audio_bytes": bytearray(b"direct_byte_data"), "mime_type": "audio/webm", "sequence": 1}

    packet = ingress.decode_packet(payload)
    assert packet.audio_bytes == b"direct_byte_data"
    assert packet.mime_type == "audio/webm"


def test_webrtc_audio_ingress_decode_packet_alternate_keys():
    """_decode_audio_bytes içindeki 'audio_b64' ve 'data' alternatif anahtarlarını kapsar."""
    ingress = WebRTCAudioIngress()

    payload_b64 = {"audio_b64": base64.b64encode(b"b64data").decode("ascii"), "mime_type": "audio/wav"}
    packet1 = ingress.decode_packet(payload_b64)
    assert packet1.audio_bytes == b"b64data"

    payload_data = {"data": base64.b64encode(b"datavalue").decode("ascii"), "mime_type": "audio/mp3"}
    packet2 = ingress.decode_packet(payload_data)
    assert packet2.audio_bytes == b"datavalue"
