"""Sidar Project — Voice/TTS yardımcıları.

Text-to-Speech adaptörleri ve websocket tarafında kademeli ses yanıtı üretmek
için kullanılacak ortak yardımcı sınıfları içerir.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyttsx3


class _BaseTTSAdapter:
    provider = "base"

    @property
    def available(self) -> bool:
        return True

    async def synthesize(self, text: str, *, voice: str = "") -> dict[str, Any]:
        raise NotImplementedError


class _MockTTSAdapter(_BaseTTSAdapter):
    provider = "mock"

    async def synthesize(self, text: str, *, voice: str = "") -> dict[str, Any]:
        payload = (text or "").strip().encode("utf-8")
        return {
            "success": bool(payload),
            "audio_bytes": payload,
            "mime_type": "audio/mock",
            "provider": self.provider,
            "voice": voice,
            "reason": "" if payload else "Boş metin için TTS üretilmedi.",
        }


class _Pyttsx3Adapter(_BaseTTSAdapter):
    provider = "pyttsx3"

    def __init__(self) -> None:
        self._import_error = ""

    @property
    def available(self) -> bool:
        return True

    def _synthesize_sync(self, text: str, voice: str) -> dict[str, Any]:
        engine = pyttsx3.init()
        if voice:
            for candidate in engine.getProperty("voices") or []:
                candidate_id = str(getattr(candidate, "id", "") or "")
                candidate_name = str(getattr(candidate, "name", "") or "")
                if voice.lower() in candidate_id.lower() or voice.lower() in candidate_name.lower():
                    engine.setProperty("voice", candidate_id)
                    break

        with tempfile.TemporaryDirectory(prefix="sidar-tts-") as tmpdir:
            output = Path(tmpdir) / "speech.wav"
            engine.save_to_file(text, str(output))
            engine.runAndWait()
            audio_bytes = output.read_bytes() if output.exists() else b""
        try:
            engine.stop()
        except Exception:
            pass
        return {
            "success": bool(audio_bytes),
            "audio_bytes": audio_bytes,
            "mime_type": "audio/wav",
            "provider": self.provider,
            "voice": voice,
            "reason": "" if audio_bytes else "pyttsx3 çıktı üretemedi.",
        }

    async def synthesize(self, text: str, *, voice: str = "") -> dict[str, Any]:
        return await asyncio.to_thread(self._synthesize_sync, text, voice)


def _build_tts_adapter(provider: str) -> _BaseTTSAdapter:
    normalized = (provider or "auto").strip().lower()
    if normalized == "mock":
        return _MockTTSAdapter()
    return _Pyttsx3Adapter()


class VoicePipeline:
    """Websocket voice akışı için TTS adaptörü ve segmentleme yardımcıları."""

    INTERRUPT_EVENTS = {"speech_start", "speech", "user_speaking", "barge_in", "interrupt"}
    COMMIT_EVENTS = {"speech_end", "speech_ended", "end_of_turn", "silence", "vad_commit"}

    def __init__(self, config: Any = None) -> None:
        provider = str(getattr(config, "VOICE_TTS_PROVIDER", "auto") or "auto")
        self.multimodal_enabled = bool(getattr(config, "ENABLE_MULTIMODAL", True))
        self.voice_enabled = bool(getattr(config, "VOICE_ENABLED", True))
        self.voice = str(getattr(config, "VOICE_TTS_VOICE", "") or "")
        self.segment_chars = max(20, int(getattr(config, "VOICE_TTS_SEGMENT_CHARS", 48) or 48))
        self.buffer_chars = max(
            self.segment_chars,
            int(
                getattr(config, "VOICE_TTS_BUFFER_CHARS", self.segment_chars * 2)
                or (self.segment_chars * 2)
            ),
        )
        self.vad_enabled = bool(getattr(config, "VOICE_VAD_ENABLED", True))
        self.vad_min_speech_bytes = max(
            256, int(getattr(config, "VOICE_VAD_MIN_SPEECH_BYTES", 1024) or 1024)
        )
        self.duplex_enabled = bool(getattr(config, "VOICE_DUPLEX_ENABLED", True))
        self.vad_interrupt_min_bytes = max(
            128,
            int(getattr(config, "VOICE_VAD_INTERRUPT_MIN_BYTES", 384) or 384),
        )
        self.adapter = _build_tts_adapter(provider)
        self.provider = self.adapter.provider
        self.voice_disabled_reason = ""
        if not self.multimodal_enabled:
            self.voice_disabled_reason = "ENABLE_MULTIMODAL devre dışı."
        elif not self.voice_enabled:
            self.voice_disabled_reason = "VOICE_ENABLED devre dışı."

    @property
    def enabled(self) -> bool:
        return bool(self.adapter.available) and not self.voice_disabled_reason

    def extract_ready_segments(self, buffer: str, *, flush: bool = False) -> tuple[list[str], str]:
        text = str(buffer or "")
        if not text.strip():
            return [], ""

        if flush:
            return ([text.strip()] if text.strip() else []), ""

        segments: list[str] = []
        remainder = text
        boundary = re.compile(r"(?<=[.!?。！？\n])\s+")
        parts = boundary.split(text)
        if len(parts) > 1:
            built = []
            for part in parts[:-1]:
                chunk = part.strip()
                if chunk:
                    built.append(chunk)
            segments.extend(built)
            remainder = parts[-1]

        if len(remainder.strip()) >= self.segment_chars:
            segments.append(remainder.strip())
            remainder = ""

        return segments, remainder

    @dataclass
    class DuplexState:
        assistant_turn_id: int = 0
        output_sequence: int = 0
        output_text_buffer: str = ""
        interrupted_turns: list[int] = field(default_factory=list)
        last_interrupt_reason: str = ""

    def create_duplex_state(self) -> VoicePipeline.DuplexState:
        return self.DuplexState()

    def begin_assistant_turn(self, state: VoicePipeline.DuplexState | None) -> int:
        if state is None:
            return 0
        state.assistant_turn_id += 1
        state.output_sequence = 0
        state.output_text_buffer = ""
        state.last_interrupt_reason = ""
        return state.assistant_turn_id

    def buffer_assistant_text(
        self,
        state: VoicePipeline.DuplexState | None,
        text: str,
        *,
        flush: bool = False,
    ) -> tuple[int, list[dict[str, Any]]]:
        if state is None:
            normalized = str(text or "")
            ready_segments, _remainder = self.extract_ready_segments(normalized, flush=flush)
            return 0, [
                {"assistant_turn_id": 0, "audio_sequence": idx, "text": segment}
                for idx, segment in enumerate(ready_segments, start=1)
            ]

        if text:
            state.output_text_buffer += str(text)

        emit_flush = flush
        if not emit_flush and len(state.output_text_buffer.strip()) < self.buffer_chars:
            probe_segments, _probe_remainder = self.extract_ready_segments(
                state.output_text_buffer, flush=False
            )
            if not probe_segments:
                return state.assistant_turn_id, []

        ready_segments, remainder = self.extract_ready_segments(
            state.output_text_buffer, flush=emit_flush
        )
        state.output_text_buffer = remainder
        packets: list[dict[str, Any]] = []
        for segment in ready_segments:
            state.output_sequence += 1
            packets.append(
                {
                    "assistant_turn_id": state.assistant_turn_id,
                    "audio_sequence": state.output_sequence,
                    "text": segment,
                }
            )
        return state.assistant_turn_id, packets

    def interrupt_assistant_turn(
        self,
        state: VoicePipeline.DuplexState | None,
        *,
        reason: str,
    ) -> dict[str, Any]:
        if state is None:
            return {
                "assistant_turn_id": 0,
                "dropped_text_chars": 0,
                "cancelled_audio_sequences": 0,
                "reason": str(reason or "").strip() or "interrupt",
            }

        dropped = len(state.output_text_buffer)
        cancelled_sequences = state.output_sequence
        turn_id = state.assistant_turn_id
        if turn_id:
            state.interrupted_turns.append(turn_id)
        state.output_text_buffer = ""
        state.output_sequence = 0
        state.last_interrupt_reason = str(reason or "").strip() or "interrupt"
        return {
            "assistant_turn_id": turn_id,
            "dropped_text_chars": dropped,
            "cancelled_audio_sequences": cancelled_sequences,
            "reason": state.last_interrupt_reason,
        }

    def should_commit_audio(self, buffered_bytes: int, *, event: str = "") -> bool:
        """Basit VAD benzeri karar: speech_end/silence olayı ve yeterli buffer varsa işle."""
        if not self.vad_enabled:
            return False
        normalized = str(event or "").strip().lower()
        if normalized not in self.COMMIT_EVENTS:
            return False
        return int(buffered_bytes or 0) >= self.vad_min_speech_bytes

    def should_interrupt_response(self, buffered_bytes: int, *, event: str = "") -> bool:
        """Full-duplex akışta yeni kullanıcı konuşması mevcut yanıtı kesmeli mi?"""
        if not self.vad_enabled or not self.duplex_enabled:
            return False
        normalized = str(event or "").strip().lower()
        if normalized not in self.INTERRUPT_EVENTS:
            return False
        return int(buffered_bytes or 0) >= self.vad_interrupt_min_bytes

    def build_voice_state_payload(
        self,
        *,
        event: str,
        buffered_bytes: int,
        sequence: int,
        duplex_state: VoicePipeline.DuplexState | None = None,
    ) -> dict[str, Any]:
        normalized = str(event or "").strip().lower() or "unknown"
        output_buffer_chars = len(getattr(duplex_state, "output_text_buffer", "") or "")
        assistant_turn_id = int(getattr(duplex_state, "assistant_turn_id", 0) or 0)
        return {
            "voice_state": normalized,
            "buffered_bytes": max(0, int(buffered_bytes or 0)),
            "sequence": max(0, int(sequence or 0)),
            "vad_enabled": self.vad_enabled,
            "auto_commit_ready": self.should_commit_audio(buffered_bytes, event=normalized),
            "duplex_enabled": self.duplex_enabled,
            "interrupt_ready": self.should_interrupt_response(buffered_bytes, event=normalized),
            "tts_enabled": self.enabled,
            "voice_disabled_reason": self.voice_disabled_reason,
            "assistant_turn_id": assistant_turn_id,
            "output_buffer_chars": output_buffer_chars,
            "last_interrupt_reason": str(getattr(duplex_state, "last_interrupt_reason", "") or ""),
        }

    async def synthesize_text(self, text: str) -> dict[str, Any]:
        normalized = (text or "").strip()
        if not normalized:
            return {
                "success": False,
                "audio_bytes": b"",
                "mime_type": "audio/mock",
                "provider": self.provider,
                "voice": self.voice,
                "reason": "Boş metin için TTS üretilmedi.",
            }
        if not self.enabled:
            return {
                "success": False,
                "audio_bytes": b"",
                "mime_type": "audio/mock",
                "provider": self.provider,
                "voice": self.voice,
                "reason": self.voice_disabled_reason or "Voice pipeline devre dışı.",
            }
        try:
            return await self.adapter.synthesize(normalized, voice=self.voice)
        except Exception as exc:
            self.voice_disabled_reason = f"Voice Disabled: {exc.__class__.__name__}"
            return {
                "success": False,
                "audio_bytes": b"",
                "mime_type": "audio/mock",
                "provider": self.provider,
                "voice": self.voice,
                "reason": self.voice_disabled_reason,
            }


@dataclass(frozen=True)
class BrowserAudioPacket:
    """web_ui_react/WebRTC üzerinden gelen tarayıcı ses paketi."""

    audio_bytes: bytes
    mime_type: str
    sequence: int = 0
    sample_rate_hz: int = 48000
    channels: int = 1
    duration_ms: int = 0
    event: str = "media_chunk"
    transport: str = "webrtc"
    session_id: str = ""
    client_id: str = ""


class WebRTCAudioIngress:
    """Tarayıcı tabanlı WebRTC ses girişini OS bağımsız normalize eder."""

    SUPPORTED_MIME_TYPES = {
        "audio/webm",
        "audio/ogg",
        "audio/wav",
        "audio/x-wav",
        "audio/mp4",
        "audio/mpeg",
        "audio/mp3",
    }

    def __init__(self, config: Any = None) -> None:
        self.max_chunk_bytes = max(
            2048,
            int(
                getattr(config, "VOICE_WEBRTC_MAX_CHUNK_BYTES", 2 * 1024 * 1024)
                or (2 * 1024 * 1024)
            ),
        )
        self.default_mime_type = (
            str(getattr(config, "VOICE_WEBRTC_DEFAULT_MIME", "audio/webm") or "audio/webm")
            .strip()
            .lower()
        )
        self.default_sample_rate_hz = max(
            8000, int(getattr(config, "VOICE_WEBRTC_SAMPLE_RATE_HZ", 48000) or 48000)
        )
        self.default_channels = max(1, int(getattr(config, "VOICE_WEBRTC_CHANNELS", 1) or 1))

    def decode_packet(self, payload: dict[str, Any]) -> BrowserAudioPacket:
        raw_bytes = self._decode_audio_bytes(payload)
        if not raw_bytes:
            raise ValueError("WebRTC paketi boş ses verisi içeriyor.")
        if len(raw_bytes) > self.max_chunk_bytes:
            raise ValueError(
                f"WebRTC ses paketi limiti aşıldı: {len(raw_bytes)} > {self.max_chunk_bytes}"
            )

        mime_type = str(payload.get("mime_type") or self.default_mime_type).strip().lower()
        if mime_type not in self.SUPPORTED_MIME_TYPES:
            raise ValueError(f"Desteklenmeyen WebRTC ses formatı: {mime_type}")

        return BrowserAudioPacket(
            audio_bytes=raw_bytes,
            mime_type=mime_type,
            sequence=max(0, int(payload.get("sequence", 0) or 0)),
            sample_rate_hz=max(
                8000,
                int(
                    payload.get("sample_rate_hz", self.default_sample_rate_hz)
                    or self.default_sample_rate_hz
                ),
            ),
            channels=max(
                1, int(payload.get("channels", self.default_channels) or self.default_channels)
            ),
            duration_ms=max(0, int(payload.get("duration_ms", 0) or 0)),
            event=str(payload.get("event") or "media_chunk").strip().lower() or "media_chunk",
            transport=str(payload.get("transport") or "webrtc").strip().lower() or "webrtc",
            session_id=str(payload.get("session_id") or "").strip(),
            client_id=str(payload.get("client_id") or "").strip(),
        )

    @staticmethod
    def _decode_audio_bytes(payload: dict[str, Any]) -> bytes:
        direct = payload.get("audio_bytes")
        if isinstance(direct, (bytes, bytearray)):
            return bytes(direct)

        encoded = payload.get("audio_chunk") or payload.get("audio_b64") or payload.get("data")
        if not isinstance(encoded, str) or not encoded.strip():
            return b""
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("WebRTC ses paketi base64 decode edilemedi.") from exc
