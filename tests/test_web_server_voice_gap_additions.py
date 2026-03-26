import asyncio
import base64
import builtins
import contextlib
import json
import sys
import types

from tests.test_web_server_runtime import _load_web_server


def _install_voice_pipeline_stubs(monkeypatch, *, missing_voice_pipeline: bool = False):
    multimodal_mod = types.ModuleType("core.multimodal")

    class _MultimodalPipeline:
        def __init__(self, llm, cfg):
            self.llm = llm
            self.cfg = cfg

        async def transcribe_bytes(self, audio_bytes, mime_type=None, language=None, prompt=None):
            return {
                "success": True,
                "text": "stub transcript" if audio_bytes else "",
                "language": language or "tr",
                "provider": "stub",
                "mime_type": mime_type,
                "prompt": prompt,
            }

    multimodal_mod.MultimodalPipeline = _MultimodalPipeline
    monkeypatch.setitem(sys.modules, "core.multimodal", multimodal_mod)

    if missing_voice_pipeline:
        real_import = builtins.__import__

        def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "core.voice":
                raise ImportError("voice pipeline unavailable")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", _fake_import)
        return

    voice_mod = types.ModuleType("core.voice")

    class _VoicePipeline:
        enabled = True
        vad_enabled = True
        duplex_enabled = True

        def __init__(self, _cfg):
            self.cfg = _cfg

        def create_duplex_state(self):
            return types.SimpleNamespace(
                assistant_turn_id=0,
                output_text_buffer="",
                last_interrupt_reason="",
            )

        def build_voice_state_payload(self, *, event, buffered_bytes, sequence, duplex_state):
            return {
                "voice_state": event,
                "buffered_bytes": buffered_bytes,
                "sequence": sequence,
                "assistant_turn_id": duplex_state.assistant_turn_id,
            }

        def interrupt_assistant_turn(self, duplex_state, reason=""):
            duplex_state.last_interrupt_reason = reason
            return {
                "assistant_turn_id": duplex_state.assistant_turn_id,
                "dropped_text_chars": 0,
                "cancelled_audio_sequences": 0,
                "reason": reason,
            }

        def should_interrupt_response(self, _buffered_bytes, event=""):
            return False

        def should_commit_audio(self, _buffered_bytes, event=""):
            return False

        def begin_assistant_turn(self, duplex_state):
            duplex_state.assistant_turn_id += 1
            return duplex_state.assistant_turn_id

    voice_mod.VoicePipeline = _VoicePipeline
    monkeypatch.setitem(sys.modules, "core.voice", voice_mod)


def _make_voice_agent():
    class _DB:
        async def get_user_by_token(self, token):
            if token == "tok":
                return types.SimpleNamespace(id="u1", username="alice")
            return None

    class _Memory:
        def __init__(self):
            self.db = _DB()
            self.active = []

        async def set_active_user(self, user_id, username=None):
            self.active.append((user_id, username))

    class _Agent:
        def __init__(self):
            self.memory = _Memory()
            self.llm = object()

    return _Agent()


class _VoiceWebSocket:
    def __init__(self, packets, *, headers=None):
        self._packets = list(packets)
        self.headers = headers or {}
        self.client = types.SimpleNamespace(host="127.0.0.1")
        self.sent = []
        self.closed = []
        self.accepted = []

    async def accept(self, subprotocol=None):
        self.accepted.append(subprotocol)

    async def receive(self):
        item = self._packets.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=None, reason=None):
        self.closed.append((code, reason))


def test_list_child_ollama_pids_windows_psutil_error_returns_empty(monkeypatch):
    mod = _load_web_server()

    class _PsutilMod:
        class Process:
            def __init__(self, _pid):
                raise RuntimeError("psutil failed")

    monkeypatch.setitem(sys.modules, "psutil", _PsutilMod)
    monkeypatch.setattr(mod.os, "name", "nt", raising=False)

    assert mod._list_child_ollama_pids() == []


def test_autonomous_cron_loop_stops_when_wait_completes(monkeypatch):
    mod = _load_web_server()
    stop_event = asyncio.Event()
    dispatched = {"count": 0}

    async def _wait_for(awaitable, timeout):
        with contextlib.suppress(Exception):
            awaitable.close()
        return True

    async def _dispatch(**_kwargs):
        dispatched["count"] += 1
        return {"trigger_id": "unexpected"}

    monkeypatch.setattr(mod.asyncio, "wait_for", _wait_for)
    monkeypatch.setattr(mod, "_dispatch_autonomy_trigger", _dispatch)

    asyncio.run(mod._autonomous_cron_loop(stop_event))

    assert dispatched["count"] == 0


def test_websocket_voice_authenticates_and_appends_base64_without_voice_pipeline(monkeypatch):
    mod = _load_web_server()
    _install_voice_pipeline_stubs(monkeypatch, missing_voice_pipeline=True)
    agent = _make_voice_agent()
    mod.get_agent = lambda: asyncio.sleep(0, result=agent)
    mod.jwt.decode = lambda *_a, **_k: (_ for _ in ()).throw(mod.jwt.PyJWTError("bad token"))

    ws = _VoiceWebSocket(
        [
            {"type": "websocket.receive", "text": json.dumps({"action": "auth", "token": "tok"})},
            {
                "type": "websocket.receive",
                "text": json.dumps({"action": "append_base64", "chunk": base64.b64encode(b"hi").decode("ascii")}),
            },
            {"type": "websocket.disconnect"},
        ]
    )

    asyncio.run(mod.websocket_voice(ws))

    assert ws.accepted == [None]
    assert {"auth_ok": True} in ws.sent
    assert {"buffered_bytes": 2} in ws.sent
    assert any(item.get("voice_state") == "chunk" for item in ws.sent)
    assert agent.memory.active == [("u1", "alice")]


def test_websocket_voice_rejects_non_auth_action_before_authentication(monkeypatch):
    mod = _load_web_server()
    _install_voice_pipeline_stubs(monkeypatch)
    mod.get_agent = lambda: asyncio.sleep(0, result=_make_voice_agent())

    ws = _VoiceWebSocket(
        [
            {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
        ]
    )

    asyncio.run(mod.websocket_voice(ws))

    assert ws.closed == [(1008, "Authentication required")]


def test_websocket_voice_commit_without_buffered_audio_returns_done_error(monkeypatch):
    mod = _load_web_server()
    _install_voice_pipeline_stubs(monkeypatch)
    mod.get_agent = lambda: asyncio.sleep(0, result=_make_voice_agent())
    mod.jwt.decode = lambda *_a, **_k: (_ for _ in ()).throw(mod.jwt.PyJWTError("bad token"))

    ws = _VoiceWebSocket(
        [
            {"type": "websocket.receive", "text": json.dumps({"action": "auth", "token": "tok"})},
            {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
            {"type": "websocket.disconnect"},
        ]
    )

    asyncio.run(mod.websocket_voice(ws))

    assert {"auth_ok": True} in ws.sent
    assert {"error": "İşlenecek ses verisi bulunamadı.", "done": True} in ws.sent

def test_websocket_voice_second_commit_cancels_active_response(monkeypatch):
    mod = _load_web_server()
    _install_voice_pipeline_stubs(monkeypatch)
    agent = _make_voice_agent()
    mod.get_agent = lambda: asyncio.sleep(0, result=agent)
    mod.jwt.decode = lambda *_a, **_k: (_ for _ in ()).throw(mod.jwt.PyJWTError("bad token"))

    task_calls = {"created": 0, "cancelled": 0}

    class _FakeTask:
        def __init__(self, *, done):
            self._done = done

        def done(self):
            return self._done

        def cancel(self):
            task_calls["cancelled"] += 1
            self._done = True

        def __await__(self):
            if False:
                yield None
            return None

    def _create_task(coro):
        task_calls["created"] += 1
        coro.close()
        return _FakeTask(done=task_calls["created"] > 1)

    monkeypatch.setattr(mod.asyncio, "create_task", _create_task)

    ws = _VoiceWebSocket(
        [
            {"type": "websocket.receive", "text": json.dumps({"action": "auth", "token": "tok"})},
            {
                "type": "websocket.receive",
                "text": json.dumps({"action": "append_base64", "chunk": base64.b64encode(b"one").decode("ascii")}),
            },
            {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
            {
                "type": "websocket.receive",
                "text": json.dumps({"action": "append_base64", "chunk": base64.b64encode(b"two").decode("ascii")}),
            },
            {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
            {"type": "websocket.disconnect"},
        ]
    )

    asyncio.run(mod.websocket_voice(ws))

    assert task_calls["created"] == 2
    assert task_calls["cancelled"] == 1
    assert any(item.get("voice_interruption") == "superseded_by_new_turn" for item in ws.sent)


def test_websocket_voice_logs_anyio_closed_and_unexpected_errors(monkeypatch):
    mod = _load_web_server()
    _install_voice_pipeline_stubs(monkeypatch)
    mod.get_agent = lambda: asyncio.sleep(0, result=_make_voice_agent())

    info_logs = []
    warning_logs = []
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: info_logs.append(msg % args if args else msg))
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warning_logs.append(msg % args if args else msg))

    class _Closed(Exception):
        pass

    mod._ANYIO_CLOSED = _Closed
    ws_closed = _VoiceWebSocket([_Closed("socket closed")])
    asyncio.run(mod.websocket_voice(ws_closed))

    ws_boom = _VoiceWebSocket([RuntimeError("boom")])
    asyncio.run(mod.websocket_voice(ws_boom))

    assert any("ClosedResourceError" in entry for entry in info_logs)
    assert any("beklenmedik hata: boom" in entry for entry in warning_logs)


def test_websocket_voice_anyio_closed_awaits_active_response_task(monkeypatch):
    mod = _load_web_server()
    _install_voice_pipeline_stubs(monkeypatch)
    mod.get_agent = lambda: asyncio.sleep(0, result=_make_voice_agent())

    task_state = {"created": 0, "awaited": 0}

    class _PendingTask:
        def done(self):
            return False

        def cancel(self):
            return None

        def __await__(self):
            task_state["awaited"] += 1
            if False:
                yield None
            return None

    def _create_task(coro):
        task_state["created"] += 1
        coro.close()
        return _PendingTask()

    class _Closed(Exception):
        pass

    monkeypatch.setattr(mod.asyncio, "create_task", _create_task)
    mod._ANYIO_CLOSED = _Closed

    ws = _VoiceWebSocket(
        [
            {"type": "websocket.receive", "text": json.dumps({"action": "auth", "token": "tok"})},
            {
                "type": "websocket.receive",
                "text": json.dumps({"action": "append_base64", "chunk": base64.b64encode(b"voice").decode("ascii")}),
            },
            {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
            _Closed("socket closed"),
        ]
    )

    asyncio.run(mod.websocket_voice(ws))

    assert task_state == {"created": 1, "awaited": 1}


def test_websocket_voice_anyio_closed_skips_completed_active_response_task(monkeypatch):
    mod = _load_web_server()
    _install_voice_pipeline_stubs(monkeypatch)
    mod.get_agent = lambda: asyncio.sleep(0, result=_make_voice_agent())

    task_state = {"created": 0, "awaited": 0}

    class _DoneTask:
        def done(self):
            return True

        def cancel(self):
            return None

        def __await__(self):
            task_state["awaited"] += 1
            if False:
                yield None
            return None

    def _create_task(coro):
        task_state["created"] += 1
        coro.close()
        return _DoneTask()

    class _Closed(Exception):
        pass

    monkeypatch.setattr(mod.asyncio, "create_task", _create_task)
    mod._ANYIO_CLOSED = _Closed

    ws = _VoiceWebSocket(
        [
            {"type": "websocket.receive", "text": json.dumps({"action": "auth", "token": "tok"})},
            {
                "type": "websocket.receive",
                "text": json.dumps({"action": "append_base64", "chunk": base64.b64encode(b"voice").decode("ascii")}),
            },
            {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
            _Closed("socket closed"),
        ]
    )

    asyncio.run(mod.websocket_voice(ws))

    assert task_state == {"created": 1, "awaited": 0}
