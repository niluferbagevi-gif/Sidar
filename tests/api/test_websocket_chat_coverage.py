from __future__ import annotations

import pytest

import web_server


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed: list[tuple[int, str]] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        self.closed.append((code, reason))


class _FakeAgent:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def respond(self, _prompt: str):
        for chunk in self._chunks:
            yield chunk


class _FakeVoicePipeline:
    enabled = True

    def buffer_assistant_text(self, _state, text: str, *, flush: bool = False):
        if not text.strip():
            return 0, []
        return 7, [{"assistant_turn_id": 7, "audio_sequence": 1, "text": text}]

    async def synthesize_text(self, segment: str) -> dict:
        return {
            "success": True,
            "audio_bytes": f"audio:{segment}".encode("utf-8"),
            "mime_type": "audio/wav",
            "provider": "fake-tts",
            "voice": "test-voice",
        }


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_splits_tool_thought_and_chunk() -> None:
    ws = _FakeWebSocket()
    agent = _FakeAgent([
        "\x00TOOL:run_tests\x00",
        "\x00THOUGHT:need more context\x00",
        "normal chunk",
    ])

    await web_server._ws_stream_agent_text_response(ws, agent, "hello")

    assert ws.sent[0] == {"tool_call": "run_tests"}
    assert ws.sent[1] == {"thought": "need more context"}
    assert ws.sent[2] == {"chunk": "normal chunk"}


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_emits_audio_chunks_when_voice_pipeline_enabled() -> None:
    ws = _FakeWebSocket()
    ws._sidar_voice_pipeline = _FakeVoicePipeline()
    ws._sidar_voice_duplex_state = object()
    agent = _FakeAgent(["merhaba"])

    await web_server._ws_stream_agent_text_response(ws, agent, "hello")

    assert ws.sent[0] == {"chunk": "merhaba"}
    assert ws.sent[1]["audio_text"] == "merhaba"
    assert ws.sent[1]["audio_provider"] == "fake-tts"
    assert ws.sent[1]["audio_voice"] == "test-voice"
    assert ws.sent[1]["assistant_turn_id"] == 7
    assert ws.sent[1]["audio_sequence"] == 1


@pytest.mark.asyncio
async def test_ws_close_policy_violation_uses_close_code_1008() -> None:
    ws = _FakeWebSocket()

    await web_server._ws_close_policy_violation(ws, "Authentication required")

    assert ws.closed == [(1008, "Authentication required")]


@pytest.mark.asyncio
async def test_ws_close_policy_violation_ignores_websocket_without_close() -> None:
    class _NoCloseSocket:
        pass

    ws = _NoCloseSocket()
    await web_server._ws_close_policy_violation(ws, "ignored")


def test_collaboration_role_and_command_helpers() -> None:
    assert web_server._normalize_collaboration_role("ADMIN") == "admin"
    assert web_server._normalize_collaboration_role("unknown") == "user"
    assert web_server._collaboration_command_requires_write("delete file core/db.py") is True
    assert web_server._collaboration_command_requires_write("sadece özet paylaş") is False
    assert web_server._is_sidar_mention("@Sidar coverage artır") is True
    assert web_server._is_sidar_mention("Merhaba ekip") is False
