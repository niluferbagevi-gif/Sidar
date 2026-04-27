from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

# Bazı CI ortamlarında opentelemetry httpx enstrümantasyonu opsiyonel olabilir.
if "opentelemetry.instrumentation.httpx" not in sys.modules:
    fake_httpx_mod = SimpleNamespace(
        HTTPXClientInstrumentor=SimpleNamespace(instrument=lambda *a, **k: None)
    )
    sys.modules["opentelemetry.instrumentation.httpx"] = fake_httpx_mod


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import web_server
from web_server import app


class _VoiceMemory:
    def __len__(self) -> int:
        return 0

    async def set_active_user(self, _user_id: str, _username: str) -> None:
        return None


class _VoiceAgent:
    def __init__(self) -> None:
        self.llm = object()
        self.cfg = SimpleNamespace(AI_PROVIDER="test", USE_GPU=False)
        self.docs = SimpleNamespace(doc_count=0)
        self.memory = _VoiceMemory()
        self.VERSION = "test"

    async def respond(self, prompt: str):
        yield f"echo:{prompt}"


class _FakeMultimodalPipeline:
    next_result = {"success": True, "text": "sesli merhaba", "language": "tr", "provider": "fake"}

    def __init__(self, _llm, _cfg) -> None:
        return None

    async def transcribe_bytes(self, *_args, **_kwargs):
        return dict(self.next_result)


class _FakeVoicePipeline:
    enabled = False
    vad_enabled = True
    duplex_enabled = True

    def __init__(self, _cfg) -> None:
        self.voice_disabled_reason = ""

    def create_duplex_state(self):
        return SimpleNamespace(assistant_turn_id=0, output_text_buffer="", last_interrupt_reason="")

    def build_voice_state_payload(
        self, *, event: str, buffered_bytes: int, sequence: int, duplex_state
    ):
        return {
            "voice_state": event,
            "buffered_bytes": buffered_bytes,
            "sequence": sequence,
            "assistant_turn_id": int(getattr(duplex_state, "assistant_turn_id", 0) or 0),
        }

    def begin_assistant_turn(self, duplex_state) -> int:
        duplex_state.assistant_turn_id = int(getattr(duplex_state, "assistant_turn_id", 0) or 0) + 1
        return duplex_state.assistant_turn_id

    def should_interrupt_response(self, _buffered_bytes: int, *, event: str) -> bool:
        return event == "speech_start"

    def should_commit_audio(self, _buffered_bytes: int, *, event: str) -> bool:
        return event == "speech_end"

    def interrupt_assistant_turn(self, duplex_state, *, reason: str):
        duplex_state.last_interrupt_reason = reason
        return {
            "assistant_turn_id": int(getattr(duplex_state, "assistant_turn_id", 0) or 0),
            "dropped_text_chars": 0,
            "cancelled_audio_sequences": 0,
            "reason": reason,
        }


def _install_voice_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent = _VoiceAgent()

    async def _fake_get_agent():
        return fake_agent

    async def _fake_resolve(_agent, token: str):
        if token == "voice-token":
            return SimpleNamespace(id="u1", username="voice-user", role="user", tenant_id="default")
        return None

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.multimodal",
        SimpleNamespace(MultimodalPipeline=_FakeMultimodalPipeline),
    )
    monkeypatch.setitem(
        __import__("sys").modules, "core.voice", SimpleNamespace(VoicePipeline=_FakeVoicePipeline)
    )


@pytest.mark.integration
def test_voice_websocket_transcription_error_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_voice_mocks(monkeypatch)
    _FakeMultimodalPipeline.next_result = {"success": False, "reason": "stt failed"}

    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as websocket:
            websocket.send_json({"action": "auth", "token": "voice-token"})
            assert websocket.receive_json() == {"auth_ok": True}

            websocket.send_bytes(b"abc")
            assert websocket.receive_json()["buffered_bytes"] == 3
            websocket.receive_json()  # voice_state=chunk

            websocket.send_json({"action": "commit"})
            processed_state = websocket.receive_json()
            assert processed_state["voice_state"] == "processed"
            error_payload = websocket.receive_json()
            assert error_payload == {"error": "stt failed", "done": True}


@pytest.mark.integration
def test_voice_websocket_happy_path_and_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_voice_mocks(monkeypatch)
    _FakeMultimodalPipeline.next_result = {
        "success": True,
        "text": "merhaba",
        "language": "tr",
        "provider": "fake",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as websocket:
            websocket.send_json({"action": "auth", "token": "voice-token"})
            assert websocket.receive_json() == {"auth_ok": True}

            websocket.send_json({"action": "start", "mime_type": "audio/wav", "prompt": "deneme"})
            ready_payload = websocket.receive_json()
            assert ready_payload["voice_session"] == "ready"
            ready_state = websocket.receive_json()
            assert ready_state["voice_state"] == "ready"

            websocket.send_json({"action": "append_base64", "chunk": "%%%"})
            assert websocket.receive_json() == {
                "error": "Geçersiz base64 ses parçası",
                "done": True,
            }

            websocket.send_bytes(b"abc")
            assert websocket.receive_json()["buffered_bytes"] == 3
            websocket.receive_json()  # voice_state=chunk

            websocket.send_json({"action": "commit"})

            events = [websocket.receive_json() for _ in range(6)]
            assert events[0]["voice_state"] == "processed"
            assert events[1]["transcript"] == "merhaba"
            assert events[2]["assistant_turn"] == "started"
            assert events[3]["chunk"] == "echo:merhaba"
            assert events[4]["assistant_turn"] == "completed"
            assert events[5] == {"done": True}

            websocket.send_json({"action": "cancel"})
            cancel_state = websocket.receive_json()
            assert cancel_state["voice_state"] == "cancelled"
            assert websocket.receive_json() == {"cancelled": True, "done": True}
