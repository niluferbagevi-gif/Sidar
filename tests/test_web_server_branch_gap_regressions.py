import asyncio
import inspect
import json
import sys
import types
from pathlib import Path

from tests.test_web_server_runtime import _FakeFastAPI, _FakeRequest, _load_web_server


class _ModulePatch:
    def __init__(self, name: str, module: types.ModuleType):
        self.name = name
        self.module = module
        self.previous = sys.modules.get(name)

    def __enter__(self):
        sys.modules[self.name] = self.module
        return self.module

    def __exit__(self, exc_type, exc, tb):
        if self.previous is None:
            sys.modules.pop(self.name, None)
        else:
            sys.modules[self.name] = self.previous
        return False


def test_setup_tracing_skips_httpx_instrumentation_when_instrumentor_is_missing(monkeypatch):
    mod = _load_web_server()

    class _Res:
        @staticmethod
        def create(data):
            return {"resource": data}

    class _Provider:
        def __init__(self, resource):
            self.resource = resource
            self.processors = []

        def add_span_processor(self, proc):
            self.processors.append(proc)

    class _Exporter:
        def __init__(self, endpoint, insecure):
            self.endpoint = endpoint
            self.insecure = insecure

    class _Batch:
        def __init__(self, exporter):
            self.exporter = exporter

    class _FastAPIInstr:
        called = 0

        @classmethod
        def instrument_app(cls, _app):
            cls.called += 1

    class _Trace:
        provider = None

        @classmethod
        def set_tracer_provider(cls, provider):
            cls.provider = provider

    infos = []
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: infos.append(msg % args if args else msg))

    mod.cfg.ENABLE_TRACING = True
    mod.cfg.OTEL_EXPORTER_ENDPOINT = "http://otel:4317"
    mod.trace = _Trace
    mod.Resource = _Res
    mod.TracerProvider = _Provider
    mod.OTLPSpanExporter = _Exporter
    mod.BatchSpanProcessor = _Batch
    mod.FastAPIInstrumentor = _FastAPIInstr
    mod.HTTPXClientInstrumentor = None

    mod._setup_tracing()

    assert _Trace.provider is not None
    assert _FastAPIInstr.called == 1
    assert any("OpenTelemetry aktif" in item for item in infos)


def test_rate_limit_middleware_allows_non_limited_get_io_request(monkeypatch):
    mod = _load_web_server()
    calls = []

    async def _not_limited(bucket, client_ip, limit, window):
        calls.append((bucket, client_ip, limit, window))
        return False

    async def _next(_request):
        return {"ok": True}

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)

    response = asyncio.run(mod.rate_limit_middleware(_FakeRequest(method="GET", path="/git-info"), _next))

    assert response == {"ok": True}
    assert calls == [("get", "127.0.0.1", mod._RATE_LIMIT_GET_IO, mod._RATE_WINDOW)]


def test_websocket_voice_returns_default_error_for_non_dict_transcription_result():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            if token == "valid-token":
                return types.SimpleNamespace(id="u1", username="alice")
            return None

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    agent = types.SimpleNamespace(memory=_Memory(), llm=object(), respond=None)
    mod.get_agent = lambda: asyncio.sleep(0, result=agent)

    multimodal_mod = types.ModuleType("core.multimodal")
    voice_mod = types.ModuleType("core.voice")

    class _Pipeline:
        def __init__(self, *_args, **_kwargs):
            return None

        async def transcribe_bytes(self, *_args, **_kwargs):
            return "unexpected-string"

    class _VoicePipeline:
        def __init__(self, *_args, **_kwargs):
            self.vad_enabled = False
            self.duplex_enabled = False

        def create_duplex_state(self):
            return types.SimpleNamespace(assistant_turn_id=0, output_text_buffer="", last_interrupt_reason="")

    multimodal_mod.MultimodalPipeline = _Pipeline
    voice_mod.VoicePipeline = _VoicePipeline

    class _WebSocket:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "valid-token"}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.sent = []
            self._events = [
                {"type": "websocket.receive", "bytes": b"voice"},
                {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
                {"type": "websocket.disconnect"},
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            return self._events.pop(0)

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws = _WebSocket()
    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert ws.accepted == "valid-token"
    assert {"error": "Ses transkripsiyonu başarısız oldu.", "done": True} in ws.sent
    assert not any("transcript" in item for item in ws.sent)


def test_health_response_returns_ok_when_dependency_health_is_all_green(monkeypatch):
    mod = _load_web_server()

    async def _get_agent():
        return types.SimpleNamespace(
            cfg=types.SimpleNamespace(AI_PROVIDER="openai"),
            health=types.SimpleNamespace(
                get_health_summary=lambda: {"status": "ok", "ollama_online": True},
                get_dependency_health=lambda: {
                    "redis": {"healthy": True, "detail": "ok"},
                    "database": {"healthy": True, "detail": "ok"},
                },
            ),
        )

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    response = asyncio.run(mod._health_response(require_dependencies=True))

    assert response.status_code == 200
    assert response.content["status"] == "ok"
    assert response.content["dependencies"]["redis"]["healthy"] is True
    assert response.content["dependencies"]["database"]["healthy"] is True



def test_get_agent_waiting_caller_reuses_instance_created_by_first_initializer():
    mod = _load_web_server()
    created = {"count": 0, "initialized": 0}
    release_lock = asyncio.Event()

    class _Agent:
        def __init__(self, _cfg):
            created["count"] += 1

        async def initialize(self):
            created["initialized"] += 1
            await release_lock.wait()

    async def _run():
        mod._agent = None
        mod._agent_lock = asyncio.Lock()
        await mod._agent_lock.acquire()
        mod.SidarAgent = _Agent

        first = asyncio.create_task(mod.get_agent())
        second = asyncio.create_task(mod.get_agent())
        await asyncio.sleep(0)
        mod._agent_lock.release()
        await asyncio.sleep(0)
        release_lock.set()
        return await asyncio.gather(first, second)

    a1, a2 = asyncio.run(_run())

    assert a1 is a2
    assert created == {"count": 1, "initialized": 1}


def test_rate_limit_middleware_allows_put_requests_without_get_branch(monkeypatch):
    mod = _load_web_server()
    calls = []

    async def _not_limited(bucket, *_args):
        calls.append(bucket)
        return False

    async def _next(_request):
        return "put-ok"

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)

    response = asyncio.run(mod.rate_limit_middleware(_FakeRequest(method="PUT", path="/git-info"), _next))

    assert response == "put-ok"
    assert calls == []


def test_assets_mount_is_not_added_when_assets_directory_is_missing(monkeypatch):
    recorded = []
    original_mount = _FakeFastAPI.mount
    original_exists = Path.exists

    def _mount(self, path, app, name=None):
        recorded.append((path, getattr(app, "directory", None), name))
        return None

    def _exists(self):
        path = str(self).replace("\\", "/")
        if path.endswith("/web_ui_react/dist/assets"):
            return False
        return original_exists(self)

    monkeypatch.setattr(_FakeFastAPI, "mount", _mount)
    monkeypatch.setattr(Path, "exists", _exists)

    _load_web_server()

    assert not any(path == "/assets" for path, _directory, _name in recorded)


def test_websocket_chat_status_pump_can_exit_cleanly_and_unsubscribe(monkeypatch):
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="", username="alice")

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            if False:
                yield "unused"

    class _Bus:
        def __init__(self):
            self.unsubscribed = []

        def subscribe(self):
            return "sub-clean", asyncio.Queue()

        def unsubscribe(self, sub_id):
            self.unsubscribed.append(sub_id)

    class _DeferredTask:
        def __init__(self, coro):
            self._coro = coro
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

        def __await__(self):
            return self._coro.__await__()

    real_create_task = mod.asyncio.create_task

    def _create_task(coro):
        if getattr(coro, 'cr_code', None) and coro.cr_code.co_name == '_status_pump':
            return _DeferredTask(coro)
        return real_create_task(coro)

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self.sent = []
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "merhaba"}),
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(0.05)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    bus = _Bus()
    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=_Agent()))
    monkeypatch.setattr(mod, 'get_agent_event_bus', lambda: bus)
    monkeypatch.setattr(mod, '_redis_is_rate_limited', lambda *_a, **_k: asyncio.sleep(0, result=False))
    monkeypatch.setattr(mod.asyncio, 'create_task', _create_task)

    asyncio.run(mod.websocket_chat(_WebSocket()))

    assert bus.unsubscribed == ['sub-clean']


def test_websocket_chat_room_status_pump_exits_cleanly_and_cancel_without_active_task(monkeypatch):
    mod = _load_web_server()
    mod._collaboration_rooms.clear()

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="", username="alice")

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, prompt):
            return f"ok:{prompt}"

    class _Bus:
        def __init__(self):
            self.unsubscribed = []

        def subscribe(self):
            return 'sub-room', asyncio.Queue()

        def unsubscribe(self, sub_id):
            self.unsubscribed.append(sub_id)

    class _DeferredTask:
        def __init__(self, coro):
            self._coro = coro
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

        def __await__(self):
            return self._coro.__await__()

    real_create_task = mod.asyncio.create_task

    def _create_task(coro):
        name = getattr(getattr(coro, 'cr_code', None), 'co_name', '')
        if name == '_status_pump':
            return _DeferredTask(coro)
        return real_create_task(coro)

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self.headers = {}
            self.sent = []
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "join_room", "room_id": "workspace:demo", "display_name": "Alice"}),
                json.dumps({"action": "message", "message": "@Sidar plan yap", "display_name": "Alice"}),
                json.dumps({"action": "cancel"}),
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(0.05)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    bus = _Bus()
    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=_Agent()))
    monkeypatch.setattr(mod, 'get_agent_event_bus', lambda: bus)
    monkeypatch.setattr(mod, '_redis_is_rate_limited', lambda *_a, **_k: asyncio.sleep(0, result=False))
    monkeypatch.setattr(mod.asyncio, 'create_task', _create_task)

    asyncio.run(mod.websocket_chat(_WebSocket()))

    assert bus.unsubscribed == ['sub-room']


def test_websocket_chat_anyio_closed_without_active_task_still_leaves_room(monkeypatch):
    mod = _load_web_server()
    left = []

    class _Closed(Exception):
        pass

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self.headers = {}
            self._payloads = [json.dumps({"action": "auth", "token": "tok"})]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise _Closed('socket closed')

        async def send_json(self, _payload):
            return None

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id='u1', username='alice')

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=types.SimpleNamespace(memory=_Memory())))
    monkeypatch.setattr(mod, '_ANYIO_CLOSED', _Closed)
    monkeypatch.setattr(mod, '_leave_collaboration_room', lambda ws: left.append(ws) or asyncio.sleep(0))

    asyncio.run(mod.websocket_chat(_WebSocket()))

    assert len(left) == 1


def test_websocket_voice_vad_event_without_auto_commit_only_emits_state(monkeypatch):
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            if token == 'valid-token':
                return types.SimpleNamespace(id='u1', username='alice')
            return None

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=types.SimpleNamespace(memory=_Memory(), llm=object(), respond=None)))

    multimodal_mod = types.ModuleType('core.multimodal')
    voice_mod = types.ModuleType('core.voice')

    class _Pipeline:
        def __init__(self, *_args, **_kwargs):
            return None

        async def transcribe_bytes(self, *_args, **_kwargs):
            raise AssertionError('transcribe_bytes should not run')

    class _VoicePipeline:
        vad_enabled = True
        duplex_enabled = True

        def __init__(self, *_args, **_kwargs):
            return None

        def create_duplex_state(self):
            return types.SimpleNamespace(assistant_turn_id=0, output_text_buffer='', last_interrupt_reason='')

        def should_interrupt_response(self, *_args, **_kwargs):
            return False

        def should_commit_audio(self, *_args, **_kwargs):
            return False

        def build_voice_state_payload(self, *, event, buffered_bytes, sequence, duplex_state=None):
            return {
                'voice_state': event,
                'buffered_bytes': buffered_bytes,
                'sequence': sequence,
                'assistant_turn_id': int(getattr(duplex_state, 'assistant_turn_id', 0) or 0),
            }

    multimodal_mod.MultimodalPipeline = _Pipeline
    voice_mod.VoicePipeline = _VoicePipeline

    class _WebSocket:
        def __init__(self):
            self.headers = {'sec-websocket-protocol': 'valid-token'}
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self.sent = []
            self._events = [
                {'type': 'websocket.receive', 'bytes': b'audio'},
                {'type': 'websocket.receive', 'text': json.dumps({'action': 'vad_event', 'state': 'speech_start'})},
                {'type': 'websocket.disconnect'},
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            return self._events.pop(0)

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws = _WebSocket()
    with _ModulePatch('core.multimodal', multimodal_mod), _ModulePatch('core.voice', voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert {'buffered_bytes': 5} in ws.sent
    assert any(item.get('voice_state') == 'speech_start' for item in ws.sent)
    assert not any('transcript' in item for item in ws.sent)


def test_websocket_voice_anyio_closed_without_active_response_task_exits_cleanly(monkeypatch):
    mod = _load_web_server()
    info_logs = []

    class _Closed(Exception):
        pass

    class _DB:
        async def get_user_by_token(self, token):
            if token == 'valid-token':
                return types.SimpleNamespace(id='u1', username='alice')
            return None

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=types.SimpleNamespace(memory=_Memory(), llm=object(), respond=None)))
    monkeypatch.setattr(mod, '_ANYIO_CLOSED', _Closed)
    monkeypatch.setattr(mod.logger, 'info', lambda msg, *args: info_logs.append(msg % args if args else msg))

    multimodal_mod = types.ModuleType('core.multimodal')
    voice_mod = types.ModuleType('core.voice')
    multimodal_mod.MultimodalPipeline = lambda *_a, **_k: object()
    voice_mod.VoicePipeline = lambda *_a, **_k: types.SimpleNamespace(create_duplex_state=lambda: types.SimpleNamespace(assistant_turn_id=0, output_text_buffer='', last_interrupt_reason=''), vad_enabled=False, duplex_enabled=False)

    class _WebSocket:
        def __init__(self):
            self.headers = {'sec-websocket-protocol': 'valid-token'}
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self._events = [_Closed('socket closed')]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            raise self._events.pop(0)

        async def send_json(self, _payload):
            return None

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws = _WebSocket()
    with _ModulePatch('core.multimodal', multimodal_mod), _ModulePatch('core.voice', voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert any('ClosedResourceError' in item for item in info_logs)


def test_set_level_endpoint_awaits_coroutine_result_from_background_thread_again(monkeypatch):
    mod = _load_web_server()

    async def _async_result():
        return 'async-level-updated-again'

    agent = types.SimpleNamespace(
        set_access_level=lambda _level: _async_result(),
        security=types.SimpleNamespace(level_name='full'),
    )

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=agent))

    response = asyncio.run(mod.set_level_endpoint(_FakeRequest(json_body={'level': 'full'})))

    assert response.status_code == 200
    assert response.content['message'] == 'async-level-updated-again'
    assert response.content['current_level'] == 'full'



def test_websocket_chat_subscribe_failure_skips_status_task_and_unsubscribe(monkeypatch):
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id='', username='alice')

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            if False:
                yield 'unused'

    class _Bus:
        def subscribe(self):
            raise RuntimeError('subscribe failed')

        def unsubscribe(self, _sub_id):
            raise AssertionError('unsubscribe should not run')

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self.headers = {}
            self.sent = []
            self._payloads = [
                json.dumps({'action': 'auth', 'token': 'tok'}),
                json.dumps({'action': 'send', 'message': 'merhaba'}),
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(0.05)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=_Agent()))
    monkeypatch.setattr(mod, 'get_agent_event_bus', lambda: _Bus())
    monkeypatch.setattr(mod, '_redis_is_rate_limited', lambda *_a, **_k: asyncio.sleep(0, result=False))

    ws = _WebSocket()
    asyncio.run(mod.websocket_chat(ws))

    assert any('Sistem Hatası' in item.get('chunk', '') for item in ws.sent)


def test_websocket_chat_room_subscribe_failure_skips_status_task_and_unsubscribe(monkeypatch):
    mod = _load_web_server()
    mod._collaboration_rooms.clear()

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id='', username='alice')

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, _prompt):
            return 'unused'

    class _Bus:
        def subscribe(self):
            raise RuntimeError('room subscribe failed')

        def unsubscribe(self, _sub_id):
            raise AssertionError('unsubscribe should not run')

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self.headers = {}
            self.sent = []
            self._payloads = [
                json.dumps({'action': 'auth', 'token': 'tok'}),
                json.dumps({'action': 'join_room', 'room_id': 'workspace:demo', 'display_name': 'Alice'}),
                json.dumps({'action': 'message', 'message': '@Sidar plan yap', 'display_name': 'Alice'}),
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(0.05)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=_Agent()))
    monkeypatch.setattr(mod, 'get_agent_event_bus', lambda: _Bus())
    monkeypatch.setattr(mod, '_redis_is_rate_limited', lambda *_a, **_k: asyncio.sleep(0, result=False))

    ws = _WebSocket()
    asyncio.run(mod.websocket_chat(ws))

    assert any(item.get('type') == 'room_error' and 'room subscribe failed' in item.get('error', '') for item in ws.sent)


def test_websocket_voice_cancel_can_skip_notification_when_called_with_notify_false(monkeypatch):
    mod = _load_web_server()
    captured = {}

    async def _resolve_user_from_token(_agent, _token):
        frame = inspect.currentframe()
        assert frame is not None and frame.f_back is not None
        captured['cancel_fn'] = frame.f_back.f_locals['_cancel_active_response']
        return types.SimpleNamespace(id='u1', username='alice')

    class _PendingTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

        def __await__(self):
            if False:
                yield None
            return None

    def _create_task(coro):
        if getattr(coro, 'cr_code', None) and coro.cr_code.co_name == '_run_voice_turn':
            coro.close()
            task = _PendingTask()
            captured['task'] = task
            return task
        return asyncio.create_task(coro)

    class _VoicePipeline:
        vad_enabled = False
        duplex_enabled = True

        def __init__(self, *_args, **_kwargs):
            return None

        def create_duplex_state(self):
            return types.SimpleNamespace(assistant_turn_id=3, output_text_buffer='abc', last_interrupt_reason='')

        def interrupt_assistant_turn(self, state, *, reason):
            state.last_interrupt_reason = reason
            return {'assistant_turn_id': state.assistant_turn_id, 'reason': reason}

    class _WebSocket:
        def __init__(self):
            self.headers = {'sec-websocket-protocol': 'valid-token'}
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self.sent = []
            self.step = 0

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            if self.step == 0:
                self.step += 1
                return {'type': 'websocket.receive', 'bytes': b'audio'}
            if self.step == 1:
                self.step += 1
                return {'type': 'websocket.receive', 'text': json.dumps({'action': 'commit'})}
            if self.step == 2:
                self.step += 1
                await captured['cancel_fn']('silent', notify=False)
                return {'type': 'websocket.disconnect'}
            raise AssertionError('unexpected receive call')

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = (code, reason)

    multimodal_mod = types.ModuleType('core.multimodal')
    voice_mod = types.ModuleType('core.voice')
    multimodal_mod.MultimodalPipeline = lambda *_a, **_k: types.SimpleNamespace(transcribe_bytes=lambda *_a, **_k: None)
    voice_mod.VoicePipeline = _VoicePipeline

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=types.SimpleNamespace(memory=types.SimpleNamespace(set_active_user=lambda *_a, **_k: asyncio.sleep(0), db=None), llm=object(), respond=None)))
    monkeypatch.setattr(mod, '_resolve_user_from_token', _resolve_user_from_token)
    monkeypatch.setattr(mod.asyncio, 'create_task', _create_task)

    ws = _WebSocket()
    with _ModulePatch('core.multimodal', multimodal_mod), _ModulePatch('core.voice', voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert captured['task'].cancelled is True
    assert not any('voice_interruption' in item for item in ws.sent)


def test_set_level_endpoint_returns_plain_string_from_background_thread(monkeypatch):
    mod = _load_web_server()

    agent = types.SimpleNamespace(
        set_access_level=lambda _level: 'plain-level-updated',
        security=types.SimpleNamespace(level_name='full'),
    )

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=agent))

    response = asyncio.run(mod.set_level_endpoint(_FakeRequest(json_body={'level': 'full'})))

    assert response.status_code == 200
    assert response.content['message'] == 'plain-level-updated'
    assert response.content['current_level'] == 'full'



def test_websocket_voice_anyio_closed_with_completed_response_task_exits_cleanly(monkeypatch):
    mod = _load_web_server()

    class _Closed(Exception):
        pass

    class _DoneTask:
        def __init__(self):
            self.awaited = 0

        def done(self):
            return True

        def cancel(self):
            return None

        def __await__(self):
            self.awaited += 1
            if False:
                yield None
            return None

    done_task = _DoneTask()

    def _create_task(coro):
        if getattr(coro, 'cr_code', None) and coro.cr_code.co_name == '_run_voice_turn':
            coro.close()
            return done_task
        return asyncio.create_task(coro)

    class _DB:
        async def get_user_by_token(self, token):
            if token == 'valid-token':
                return types.SimpleNamespace(id='u1', username='alice')
            return None

    class _Memory:
        db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    monkeypatch.setattr(mod, 'get_agent', lambda: asyncio.sleep(0, result=types.SimpleNamespace(memory=_Memory(), llm=object(), respond=None)))
    monkeypatch.setattr(mod, '_ANYIO_CLOSED', _Closed)
    monkeypatch.setattr(mod.asyncio, 'create_task', _create_task)

    multimodal_mod = types.ModuleType('core.multimodal')
    voice_mod = types.ModuleType('core.voice')
    multimodal_mod.MultimodalPipeline = lambda *_a, **_k: types.SimpleNamespace(transcribe_bytes=lambda *_a, **_k: None)
    voice_mod.VoicePipeline = lambda *_a, **_k: types.SimpleNamespace(create_duplex_state=lambda: types.SimpleNamespace(assistant_turn_id=0, output_text_buffer='', last_interrupt_reason=''), vad_enabled=False, duplex_enabled=False)

    class _WebSocket:
        def __init__(self):
            self.headers = {'sec-websocket-protocol': 'valid-token'}
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self._events = [
                {'type': 'websocket.receive', 'bytes': b'audio'},
                {'type': 'websocket.receive', 'text': json.dumps({'action': 'commit'})},
                _Closed('socket closed'),
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            item = self._events.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        async def send_json(self, _payload):
            return None

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws = _WebSocket()
    with _ModulePatch('core.multimodal', multimodal_mod), _ModulePatch('core.voice', voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert done_task.awaited == 0