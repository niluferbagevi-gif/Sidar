from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from web.routes import ws_voice


class _Ws:
    def __init__(self, messages=None, headers=None) -> None:
        self.headers = headers or {}
        self.sent: list[dict[str, object]] = []
        self.accepted: list[str | None] = []
        self.closed: list[tuple[int, str]] = []
        self._messages = iter(messages or [])

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
