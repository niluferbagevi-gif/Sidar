from __future__ import annotations

import asyncio
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
