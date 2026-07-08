from __future__ import annotations

import asyncio
import base64
import builtins
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketState

from web.routes import ws_voice


class _Ws:
    def __init__(self, messages=None, headers=None) -> None:
        self.headers = headers or {}
        self.sent: list[dict[str, object]] = []
        self.accepted: list[str | None] = []
        self.closed: list[tuple[int, str]] = []
        self._messages = iter(messages or [])
        self.client_state = WebSocketState.CONNECTED

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted.append(subprotocol)

    async def close(self, code: int, reason: str) -> None:
        self.closed.append((code, reason))

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def receive(self) -> dict[str, object]:
        try:
            return next(self._messages)
        except StopIteration as exc:
            raise ws_voice.WebSocketDisconnect() from exc


class _WaitUntilSentWs(_Ws):
    def __init__(self, messages=None, *, expected_key: str, headers=None) -> None:
        super().__init__(messages, headers=headers)
        self.expected_key = expected_key

    async def receive(self) -> dict[str, object]:
        try:
            packet = next(self._messages)
        except StopIteration as exc:
            raise ws_voice.WebSocketDisconnect() from exc
        if packet.get("wait_for_expected"):
            for _ in range(100):
                if any(self.expected_key in payload for payload in self.sent):
                    break
                await asyncio.sleep(0.01)
            raise ws_voice.WebSocketDisconnect()
        return packet


class _NeverSendsWs(_Ws):
    """A websocket that accepts the connection but never sends any message."""

    async def receive(self) -> dict[str, object]:
        await asyncio.sleep(999)
        return {"type": "websocket.receive", "text": "{}"}  # pragma: no cover - unreachable


class _RepeatedGarbageWs(_Ws):
    """A websocket that keeps sending unparseable junk fast enough to reset

    a naive per-message timeout, without ever authenticating."""

    async def receive(self) -> dict[str, object]:
        await asyncio.sleep(0.001)
        return {"text": "not json"}


class _Logger:
    def exception(self, *_args, **_kwargs) -> None:
        return None

    def warning(self, *_args, **_kwargs) -> None:
        return None

    def info(self, *_args, **_kwargs) -> None:
        return None

    def debug(self, *_args, **_kwargs) -> None:
        return None


class _MultimodalPipeline:
    def __init__(self, *_args, **_kwargs) -> None:
        return None


class _VoicePipeline:
    enabled = True
    vad_enabled = True
    duplex_enabled = True

    def __init__(self, *_args, **_kwargs) -> None:
        return None

    def create_duplex_state(self) -> dict[str, object]:
        return {"turn": 0}

    def build_voice_state_payload(self, *_args, **_kwargs) -> dict[str, object]:
        return {"enabled": True}

    def begin_assistant_turn(self, duplex_state) -> int:
        if isinstance(duplex_state, dict):
            duplex_state["assistant_turn_id"] = int(duplex_state.get("assistant_turn_id", 0) or 0) + 1
            return int(duplex_state["assistant_turn_id"])
        return 1

    def interrupt_assistant_turn(self, duplex_state, *, reason: str) -> dict[str, object]:
        assistant_turn_id = 0
        if isinstance(duplex_state, dict):
            assistant_turn_id = int(duplex_state.get("assistant_turn_id", 0) or 0)
            duplex_state["last_interrupt_reason"] = reason
        return {
            "assistant_turn_id": assistant_turn_id,
            "dropped_text_chars": 0,
            "cancelled_audio_sequences": 0,
            "reason": reason,
        }

    def should_interrupt_response(self, buffered_bytes: int, *, event: str) -> bool:
        return bool(buffered_bytes and event == "speech_start")

    def should_commit_audio(self, buffered_bytes: int, *, event: str) -> bool:
        return bool(buffered_bytes and event in {"speech_end", "vad_commit"})


def _deps(**overrides) -> SimpleNamespace:
    async def _set_active_user(*_args):
        return None

    async def _resolve_agent_instance():
        return SimpleNamespace(
            llm=object(), memory=SimpleNamespace(set_active_user=_set_active_user)
        )

    async def _close(websocket, reason: str) -> None:
        await websocket.close(code=1008, reason=reason)

    deps = SimpleNamespace(
        anyio_closed=(),
        await_if_needed=lambda value: value,
        cfg=SimpleNamespace(VOICE_WS_MAX_BYTES=8),
        llm_api_error_cls=RuntimeError,
        logger=_Logger(),
        resolve_agent_instance=_resolve_agent_instance,
        resolve_user_from_token=lambda _agent, _token: None,
        ws_close_policy_violation=_close,
        ws_stream_agent_text_response=lambda *_args, **_kwargs: None,
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


@pytest.mark.asyncio
async def test_websocket_voice_import_error_closes_connection(monkeypatch) -> None:
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            raise ImportError("missing multimodal")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ws = _Ws()

    await ws_voice.websocket_voice(ws, _deps())

    assert ws.accepted == [None]
    assert ws.sent == [{"error": "core.multimodal modülü yüklenemedi.", "done": True}]
    assert ws.closed == [(1011, "multimodal unavailable")]


@pytest.mark.asyncio
async def test_websocket_voice_rejects_binary_before_auth(monkeypatch) -> None:
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            return SimpleNamespace(MultimodalPipeline=_MultimodalPipeline)
        if name == "core.voice":
            return SimpleNamespace(VoicePipeline=_VoicePipeline)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ws = _Ws([{"bytes": b"abc"}])

    await ws_voice.websocket_voice(ws, _deps())

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Authentication required")]


@pytest.mark.asyncio
async def test_websocket_voice_closes_idle_unauthenticated_connection_after_timeout(
    monkeypatch,
) -> None:
    """Regression test: an unauthenticated client that never sends anything

    must not keep the connection open forever (slow DoS / resource exhaustion).
    """
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            return SimpleNamespace(MultimodalPipeline=_MultimodalPipeline)
        if name == "core.voice":
            return SimpleNamespace(VoicePipeline=_VoicePipeline)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ws = _NeverSendsWs()

    await asyncio.wait_for(
        ws_voice.websocket_voice(
            ws, _deps(cfg=SimpleNamespace(VOICE_WS_MAX_BYTES=8, WS_AUTH_TIMEOUT_SECONDS=0.05))
        ),
        timeout=5,
    )

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Authentication timeout")]


@pytest.mark.asyncio
async def test_websocket_voice_auth_timeout_is_absolute_not_reset_by_junk_messages(
    monkeypatch,
) -> None:
    """Regression test: repeatedly sending unparseable junk must not let an

    unauthenticated client reset the auth timeout and stay connected forever.
    """
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            return SimpleNamespace(MultimodalPipeline=_MultimodalPipeline)
        if name == "core.voice":
            return SimpleNamespace(VoicePipeline=_VoicePipeline)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ws = _RepeatedGarbageWs()

    await asyncio.wait_for(
        ws_voice.websocket_voice(
            ws, _deps(cfg=SimpleNamespace(VOICE_WS_MAX_BYTES=8, WS_AUTH_TIMEOUT_SECONDS=0.05))
        ),
        timeout=5,
    )

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Authentication timeout")]


@pytest.mark.asyncio
async def test_websocket_voice_rejects_oversized_binary_after_auth(monkeypatch) -> None:
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            return SimpleNamespace(MultimodalPipeline=_MultimodalPipeline)
        if name == "core.voice":
            return SimpleNamespace(VoicePipeline=_VoicePipeline)
        return original_import(name, *args, **kwargs)

    async def _resolve_user(_agent, token: str):
        assert token == "voice-token"
        return SimpleNamespace(id="u1", username="ada")

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ws = _Ws(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"123456789"},
        ]
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_resolve_user))

    assert {"auth_ok": True} in ws.sent
    assert ws.closed == [(1008, "Voice payload too large")]


@pytest.mark.asyncio
async def test_websocket_voice_does_not_transcribe_after_disconnect(monkeypatch) -> None:
    original_import = builtins.__import__
    calls = {"transcribe": 0}

    class _DisconnectAwareMultimodalPipeline:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def transcribe_bytes(self, *_args, **_kwargs):
            calls["transcribe"] += 1
            return {"success": True, "text": "hello"}

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            return SimpleNamespace(MultimodalPipeline=_DisconnectAwareMultimodalPipeline)
        if name == "core.voice":
            return SimpleNamespace(VoicePipeline=_VoicePipeline)
        return original_import(name, *args, **kwargs)

    async def _resolve_user(_agent, token: str):
        assert token == "voice-token"
        return SimpleNamespace(id="u1", username="ada")

    ws = _Ws(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
        ]
    )

    async def _send_and_disconnect(payload: dict[str, object]) -> None:
        ws.sent.append(payload)
        if payload == {"auth_ok": True}:
            ws.client_state = WebSocketState.DISCONNECTED

    ws.send_json = _send_and_disconnect  # type: ignore[method-assign]
    monkeypatch.setattr(builtins, "__import__", _fake_import)

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_resolve_user))

    assert {"auth_ok": True} in ws.sent
    assert calls["transcribe"] == 0


@pytest.mark.asyncio
async def test_websocket_voice_uses_default_header_token_extractor_without_echo(
    monkeypatch,
) -> None:
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            return SimpleNamespace(MultimodalPipeline=_MultimodalPipeline)
        if name == "core.voice":
            return SimpleNamespace(VoicePipeline=_VoicePipeline)
        return original_import(name, *args, **kwargs)

    async def _resolve_user(_agent, token: str):
        assert token == "voice-token"
        return SimpleNamespace(id="u1", username="ada")

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ws = _Ws(
        headers={"sec-websocket-protocol": "voice-token"},
        messages=[{"type": "websocket.disconnect"}],
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_resolve_user))

    assert ws.accepted == [None]
    assert {"auth_ok": True} in ws.sent


def _install_voice_imports(monkeypatch, pipeline_cls, voice_pipeline_cls=_VoicePipeline) -> None:
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            return SimpleNamespace(MultimodalPipeline=pipeline_cls)
        if name == "core.voice":
            return SimpleNamespace(VoicePipeline=voice_pipeline_cls)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)


def _install_multimodal_only(monkeypatch, pipeline_cls) -> None:
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            return SimpleNamespace(MultimodalPipeline=pipeline_cls)
        if name == "core.voice":
            raise ImportError("voice unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)


async def _voice_user(_agent, token: str):
    assert token == "voice-token"
    return SimpleNamespace(id="u1", username="ada")


class _SuccessfulTranscriptionPipeline:
    def __init__(self, *_args, **_kwargs) -> None:
        return None

    async def transcribe_bytes(self, *_args, **_kwargs):
        return {"success": True, "text": "hello", "language": "tr", "provider": "mock"}


@pytest.mark.asyncio
async def test_websocket_voice_reports_empty_audio_commit(monkeypatch) -> None:
    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _Ws(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"text": '{"action":"commit"}'},
        ]
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert {"auth_ok": True} in ws.sent
    assert {"error": "İşlenecek ses verisi bulunamadı.", "done": True} in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_rejects_missing_auth_token(monkeypatch) -> None:
    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _Ws([{"text": '{"action":"auth","token":"   "}'}])

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Authentication token missing")]


@pytest.mark.asyncio
async def test_websocket_voice_rejects_invalid_auth_token(monkeypatch) -> None:
    async def _resolve_user(_agent, token: str):
        assert token == "bad-token"
        return None

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _Ws([{"text": '{"action":"auth","token":"bad-token"}'}])

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_resolve_user))

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Invalid or expired token")]


@pytest.mark.asyncio
async def test_websocket_voice_rejects_invalid_header_token(monkeypatch) -> None:
    async def _resolve_user(_agent, token: str):
        assert token == "bad-header-token"
        return None

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _Ws(
        headers={"sec-websocket-protocol": "voice, bad-header-token"},
        messages=[{"type": "websocket.disconnect"}],
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(
            extract_ws_header_token=lambda _header, _protocol: ("bad-header-token", "voice"),
            resolve_user_from_token=_resolve_user,
        ),
    )

    assert ws.accepted == ["voice"]
    assert ws.closed == [(1008, "Invalid or expired token")]


@pytest.mark.asyncio
async def test_websocket_voice_ignores_bad_json_then_accepts_auth(monkeypatch) -> None:
    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _Ws(
        [
            {"text": "not json"},
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"type": "websocket.disconnect"},
        ]
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert {"auth_ok": True} in ws.sent
    assert ws.closed == []


@pytest.mark.asyncio
async def test_websocket_voice_reports_invalid_base64_chunk(monkeypatch) -> None:
    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _Ws(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"text": '{"action":"append_base64","chunk":"not@@base64"}'},
            {"type": "websocket.disconnect"},
        ]
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert {"error": "Geçersiz base64 ses parçası", "done": True} in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_rejects_oversized_base64_chunk(monkeypatch) -> None:
    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    chunk = base64.b64encode(b"123456789").decode()
    ws = _Ws(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"text": f'{{"action":"append_base64","chunk":"{chunk}"}}'},
        ]
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert ws.closed == [(1008, "Voice payload too large")]


@pytest.mark.asyncio
async def test_websocket_voice_start_resets_session_and_buffers_base64(monkeypatch) -> None:
    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    chunk = base64.b64encode(b"abc").decode()
    ws = _Ws(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {
                "text": (
                    '{"action":"start","mime_type":"audio/wav",'
                    '"language":"tr","prompt":"kisa"}'
                )
            },
            {"text": f'{{"action":"append_base64","chunk":"{chunk}"}}'},
            {"type": "websocket.disconnect"},
        ]
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert {
        "voice_session": "ready",
        "mime_type": "audio/wav",
        "duplex": True,
        "vad_enabled": True,
        "tts_enabled": True,
        "voice_disabled_reason": "",
    } in ws.sent
    assert {"buffered_bytes": 3} in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_uses_generic_state_payload_without_voice_pipeline(
    monkeypatch,
) -> None:
    _install_multimodal_only(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _Ws(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"text": '{"action":"start"}'},
            {"type": "websocket.disconnect"},
        ]
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert any(payload.get("voice_state") == "ready" for payload in ws.sent)
    assert any(payload.get("tts_enabled") is False for payload in ws.sent)


@pytest.mark.asyncio
async def test_websocket_voice_cancel_action_without_active_response_sends_done(
    monkeypatch,
) -> None:
    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _Ws(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"text": '{"action":"cancel"}'},
            {"type": "websocket.disconnect"},
        ]
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert any(payload.get("enabled") is True for payload in ws.sent)
    assert {"cancelled": True, "done": True} in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_cancel_action_cancels_active_response(monkeypatch) -> None:
    first_stream_started = asyncio.Event()

    async def _stream(*_args, **_kwargs) -> None:
        first_stream_started.set()
        await asyncio.sleep(999)

    class _CancelAfterStreamWs(_Ws):
        async def receive(self) -> dict[str, object]:
            try:
                packet = next(self._messages)
            except StopIteration as exc:
                raise ws_voice.WebSocketDisconnect() from exc
            if packet.get("wait_for_stream"):
                await asyncio.wait_for(first_stream_started.wait(), timeout=1)
                return {"text": '{"action":"cancel"}'}
            return packet

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _CancelAfterStreamWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
            {"wait_for_stream": True},
            {"type": "websocket.disconnect"},
        ]
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(
            resolve_user_from_token=_voice_user,
            ws_stream_agent_text_response=_stream,
        ),
    )

    assert any(
        payload.get("voice_interruption") == "user_cancelled"
        and payload.get("cancelled") is True
        for payload in ws.sent
    )
    assert {"cancelled": True, "done": True} in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_vad_barge_in_cancels_active_response(monkeypatch) -> None:
    first_stream_started = asyncio.Event()

    async def _stream(*_args, **_kwargs) -> None:
        first_stream_started.set()
        await asyncio.sleep(999)

    class _BargeInAfterStreamWs(_Ws):
        async def receive(self) -> dict[str, object]:
            try:
                packet = next(self._messages)
            except StopIteration as exc:
                raise ws_voice.WebSocketDisconnect() from exc
            if packet.get("wait_for_stream"):
                await asyncio.wait_for(first_stream_started.wait(), timeout=1)
                return {"text": '{"action":"vad_event","state":"speech_start"}'}
            return packet

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _BargeInAfterStreamWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
            {"bytes": b"x"},
            {"wait_for_stream": True},
            {"type": "websocket.disconnect"},
        ]
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(
            cfg=SimpleNamespace(VOICE_WS_MAX_BYTES=32),
            resolve_user_from_token=_voice_user,
            ws_stream_agent_text_response=_stream,
        ),
    )

    assert any(
        payload.get("voice_interruption") == "barge_in" and payload.get("cancelled") is True
        for payload in ws.sent
    )


@pytest.mark.asyncio
async def test_websocket_voice_vad_speech_end_commits_buffer(monkeypatch) -> None:
    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _WaitUntilSentWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"vad_event","state":"speech_end"}'},
            {"wait_for_expected": True},
        ],
        expected_key="transcript",
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert {"transcript": "hello", "language": "tr", "provider": "mock"} in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_reports_transcription_failure(monkeypatch) -> None:
    class _FailingTranscriptionPipeline:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def transcribe_bytes(self, *_args, **_kwargs):
            return {"success": False, "reason": "bad audio"}

    _install_voice_imports(monkeypatch, _FailingTranscriptionPipeline)
    ws = _WaitUntilSentWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
            {"wait_for_expected": True},
        ],
        expected_key="error",
    )

    await ws_voice.websocket_voice(ws, _deps(resolve_user_from_token=_voice_user))

    assert {"error": "bad audio", "done": True} in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_finishes_empty_transcript_without_llm(monkeypatch) -> None:
    calls = {"stream": 0}

    class _EmptyTranscriptPipeline:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def transcribe_bytes(self, *_args, **_kwargs):
            return {"success": True, "text": "   ", "language": "tr", "provider": "mock"}

    async def _stream(*_args, **_kwargs) -> None:
        calls["stream"] += 1

    _install_voice_imports(monkeypatch, _EmptyTranscriptPipeline)
    ws = _WaitUntilSentWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
            {"wait_for_expected": True},
        ],
        expected_key="done",
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(resolve_user_from_token=_voice_user, ws_stream_agent_text_response=_stream),
    )

    assert {"transcript": "", "language": "tr", "provider": "mock"} in ws.sent
    assert {"done": True} in ws.sent
    assert calls["stream"] == 0


@pytest.mark.asyncio
async def test_websocket_voice_reports_llm_provider_error(monkeypatch) -> None:
    class _ProviderError(Exception):
        provider = "mock-llm"
        status_code = 429

    async def _stream(*_args, **_kwargs) -> None:
        raise _ProviderError("quota")

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _WaitUntilSentWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
            {"wait_for_expected": True},
        ],
        expected_key="chunk",
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(
            resolve_user_from_token=_voice_user,
            ws_stream_agent_text_response=_stream,
            llm_api_error_cls=_ProviderError,
        ),
    )

    assert {
        "chunk": "\n[LLM Hatası] mock-llm (429): quota",
        "done": True,
    } in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_reports_generic_stream_error(monkeypatch) -> None:
    async def _stream(*_args, **_kwargs) -> None:
        raise ValueError("boom")

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _WaitUntilSentWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
            {"wait_for_expected": True},
        ],
        expected_key="chunk",
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(resolve_user_from_token=_voice_user, ws_stream_agent_text_response=_stream),
    )

    assert {"chunk": "\n[Sistem Hatası] boom", "done": True} in ws.sent


@pytest.mark.asyncio
async def test_websocket_voice_stops_turn_when_transcript_send_fails(monkeypatch) -> None:
    calls = {"stream": 0}

    async def _stream(*_args, **_kwargs) -> None:
        calls["stream"] += 1

    async def _send_json_if_connected(_websocket, payload):
        return "transcript" not in payload

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    monkeypatch.setattr(ws_voice, "send_json_if_connected", _send_json_if_connected)
    ws = _WaitUntilSentWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
            {"wait_for_expected": True},
        ],
        expected_key="enabled",
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(resolve_user_from_token=_voice_user, ws_stream_agent_text_response=_stream),
    )

    assert calls["stream"] == 0
    assert not any(payload.get("assistant_turn") == "started" for payload in ws.sent)


@pytest.mark.asyncio
async def test_websocket_voice_emits_assistant_turn_started_before_completed(
    monkeypatch,
) -> None:
    async def _stream(websocket, *_args, **_kwargs) -> None:
        await websocket.send_json({"chunk": "voice answer"})

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _WaitUntilSentWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"abc"},
            {"text": '{"action":"commit"}'},
            {"wait_for_expected": True},
        ],
        expected_key="done",
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(resolve_user_from_token=_voice_user, ws_stream_agent_text_response=_stream),
    )

    turn_events = [
        payload.get("assistant_turn")
        for payload in ws.sent
        if payload.get("assistant_turn") in {"started", "completed"}
    ]
    assert turn_events == ["started", "completed"]
    assert {"chunk": "voice answer"} in ws.sent
    assert ws.sent.index({"assistant_turn": "started", "assistant_turn_id": 1}) < ws.sent.index(
        {"assistant_turn": "completed", "assistant_turn_id": 1}
    )


@pytest.mark.asyncio
async def test_websocket_voice_cancels_active_response_on_new_turn(monkeypatch) -> None:
    first_stream_started = asyncio.Event()
    release_stream = asyncio.Event()
    stream_calls = {"count": 0}

    async def _stream(*_args, **_kwargs) -> None:
        stream_calls["count"] += 1
        first_stream_started.set()
        await release_stream.wait()

    class _InterleavedWs(_Ws):
        async def receive(self) -> dict[str, object]:
            try:
                packet = next(self._messages)
            except StopIteration as exc:
                raise ws_voice.WebSocketDisconnect() from exc
            if packet.get("wait_for_stream"):
                await asyncio.wait_for(first_stream_started.wait(), timeout=1)
                return {"bytes": b"second"}
            return packet

    _install_voice_imports(monkeypatch, _SuccessfulTranscriptionPipeline)
    ws = _InterleavedWs(
        [
            {"text": '{"action":"auth","token":"voice-token"}'},
            {"bytes": b"first"},
            {"text": '{"action":"commit"}'},
            {"wait_for_stream": True},
            {"text": '{"action":"commit"}'},
        ]
    )

    await ws_voice.websocket_voice(
        ws,
        _deps(
            cfg=SimpleNamespace(VOICE_WS_MAX_BYTES=32),
            resolve_user_from_token=_voice_user,
            ws_stream_agent_text_response=_stream,
        ),
    )
    release_stream.set()

    assert any(
        payload.get("voice_interruption") == "superseded_by_new_turn"
        and payload.get("cancelled") is True
        for payload in ws.sent
    )
    assert stream_calls["count"] >= 1
