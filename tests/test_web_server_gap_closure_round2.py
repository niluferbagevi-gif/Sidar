import asyncio
import base64
import json
import sys
import types

import pytest

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


class _VoiceWebSocket:
    def __init__(self, events, *, token="valid-token"):
        self.headers = {"sec-websocket-protocol": token} if token is not None else {}
        self.client = types.SimpleNamespace(host="127.0.0.1")
        self.sent = []
        self.closed = None
        self.accepted = None
        self._events = list(events)

    async def accept(self, subprotocol=None):
        self.accepted = subprotocol

    async def receive(self):
        if self._events:
            return self._events.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code, reason):
        self.closed = (code, reason)


def _install_voice_modules(*, transcribe_result=None, voice_pipeline_cls=None):
    multimodal_mod = types.ModuleType("core.multimodal")
    voice_mod = types.ModuleType("core.voice")

    class _Pipeline:
        def __init__(self, *_args, **_kwargs):
            return None

        async def transcribe_bytes(self, *_args, **_kwargs):
            return transcribe_result

    multimodal_mod.MultimodalPipeline = _Pipeline
    if voice_pipeline_cls is not None:
        voice_mod.VoicePipeline = voice_pipeline_cls
    return multimodal_mod, voice_mod


def _set_voice_agent(mod, *, valid_token="valid-token", respond=None):
    class _DB:
        async def get_user_by_token(self, token):
            if token == valid_token:
                return types.SimpleNamespace(id="u1", username="alice")
            return None

    class _Memory:
        db = _DB()

        def __len__(self):
            return 1

        async def set_active_user(self, *_args, **_kwargs):
            return None

    async def _default_respond(prompt):
        yield f"reply:{prompt}"

    agent = types.SimpleNamespace(memory=_Memory(), llm=object(), respond=respond or _default_respond)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    return agent


class _BasicVoicePipeline:
    def __init__(self, *_args, **_kwargs):
        self.enabled = False
        self.vad_enabled = True
        self.duplex_enabled = True

    def create_duplex_state(self):
        return types.SimpleNamespace(assistant_turn_id=0, output_text_buffer="", last_interrupt_reason="")


class _RichVoicePipeline(_BasicVoicePipeline):
    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.enabled = True

    def build_voice_state_payload(self, *, event, buffered_bytes, sequence, duplex_state=None):
        return {
            "voice_state": event,
            "buffered_bytes": buffered_bytes,
            "sequence": sequence,
            "vad_enabled": True,
            "auto_commit_ready": False,
            "duplex_enabled": True,
            "interrupt_ready": False,
            "tts_enabled": True,
            "assistant_turn_id": int(getattr(duplex_state, "assistant_turn_id", 0) or 0),
            "output_buffer_chars": len(getattr(duplex_state, "output_text_buffer", "") or ""),
            "last_interrupt_reason": str(getattr(duplex_state, "last_interrupt_reason", "") or ""),
        }

    def interrupt_assistant_turn(self, state, *, reason):
        state.last_interrupt_reason = reason
        return {
            "assistant_turn_id": int(getattr(state, "assistant_turn_id", 0) or 0),
            "dropped_text_chars": 0,
            "cancelled_audio_sequences": 0,
            "reason": reason,
        }


class _StreamingVoicePipeline(_RichVoicePipeline):
    def extract_ready_segments(self, text, flush=False):
        text = str(text or "")
        if not flush:
            return ["   ", "skip-fail", "skip-empty", text], ""
        return ["trailing"], ""

    async def synthesize_text(self, text):
        if text == "skip-fail":
            return {"success": False}
        if text == "skip-empty":
            return {"success": True, "audio_bytes": b""}
        return {
            "success": True,
            "audio_bytes": f"tts:{text}".encode("utf-8"),
            "mime_type": "audio/mock",
            "provider": "mock",
            "voice": "v1",
        }


@pytest.fixture
def mod():
    return _load_web_server()


def test_ci_failure_context_variants_and_resolve_direct_context(mod, monkeypatch):
    workflow_payload = {
        "repository": {"full_name": "acme/sidar", "default_branch": "main"},
        "workflow_run": {
            "status": "completed",
            "conclusion": "failure",
            "pull_requests": [{"base": {"ref": "release/1.2"}}],
            "name": "CI",
        },
    }
    workflow_ctx = mod._fallback_ci_failure_context("workflow_run", workflow_payload)
    assert workflow_ctx["kind"] == "workflow_run"
    assert workflow_ctx["base_branch"] == "release/1.2"

    check_run_ctx = mod._fallback_ci_failure_context(
        "check_run",
        {
            "repository": {"full_name": "acme/sidar", "default_branch": "main"},
            "check_run": {
                "conclusion": "failure",
                "name": "lint",
                "output": {"title": "flake8", "summary": "bad", "text": "details"},
                "check_suite": {"head_branch": "feat/x"},
                "details_url": "https://example.test/job",
            },
        },
    )
    assert check_run_ctx["kind"] == "check_run"
    assert "bad" in check_run_ctx["log_excerpt"] and "details" in check_run_ctx["log_excerpt"]

    check_suite_ctx = mod._fallback_ci_failure_context(
        "check_suite",
        {
            "repository": {"full_name": "acme/sidar", "default_branch": "main"},
            "check_suite": {"conclusion": "timed_out", "app": {"name": "checks"}, "head_branch": "feat/y"},
        },
    )
    assert check_suite_ctx["kind"] == "check_suite"
    assert check_suite_ctx["workflow_name"] == "checks"

    monkeypatch.setattr(mod, "build_ci_failure_context", lambda *_a, **_k: {"kind": "external", "nested": {"x": 1}})
    resolved = mod._resolve_ci_failure_context("push", {"x": 1})
    assert resolved == {"kind": "external", "nested": {"x": 1}}
    assert resolved is not mod.build_ci_failure_context("push", {"x": 1})


def test_autonomous_cron_loop_covers_blank_prompt_success_and_warning(mod, monkeypatch):
    info_logs = []
    warning_logs = []
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: info_logs.append(msg % args if args else msg))
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warning_logs.append(msg % args if args else msg))

    mod.cfg.AUTONOMOUS_CRON_PROMPT = "   "
    asyncio.run(mod._autonomous_cron_loop(asyncio.Event()))
    assert any("prompt boş" in msg for msg in info_logs)

    class _StopAfterOne:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            return self.calls > 0

        async def wait(self):
            self.calls += 1
            return True

    async def _timeout_once(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError()

    dispatches = []

    async def _dispatch_ok(**kwargs):
        dispatches.append(kwargs)
        stop_event.calls = 1
        return {"trigger_id": "cron-1"}

    mod.cfg.AUTONOMOUS_CRON_PROMPT = "Run audits"
    mod.cfg.AUTONOMOUS_CRON_INTERVAL_SECONDS = 5
    stop_event = _StopAfterOne()
    monkeypatch.setattr(mod.asyncio, "wait_for", _timeout_once)
    monkeypatch.setattr(mod, "_dispatch_autonomy_trigger", _dispatch_ok)
    asyncio.run(mod._autonomous_cron_loop(stop_event))
    assert dispatches[0]["payload"] == {"prompt": "Run audits", "interval_seconds": 30}
    assert any("cron tetiklendi" in msg for msg in info_logs)

    async def _dispatch_fail(**_kwargs):
        stop_event.calls = 1
        raise RuntimeError("dispatch boom")

    stop_event = _StopAfterOne()
    monkeypatch.setattr(mod, "_dispatch_autonomy_trigger", _dispatch_fail)
    asyncio.run(mod._autonomous_cron_loop(stop_event))
    assert any("dispatch boom" in msg for msg in warning_logs)


def test_app_lifespan_starts_and_cancels_autonomous_cron_task(mod, monkeypatch):
    mod.cfg.ENABLE_AUTONOMOUS_CRON = True
    events = {"prewarm_cancelled": False, "cron_cancelled": False, "close": 0, "shutdown": 0}

    async def _prewarm():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            events["prewarm_cancelled"] = True
            raise

    async def _cron_loop(stop_event):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            events["cron_cancelled"] = stop_event.is_set()
            raise

    monkeypatch.setattr(mod.Config, "validate_critical_settings", staticmethod(lambda: None))
    monkeypatch.setattr(mod, "_prewarm_rag_embeddings", _prewarm)
    monkeypatch.setattr(mod, "_autonomous_cron_loop", _cron_loop)
    monkeypatch.setattr(mod, "_close_redis_client", lambda: asyncio.sleep(0, result=events.__setitem__("close", events["close"] + 1)))
    monkeypatch.setattr(mod, "_async_force_shutdown_local_llm_processes", lambda: asyncio.sleep(0, result=events.__setitem__("shutdown", events["shutdown"] + 1)))

    async def _run():
        async with mod._app_lifespan(mod.app):
            await asyncio.sleep(0)

    asyncio.run(_run())
    assert events == {"prewarm_cancelled": True, "cron_cancelled": True, "close": 1, "shutdown": 1}


def test_ws_stream_agent_text_response_handles_tool_thought_and_voice_segments(mod):
    async def _respond(_prompt):
        for chunk in ["\x00TOOL:search\x00", "\x00THOUGHT:plan\x00", "normal"]:
            yield chunk

    agent = types.SimpleNamespace(respond=_respond)

    class _WebSocket:
        def __init__(self):
            self.sent = []
            self._sidar_voice_pipeline = _StreamingVoicePipeline()
            self._sidar_voice_duplex_state = types.SimpleNamespace(assistant_turn_id=7, output_text_buffer="", last_interrupt_reason="")

        async def send_json(self, payload):
            self.sent.append(payload)

    ws = _WebSocket()
    asyncio.run(mod._ws_stream_agent_text_response(ws, agent, "hello"))

    assert {"tool_call": "search"} in ws.sent
    assert {"thought": "plan"} in ws.sent
    assert {"chunk": "normal"} in ws.sent
    audio_packets = [item for item in ws.sent if item.get("audio_text")]
    assert [item["audio_text"] for item in audio_packets] == ["normal", "trailing"]


def test_ws_stream_agent_text_response_skips_voice_output_when_pipeline_disabled(mod):
    async def _respond(_prompt):
        yield "only-text"

    agent = types.SimpleNamespace(respond=_respond)

    class _WebSocket:
        def __init__(self):
            self.sent = []
            self._sidar_voice_pipeline = types.SimpleNamespace(enabled=False)
            self._sidar_voice_duplex_state = None

        async def send_json(self, payload):
            self.sent.append(payload)

    ws = _WebSocket()
    asyncio.run(mod._ws_stream_agent_text_response(ws, agent, "hello"))
    assert ws.sent == [{"chunk": "only-text"}]


def test_hmac_and_feature_gate_errors_are_exposed(mod):
    with pytest.raises(mod.HTTPException) as missing_sig:
        mod._verify_hmac_signature(b"{}", "secret", "", label="Autonomy webhook")
    assert missing_sig.value.status_code == 401

    good_signature = "sha256=" + mod.hmac.new(b"secret", b"{}", mod.hashlib.sha256).hexdigest()
    mod._verify_hmac_signature(b"{}", "secret", good_signature, label="Autonomy webhook")

    with pytest.raises(mod.HTTPException) as bad_sig:
        mod._verify_hmac_signature(b"{}", "secret", "sha256=bad", label="Autonomy webhook")
    assert bad_sig.value.detail == "Geçersiz imza."

    mod.cfg.ENABLE_EVENT_WEBHOOKS = False
    with pytest.raises(mod.HTTPException) as webhook_disabled:
        asyncio.run(mod.autonomy_webhook("github", _FakeRequest(body_bytes=b"{}"), ""))
    assert webhook_disabled.value.status_code == 503

    mod.cfg.ENABLE_EVENT_WEBHOOKS = True
    mod.cfg.AUTONOMY_WEBHOOK_SECRET = ""
    invalid_json = asyncio.run(mod.autonomy_webhook("github", _FakeRequest(body_bytes=b"{"), ""))
    assert invalid_json.status_code == 400

    mod.cfg.ENABLE_SWARM_FEDERATION = False
    req = mod._FederationTaskRequest(task_id="t1", source_system="ext", source_agent="a", target_agent="b", goal="g")
    with pytest.raises(mod.HTTPException) as federation_disabled:
        asyncio.run(mod.swarm_federation_execute(req, ""))
    assert federation_disabled.value.status_code == 503

    feedback_req = mod._FederationFeedbackRequest(
        feedback_id="fb1",
        source_system="ext",
        source_agent="a",
        action_name="act",
        status="done",
        summary="ok",
    )
    with pytest.raises(mod.HTTPException) as feedback_disabled:
        asyncio.run(mod.swarm_federation_feedback(feedback_req, ""))
    assert feedback_disabled.value.status_code == 503


def test_websocket_voice_import_auth_and_payload_limit_edges(mod, monkeypatch):
    _set_voice_agent(mod)

    ws = _VoiceWebSocket([])

    real_import = __import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.multimodal":
            raise ImportError("multimodal missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _raising_import)
    asyncio.run(mod.websocket_voice(ws))
    monkeypatch.setattr("builtins.__import__", real_import)

    multimodal_mod = types.ModuleType("core.multimodal")
    multimodal_mod.MultimodalPipeline = lambda *_a, **_k: object()
    with _ModulePatch("core.multimodal", multimodal_mod):
        asyncio.run(mod.websocket_voice(ws))
    assert {"error": "core.multimodal modülü yüklenemedi.", "done": True} in ws.sent
    assert ws.closed == (1011, "multimodal unavailable")

    mod.cfg.VOICE_WS_MAX_BYTES = 4
    multimodal_mod, voice_mod = _install_voice_modules(transcribe_result={"success": True, "text": "x"}, voice_pipeline_cls=_BasicVoicePipeline)

    bad_header = _VoiceWebSocket([], token="bad-token")
    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(bad_header))
    assert bad_header.closed == (1008, "Invalid or expired token")

    oversized_binary = _VoiceWebSocket([{"type": "websocket.receive", "bytes": b"12345"}])
    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(oversized_binary))
    assert oversized_binary.closed == (1008, "Voice payload too large")

    encoded = base64.b64encode(b"12345").decode("ascii")
    oversized_base64 = _VoiceWebSocket([
        {"type": "websocket.receive", "text": json.dumps({"action": "append_base64", "chunk": encoded})}
    ])
    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(oversized_base64))
    assert {"auth_ok": True} in oversized_base64.sent
    assert oversized_base64.closed == (1008, "Voice payload too large")


def test_websocket_voice_misc_actions_and_turn_error_paths(mod, monkeypatch):
    _set_voice_agent(mod)
    mod.cfg.VOICE_WS_MAX_BYTES = 64

    async def _stream_llm_error(*_args, **_kwargs):
        raise mod.LLMAPIError("boom", provider="stub", status_code=429)

    multimodal_mod, voice_mod = _install_voice_modules(
        transcribe_result={"success": True, "text": "merhaba", "language": "tr", "provider": "whisper"},
        voice_pipeline_cls=_RichVoicePipeline,
    )
    monkeypatch.setattr(mod, "_ws_stream_agent_text_response", _stream_llm_error)

    events = [
        {"type": "websocket.receive", "text": json.dumps({"action": "start", "mime_type": "audio/mp3", "language": "tr", "prompt": "p"})},
        {"type": "websocket.receive"},
        {"type": "websocket.receive", "text": "{"},
        {"type": "websocket.receive", "text": json.dumps({"action": "append_base64", "chunk": ""})},
        {"type": "websocket.receive", "text": json.dumps({"action": "noop"})},
        {"type": "websocket.receive", "text": json.dumps({"action": "cancel"})},
        {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
        {"type": "websocket.receive", "bytes": b"audio"},
        {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
        {"type": "websocket.disconnect"},
    ]
    ws = _VoiceWebSocket(events)

    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert any(item.get("voice_session") == "ready" and item.get("mime_type") == "audio/mp3" for item in ws.sent)
    assert any(item.get("voice_state") == "ready" for item in ws.sent)
    assert any(item.get("voice_state") == "cancelled" for item in ws.sent)
    assert {"cancelled": True, "done": True} in ws.sent
    assert {"error": "İşlenecek ses verisi bulunamadı.", "done": True} in ws.sent
    assert {"buffered_bytes": 5} in ws.sent
    assert any(item.get("voice_state") == "processed" for item in ws.sent)
    assert any("[LLM Hatası] stub (429): boom" in item.get("chunk", "") for item in ws.sent)

    async def _stream_generic_error(*_args, **_kwargs):
        raise RuntimeError("voice crash")

    monkeypatch.setattr(mod, "_ws_stream_agent_text_response", _stream_generic_error)
    ws_generic = _VoiceWebSocket([
        {"type": "websocket.receive", "bytes": b"audio"},
        {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
        {"type": "websocket.disconnect"},
    ])
    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(ws_generic))
    assert any("[Sistem Hatası] voice crash" in item.get("chunk", "") for item in ws_generic.sent)

    multimodal_fail, voice_fail = _install_voice_modules(transcribe_result={"success": False, "reason": "bad audio"}, voice_pipeline_cls=_RichVoicePipeline)
    ws_transcribe_fail = _VoiceWebSocket([
        {"type": "websocket.receive", "bytes": b"audio"},
        {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
        {"type": "websocket.disconnect"},
    ])
    with _ModulePatch("core.multimodal", multimodal_fail), _ModulePatch("core.voice", voice_fail):
        asyncio.run(mod.websocket_voice(ws_transcribe_fail))
    assert {"error": "bad audio", "done": True} in ws_transcribe_fail.sent

    multimodal_empty, voice_empty = _install_voice_modules(transcribe_result={"success": True, "text": "", "language": "tr", "provider": "whisper"}, voice_pipeline_cls=_RichVoicePipeline)
    ws_empty = _VoiceWebSocket([
        {"type": "websocket.receive", "bytes": b"audio"},
        {"type": "websocket.receive", "text": json.dumps({"action": "commit"})},
        {"type": "websocket.disconnect"},
    ])
    with _ModulePatch("core.multimodal", multimodal_empty), _ModulePatch("core.voice", voice_empty):
        asyncio.run(mod.websocket_voice(ws_empty))
    assert {"done": True} in ws_empty.sent