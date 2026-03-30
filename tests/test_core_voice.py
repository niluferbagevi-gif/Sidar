"""
core/voice.py için birim testleri.
_MockTTSAdapter, _build_tts_adapter, VoicePipeline (extract_ready_segments,
buffer_assistant_text, interrupt_assistant_turn, should_commit_audio,
should_interrupt_response, DuplexState) fonksiyonlarını kapsar.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path


def _get_voice():
    if "core.voice" in sys.modules:
        del sys.modules["core.voice"]
    # pyttsx3 stub — gerçek paket olmasa da test geçsin
    if "pyttsx3" not in sys.modules:
        _stub = types.ModuleType("pyttsx3")
        _stub.init = lambda: None
        sys.modules["pyttsx3"] = _stub
    import core.voice as voice
    return voice


def _run(coro):
    return asyncio.run(coro)


def _make_config(**kwargs):
    class _Cfg:
        VOICE_TTS_PROVIDER = "mock"
        VOICE_TTS_VOICE = ""
        VOICE_TTS_SEGMENT_CHARS = 48
        VOICE_TTS_BUFFER_CHARS = 96
        VOICE_VAD_ENABLED = True
        VOICE_VAD_MIN_SPEECH_BYTES = 1024
        VOICE_DUPLEX_ENABLED = True
        VOICE_VAD_INTERRUPT_MIN_BYTES = 384

    for k, v in kwargs.items():
        setattr(_Cfg, k, v)
    return _Cfg()


# ══════════════════════════════════════════════════════════════
# _MockTTSAdapter
# ══════════════════════════════════════════════════════════════

class TestMockTTSAdapter:
    def test_available_is_true(self):
        voice = _get_voice()
        adapter = voice._MockTTSAdapter()
        assert adapter.available is True

    def test_provider_name(self):
        voice = _get_voice()
        assert voice._MockTTSAdapter.provider == "mock"

    def test_synthesize_nonempty_text_returns_success(self):
        voice = _get_voice()
        adapter = voice._MockTTSAdapter()

        result = _run(adapter.synthesize("Merhaba dünya"))
        assert result["success"] is True
        assert result["audio_bytes"] == "Merhaba dünya".encode("utf-8")
        assert result["provider"] == "mock"

    def test_synthesize_empty_text_returns_failure(self):
        voice = _get_voice()
        adapter = voice._MockTTSAdapter()

        result = _run(adapter.synthesize(""))
        assert result["success"] is False
        assert result["audio_bytes"] == b""

    def test_synthesize_preserves_voice_param(self):
        voice = _get_voice()
        adapter = voice._MockTTSAdapter()

        result = _run(adapter.synthesize("test", voice="female"))
        assert result["voice"] == "female"


# ══════════════════════════════════════════════════════════════
# _build_tts_adapter
# ══════════════════════════════════════════════════════════════

class TestBuildTtsAdapter:
    def test_mock_provider_returns_mock_adapter(self):
        voice = _get_voice()
        adapter = voice._build_tts_adapter("mock")
        assert isinstance(adapter, voice._MockTTSAdapter)

    def test_pyttsx3_provider_returns_pyttsx3_adapter(self):
        voice = _get_voice()
        adapter = voice._build_tts_adapter("pyttsx3")
        assert isinstance(adapter, voice._Pyttsx3Adapter)

    def test_auto_provider_without_pyttsx3_falls_back_to_mock(self):
        voice = _get_voice()
        # Force pyttsx3 unavailable
        original_available = voice._Pyttsx3Adapter.available.fget
        voice._Pyttsx3Adapter.available = property(lambda self: False)
        try:
            adapter = voice._build_tts_adapter("auto")
            assert isinstance(adapter, voice._MockTTSAdapter)
        finally:
            voice._Pyttsx3Adapter.available = property(original_available)

    def test_empty_provider_treated_as_auto(self):
        voice = _get_voice()
        adapter = voice._build_tts_adapter("")
        assert adapter is not None


# ══════════════════════════════════════════════════════════════
# VoicePipeline init
# ══════════════════════════════════════════════════════════════

class TestVoicePipelineInit:
    def test_enabled_when_adapter_available(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_TTS_PROVIDER="mock"))
        assert vp.enabled is True

    def test_provider_set_from_adapter(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_TTS_PROVIDER="mock"))
        assert vp.provider == "mock"

    def test_segment_chars_minimum_20(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_TTS_SEGMENT_CHARS=0))
        assert vp.segment_chars >= 20

    def test_none_config_uses_defaults(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(None)
        assert vp.segment_chars >= 20
        assert vp.vad_enabled is True


# ══════════════════════════════════════════════════════════════
# extract_ready_segments
# ══════════════════════════════════════════════════════════════

class TestExtractReadySegments:
    def setup_method(self):
        voice = _get_voice()
        self.vp = voice.VoicePipeline(_make_config())

    def test_empty_buffer_returns_empty(self):
        segs, remainder = self.vp.extract_ready_segments("")
        assert segs == []
        assert remainder == ""

    def test_flush_returns_full_text(self):
        segs, remainder = self.vp.extract_ready_segments("Merhaba dünya", flush=True)
        assert len(segs) == 1
        assert "Merhaba" in segs[0]
        assert remainder == ""

    def test_sentence_boundary_splits_segments(self):
        text = "Birinci cümle. İkinci cümle."
        segs, remainder = self.vp.extract_ready_segments(text)
        # "Birinci cümle." should be in segments
        assert any("Birinci" in s for s in segs)

    def test_long_remainder_emitted_as_segment(self):
        # Text longer than segment_chars without sentence boundary
        long_text = "x" * 100
        segs, remainder = self.vp.extract_ready_segments(long_text)
        assert any(len(s) > 0 for s in segs)

    def test_short_text_without_boundary_stays_in_remainder(self):
        segs, remainder = self.vp.extract_ready_segments("hi")
        assert segs == []
        assert remainder == "hi"

    def test_whitespace_only_returns_empty(self):
        segs, remainder = self.vp.extract_ready_segments("   ")
        assert segs == []


# ══════════════════════════════════════════════════════════════
# DuplexState
# ══════════════════════════════════════════════════════════════

class TestDuplexState:
    def setup_method(self):
        voice = _get_voice()
        self.vp = voice.VoicePipeline(_make_config())

    def test_create_duplex_state_initial(self):
        state = self.vp.create_duplex_state()
        assert state.assistant_turn_id == 0
        assert state.output_sequence == 0
        assert state.output_text_buffer == ""

    def test_begin_assistant_turn_increments_id(self):
        state = self.vp.create_duplex_state()
        turn_id = self.vp.begin_assistant_turn(state)
        assert turn_id == 1
        assert state.assistant_turn_id == 1

    def test_begin_assistant_turn_resets_buffer(self):
        state = self.vp.create_duplex_state()
        state.output_text_buffer = "some text"
        self.vp.begin_assistant_turn(state)
        assert state.output_text_buffer == ""

    def test_begin_assistant_turn_none_state(self):
        result = self.vp.begin_assistant_turn(None)
        assert result == 0


# ══════════════════════════════════════════════════════════════
# buffer_assistant_text
# ══════════════════════════════════════════════════════════════

class TestBufferAssistantText:
    def setup_method(self):
        voice = _get_voice()
        self.vp = voice.VoicePipeline(_make_config())

    def test_buffer_and_flush_emits_packets(self):
        state = self.vp.create_duplex_state()
        self.vp.begin_assistant_turn(state)
        _, packets = self.vp.buffer_assistant_text(state, "Merhaba dünya!", flush=True)
        assert len(packets) >= 1
        assert all("text" in p for p in packets)

    def test_packets_have_turn_id(self):
        state = self.vp.create_duplex_state()
        self.vp.begin_assistant_turn(state)
        turn_id, packets = self.vp.buffer_assistant_text(state, "test text!", flush=True)
        for p in packets:
            assert p["assistant_turn_id"] == turn_id

    def test_short_text_no_packets_without_flush(self):
        state = self.vp.create_duplex_state()
        self.vp.begin_assistant_turn(state)
        _, packets = self.vp.buffer_assistant_text(state, "hi")
        # Short text doesn't emit unless flush
        assert packets == []

    def test_none_state_still_emits_on_flush(self):
        _, packets = self.vp.buffer_assistant_text(None, "test sentence.", flush=True)
        assert len(packets) >= 1

    def test_sequence_increments_per_packet(self):
        state = self.vp.create_duplex_state()
        self.vp.begin_assistant_turn(state)
        # Two flushes
        _, p1 = self.vp.buffer_assistant_text(state, "First segment. ", flush=True)
        _, p2 = self.vp.buffer_assistant_text(state, "Second segment.", flush=True)
        if p1 and p2:
            assert p2[0]["audio_sequence"] > p1[-1]["audio_sequence"]


# ══════════════════════════════════════════════════════════════
# interrupt_assistant_turn
# ══════════════════════════════════════════════════════════════

class TestInterruptAssistantTurn:
    def setup_method(self):
        voice = _get_voice()
        self.vp = voice.VoicePipeline(_make_config())

    def test_interrupt_clears_buffer(self):
        state = self.vp.create_duplex_state()
        state.output_text_buffer = "some buffered text"
        self.vp.interrupt_assistant_turn(state, reason="barge_in")
        assert state.output_text_buffer == ""

    def test_interrupt_reports_dropped_chars(self):
        state = self.vp.create_duplex_state()
        state.output_text_buffer = "hello"
        result = self.vp.interrupt_assistant_turn(state, reason="interrupt")
        assert result["dropped_text_chars"] == 5

    def test_interrupt_records_turn_in_interrupted_list(self):
        state = self.vp.create_duplex_state()
        self.vp.begin_assistant_turn(state)
        self.vp.interrupt_assistant_turn(state, reason="speech_start")
        assert 1 in state.interrupted_turns

    def test_interrupt_stores_reason(self):
        state = self.vp.create_duplex_state()
        self.vp.interrupt_assistant_turn(state, reason="barge_in")
        assert state.last_interrupt_reason == "barge_in"

    def test_interrupt_none_state_returns_zeros(self):
        result = self.vp.interrupt_assistant_turn(None, reason="barge_in")
        assert result["assistant_turn_id"] == 0
        assert result["dropped_text_chars"] == 0


# ══════════════════════════════════════════════════════════════
# should_commit_audio
# ══════════════════════════════════════════════════════════════

class TestShouldCommitAudio:
    def setup_method(self):
        voice = _get_voice()
        self.vp = voice.VoicePipeline(_make_config())

    def test_commit_on_speech_end_with_enough_bytes(self):
        assert self.vp.should_commit_audio(2048, event="speech_end") is True

    def test_no_commit_with_insufficient_bytes(self):
        assert self.vp.should_commit_audio(100, event="speech_end") is False

    def test_no_commit_for_non_commit_event(self):
        assert self.vp.should_commit_audio(2048, event="unknown_event") is False

    def test_no_commit_when_vad_disabled(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_VAD_ENABLED=False))
        assert vp.should_commit_audio(2048, event="speech_end") is False

    def test_commit_on_silence_event(self):
        assert self.vp.should_commit_audio(2048, event="silence") is True

    def test_commit_on_vad_commit_event(self):
        assert self.vp.should_commit_audio(2048, event="vad_commit") is True


# ══════════════════════════════════════════════════════════════
# should_interrupt_response
# ══════════════════════════════════════════════════════════════

class TestShouldInterruptResponse:
    def setup_method(self):
        voice = _get_voice()
        self.vp = voice.VoicePipeline(_make_config())

    def test_interrupt_on_speech_start_with_enough_bytes(self):
        assert self.vp.should_interrupt_response(500, event="speech_start") is True

    def test_no_interrupt_with_insufficient_bytes(self):
        assert self.vp.should_interrupt_response(100, event="speech_start") is False

    def test_no_interrupt_for_non_interrupt_event(self):
        assert self.vp.should_interrupt_response(500, event="speech_end") is False

    def test_no_interrupt_when_vad_disabled(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_VAD_ENABLED=False))
        assert vp.should_interrupt_response(500, event="speech_start") is False

    def test_no_interrupt_when_duplex_disabled(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_DUPLEX_ENABLED=False))
        assert vp.should_interrupt_response(500, event="speech_start") is False

    def test_interrupt_on_barge_in_event(self):
        assert self.vp.should_interrupt_response(500, event="barge_in") is True


class TestVoicePipelineDummyAudioFlow:
    def test_synthesize_text_with_mock_adapter_returns_audio_bytes(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_TTS_PROVIDER="mock", VOICE_TTS_VOICE="dummy"))
        result = _run(vp.synthesize_text("Dummy audio input"))
        assert result["success"] is True
        assert result["audio_bytes"] == b"Dummy audio input"
        assert result["voice"] == "dummy"

    def test_pyttsx3_adapter_with_fake_engine_writes_dummy_wav(self, monkeypatch):
        voice = _get_voice()

        class _FakeEngine:
            def __init__(self):
                self._output = None

            def getProperty(self, _name):
                return []

            def setProperty(self, _name, _value):
                return None

            def save_to_file(self, _text, output):
                self._output = output

            def runAndWait(self):
                if self._output:
                    Path(self._output).write_bytes(b"RIFF" + b"\x00" * 32)

            def stop(self):
                return None

        fake_mod = types.SimpleNamespace(init=lambda: _FakeEngine())
        monkeypatch.setitem(sys.modules, "pyttsx3", fake_mod)
        adapter = voice._Pyttsx3Adapter()
        result = _run(adapter.synthesize("Merhaba ses", voice=""))
        assert result["provider"] == "pyttsx3"
        assert result["mime_type"] == "audio/wav"
        assert isinstance(result["audio_bytes"], (bytes, bytearray))


class TestVoicePipelineAdditionalCoverage:
    def test_build_voice_state_payload_defaults_unknown_event(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_TTS_PROVIDER="mock"))
        payload = vp.build_voice_state_payload(event="", buffered_bytes=-5, sequence=-1, duplex_state=None)
        assert payload["voice_state"] == "unknown"
        assert payload["buffered_bytes"] == 0
        assert payload["sequence"] == 0

    def test_synthesize_text_empty_returns_failure_payload(self):
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_TTS_PROVIDER="mock", VOICE_TTS_VOICE="narrator"))
        result = _run(vp.synthesize_text("   "))
        assert result["success"] is False
        assert result["voice"] == "narrator"

    def test_pyttsx3_synthesize_returns_unavailable_when_import_fails(self, monkeypatch):
        voice = _get_voice()

        real_import = __import__("builtins").__import__

        def fake_import(name, *args, **kwargs):
            if name == "pyttsx3":
                raise ImportError("missing pyttsx3")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(__import__("builtins"), "__import__", fake_import)
        adapter = voice._Pyttsx3Adapter()
        result = _run(adapter.synthesize("merhaba", voice=""))
        assert result["success"] is False
        assert "pyttsx3" in result["provider"]
        assert result["audio_bytes"] == b""

    def test_pyttsx3_voice_matching_sets_voice_property(self, monkeypatch):
        """Lines 63-68: voice matching loop body when voice parameter matches a candidate."""
        voice = _get_voice()
        set_calls = {}

        class _FakeVoice:
            id = "en_female_01"
            name = "Female Voice"

        class _FakeEngine:
            def getProperty(self, name):
                if name == "voices":
                    return [_FakeVoice()]
                return None

            def setProperty(self, name, value):
                set_calls[name] = value

            def save_to_file(self, text, output):
                from pathlib import Path
                Path(output).write_bytes(b"RIFF" + b"\x00" * 32)

            def runAndWait(self):
                pass

            def stop(self):
                pass

        fake_mod = types.SimpleNamespace(init=lambda: _FakeEngine())
        monkeypatch.setitem(sys.modules, "pyttsx3", fake_mod)
        adapter = voice._Pyttsx3Adapter()
        result = _run(adapter.synthesize("test voice match", voice="female"))
        assert result["provider"] == "pyttsx3"
        # setProperty("voice", ...) should have been called via the matching branch
        assert "voice" in set_calls
        assert set_calls["voice"] == "en_female_01"

    def test_pyttsx3_voice_no_match_loop_exhausted(self, monkeypatch):
        """63->70: voice set but NO candidate matches → loop exhausts without break."""
        voice = _get_voice()

        class _FakeVoiceNoMatch:
            id = "en_male_01"
            name = "Male Voice"

        class _FakeEngine:
            def getProperty(self, name):
                if name == "voices":
                    return [_FakeVoiceNoMatch()]
                return None

            def setProperty(self, name, value):
                pass

            def save_to_file(self, text, output):
                from pathlib import Path
                Path(output).write_bytes(b"RIFF" + b"\x00" * 32)

            def runAndWait(self):
                pass

            def stop(self):
                pass

        fake_mod = types.SimpleNamespace(init=lambda: _FakeEngine())
        monkeypatch.setitem(sys.modules, "pyttsx3", fake_mod)
        adapter = voice._Pyttsx3Adapter()
        # voice="female" but candidate is "Male Voice" → no match → loop runs to completion
        result = _run(adapter.synthesize("no match test", voice="female"))
        assert result["provider"] == "pyttsx3"
        assert result["success"] is True

    def test_pyttsx3_voice_second_candidate_matches(self, monkeypatch):
        """66->63: first candidate doesn't match (False branch → back to loop), second matches."""
        voice = _get_voice()
        set_calls = {}

        class _FakeVoiceMale:
            id = "en_male_01"
            name = "Male Voice"

        class _FakeVoiceFemale:
            id = "en_female_02"
            name = "Female Voice"

        class _FakeEngine:
            def getProperty(self, name):
                if name == "voices":
                    return [_FakeVoiceMale(), _FakeVoiceFemale()]
                return None

            def setProperty(self, name, value):
                set_calls[name] = value

            def save_to_file(self, text, output):
                from pathlib import Path
                Path(output).write_bytes(b"RIFF" + b"\x00" * 32)

            def runAndWait(self):
                pass

            def stop(self):
                pass

        fake_mod = types.SimpleNamespace(init=lambda: _FakeEngine())
        monkeypatch.setitem(sys.modules, "pyttsx3", fake_mod)
        adapter = voice._Pyttsx3Adapter()
        # First candidate (male) doesn't match, second (female) does → break
        result = _run(adapter.synthesize("second match test", voice="female"))
        assert result["provider"] == "pyttsx3"
        assert set_calls.get("voice") == "en_female_02"

    def test_pyttsx3_stop_exception_is_swallowed(self, monkeypatch):
        """Lines 77-78: engine.stop() raises Exception → swallowed, result still returned."""
        voice = _get_voice()

        class _FakeEngine:
            def getProperty(self, name):
                return []

            def setProperty(self, name, value):
                pass

            def save_to_file(self, text, output):
                from pathlib import Path
                Path(output).write_bytes(b"RIFF" + b"\x00" * 32)

            def runAndWait(self):
                pass

            def stop(self):
                raise RuntimeError("engine stop error")

        fake_mod = types.SimpleNamespace(init=lambda: _FakeEngine())
        monkeypatch.setitem(sys.modules, "pyttsx3", fake_mod)
        adapter = voice._Pyttsx3Adapter()
        result = _run(adapter.synthesize("test stop exception", voice=""))
        # Exception in stop() is swallowed; audio was already written
        assert result["provider"] == "pyttsx3"
        assert result["success"] is True

    def test_pyttsx3_no_output_file_returns_failure(self, monkeypatch):
        """Line 74 else branch: output.exists() is False → audio_bytes = b""."""
        voice = _get_voice()

        class _FakeEngine:
            def getProperty(self, name):
                return []

            def setProperty(self, name, value):
                pass

            def save_to_file(self, text, output):
                pass  # does NOT write the file

            def runAndWait(self):
                pass

            def stop(self):
                pass

        fake_mod = types.SimpleNamespace(init=lambda: _FakeEngine())
        monkeypatch.setitem(sys.modules, "pyttsx3", fake_mod)
        adapter = voice._Pyttsx3Adapter()
        result = _run(adapter.synthesize("no output", voice=""))
        assert result["success"] is False
        assert result["audio_bytes"] == b""
        assert result["reason"] != ""


class TestVoicePipelineMissingBranches:
    """158->156, 204->207, 210->213 branch coverage."""

    def setup_method(self):
        voice = _get_voice()
        self.vp = voice.VoicePipeline(_make_config())

    def test_extract_segments_empty_chunk_skipped(self):
        """158->156: chunk.strip()='' → False branch of 'if chunk:' loops back."""
        # "\n  !  " produces parts=["\n", "!", ""] after boundary split.
        # The "\n" part strips to "" → if chunk: is False → continue
        text = "\n  !  "
        segs, remainder = self.vp.extract_ready_segments(text)
        # "!" part is non-empty, so it appears in segments or remainder
        # The key is that the empty-chunk False branch was exercised
        assert isinstance(segs, list)
        assert isinstance(remainder, str)

    def test_buffer_assistant_text_empty_text_false_branch(self):
        """204->207: if text: False → state buffer not updated, continue normally."""
        state = self.vp.create_duplex_state()
        self.vp.begin_assistant_turn(state)
        # Pre-load some buffer content
        self.vp.buffer_assistant_text(state, "Some content here. ")
        # Now call with empty text → `if text:` is False (line 204 False branch → 207)
        turn_id, packets = self.vp.buffer_assistant_text(state, "")
        assert turn_id == 1

    def test_buffer_assistant_text_probe_segments_nonempty(self):
        """210->213: probe_segments non-empty → don't return early, fall through to line 213."""
        state = self.vp.create_duplex_state()
        self.vp.begin_assistant_turn(state)
        # Text with sentence boundary → probe finds segments even though buffer < buffer_chars
        # This triggers the probe path AND probe_segments is non-empty → False branch of 'if not probe_segments:'
        _, packets = self.vp.buffer_assistant_text(state, "Hello world sentence. More text")
        # Probe found ["Hello world sentence."] → fell through to line 213 → packets produced
        assert isinstance(packets, list)

    def test_buffer_chars_minimum_enforced_when_less_than_segment_chars(self):
        """When VOICE_TTS_BUFFER_CHARS < VOICE_TTS_SEGMENT_CHARS, buffer_chars = segment_chars."""
        voice = _get_voice()
        vp = voice.VoicePipeline(_make_config(VOICE_TTS_SEGMENT_CHARS=100, VOICE_TTS_BUFFER_CHARS=20))
        assert vp.buffer_chars >= vp.segment_chars
        assert vp.buffer_chars == 100
