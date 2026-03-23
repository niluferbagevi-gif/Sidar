import asyncio
import json
import sys
import types

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


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