import asyncio
import json
import types
from types import SimpleNamespace

import pytest

from agent.core.contracts import DelegationRequest, TaskResult
from agent.core.supervisor import SupervisorAgent
from agent.roles.coder_agent import CoderAgent
from core.llm_client import LLMClient, OllamaClient, AnthropicClient
from core.llm_metrics import LLMMetricsCollector
from tests.test_web_server_runtime import _load_web_server, _make_agent


async def _collect(aiter):
    out = []
    async for item in aiter:
        out.append(item)
    return out


def test_supervisor_retry_loop_routes_p2p_for_coder_and_reviewer(monkeypatch):
    sup = SupervisorAgent()
    calls = {"n": 0, "routes": 0}

    async def fake_delegate(receiver, goal, intent, parent_task_id=None, sender="supervisor"):
        calls["n"] += 1
        if calls["n"] == 1:
            return TaskResult("t1", "done", "initial-code")
        if calls["n"] == 2:
            return TaskResult("t2", "done", "[test:fail] düzeltme gerekli")
        if calls["n"] == 3:
            return TaskResult(
                "t3",
                "done",
                DelegationRequest(task_id="d1", reply_to="coder", target_agent="reviewer", payload="review_code|patched"),
            )
        return TaskResult(
            "t4",
            "done",
            DelegationRequest(task_id="d2", reply_to="reviewer", target_agent="coder", payload="qa_feedback|decision=approve"),
        )

    async def fake_route(_request, **_kwargs):
        calls["routes"] += 1
        if calls["routes"] == 1:
            return TaskResult("r1", "done", "revised-code")
        return TaskResult("r2", "done", "[REVIEW:PASS] tamam")

    monkeypatch.setattr(sup, "_delegate", fake_delegate)
    monkeypatch.setattr(sup, "_route_p2p", fake_route)

    result = asyncio.run(sup.run_task("özellik geliştir"))
    assert "revised-code" in result
    assert "REVIEW:PASS" in result
    assert calls["routes"] == 2


def test_coder_agent_qa_feedback_approved_branch():
    agent = CoderAgent()
    out = asyncio.run(agent.run_task("qa_feedback|decision=approve"))
    assert out.startswith("[CODER:APPROVED]")


def test_coder_agent_request_review_delegation_branch():
    agent = CoderAgent()
    out = asyncio.run(agent.run_task("request_review|print('ok')"))
    assert isinstance(out, DelegationRequest)
    assert out.target_agent == "reviewer"


def test_llmclient_invalid_provider_raises_value_error():
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=30)
    with pytest.raises(ValueError):
        LLMClient("xyz", cfg)


def test_llmclient_openai_fallback_compat_helpers():
    cfg = SimpleNamespace(OPENAI_API_KEY="k", OPENAI_TIMEOUT=30, OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=20)
    fac = LLMClient("openai", cfg)
    assert fac._ollama_base_url == "http://localhost:11434"
    assert hasattr(fac._build_ollama_timeout(), "connect")
    assert asyncio.run(fac.list_ollama_models()) == []
    assert asyncio.run(fac.is_ollama_available()) is False

    class _Chunk:
        text = "g"

    class _ResponseStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            if hasattr(self, "_done"):
                raise StopAsyncIteration
            self._done = True
            return _Chunk()

    chunks = asyncio.run(_collect(fac._stream_gemini_generator(_ResponseStream())))
    assert chunks == ["g"]


def test_ollama_stream_response_ignores_trailing_invalid_json(monkeypatch):
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=30, USE_GPU=False)
    client = OllamaClient(cfg)

    class _RespCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'{"message":{"content":"ok"}}\ninvalid'

    class _HttpClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, *_args, **_kwargs):
            return _RespCtx()

    monkeypatch.setattr("core.llm_client.httpx.AsyncClient", _HttpClient)
    chunks = asyncio.run(_collect(client._stream_response("u", {}, timeout=client._build_timeout())))
    assert chunks == ["ok"]


def test_anthropic_split_system_messages_keeps_non_empty_system_text():
    system, conversation = AnthropicClient._split_system_and_messages([
        {"role": "system", "content": "kural"},
        {"role": "system", "content": ""},
        {"role": "user", "content": "selam"},
    ])
    assert system == "kural"
    assert conversation == [{"role": "user", "content": "selam"}]


def test_llm_metrics_snapshot_computes_latency_average():
    collector = LLMMetricsCollector(max_events=16)
    collector.record(provider="ollama", model="test", latency_ms=100.0, prompt_tokens=1, completion_tokens=1)
    snap = collector.snapshot()
    assert snap["by_provider"]["ollama"]["latency_ms_avg"] == 100.0


def test_web_server_register_conflict_admin_stats_and_rate_limit_fallback(monkeypatch):
    mod = _load_web_server()
    agent, _calls = _make_agent()

    async def _raise_register(**_kwargs):
        raise RuntimeError("exists")

    async def _admin_stats():
        return {"users": 3}

    agent.memory.db.register_user = _raise_register
    agent.memory.db.get_admin_stats = _admin_stats

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    with pytest.raises(mod.HTTPException) as exc:
        asyncio.run(mod.register_user({"username": "alice", "password": "123456"}))
    assert exc.value.status_code == 409

    resp = asyncio.run(mod.admin_stats(_user=types.SimpleNamespace(role="admin", username="root")))
    assert resp.content == {"users": 3}

    class _Redis:
        async def incr(self, _key):
            raise RuntimeError("redis down")

    async def _get_redis():
        return _Redis()

    seen = {"fallback": False}

    async def _local(*_args, **_kwargs):
        seen["fallback"] = True
        return True

    mod._get_redis = _get_redis
    monkeypatch.setattr(mod, "_local_is_rate_limited", _local)
    assert asyncio.run(mod._redis_is_rate_limited("chat", "k", 1, 60)) is True
    assert seen["fallback"] is True


def test_web_server_usage_sink_prewarm_and_websocket_auth_edges(monkeypatch):
    mod = _load_web_server()
    agent, _calls = _make_agent()

    class _Collector:
        def __init__(self):
            self._sidar_usage_sink_bound = False
            self.sink = None

        def set_usage_sink(self, sink):
            self.sink = sink

    collector = _Collector()
    monkeypatch.setattr(mod, "get_llm_metrics_collector", lambda: collector)

    async def _raise_usage(**_kwargs):
        raise RuntimeError("db err")

    agent.memory.db.record_provider_usage_daily = _raise_usage
    mod._bind_llm_usage_sink(agent)

    logs = []
    monkeypatch.setattr(mod.logger, "debug", lambda *args, **kwargs: logs.append(args))

    async def _run_sink():
        collector.sink(types.SimpleNamespace(user_id="u1", provider="ollama", total_tokens=5))
        await asyncio.sleep(0)

    asyncio.run(_run_sink())
    assert logs

    async def _get_agent():
        return types.SimpleNamespace(rag=types.SimpleNamespace(_chroma_available=True, _init_chroma=lambda: (_ for _ in ()).throw(RuntimeError("boom"))))

    warnings = []
    mod.get_agent = _get_agent
    monkeypatch.setattr(mod.logger, "warning", lambda *args, **kwargs: warnings.append(args))
    asyncio.run(mod._prewarm_rag_embeddings())
    assert warnings

    class _WS:
        def __init__(self):
            self.closed = None
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self._messages = iter(["not-json", json.dumps({"action": "auth"})])

        async def accept(self):
            return None

        async def receive_text(self):
            return next(self._messages)

        async def close(self, code, reason):
            self.closed = (code, reason)

        async def send_json(self, payload):
            return None

    agent.memory.db.get_user_by_token = lambda _t: None
    mod.get_agent = lambda: asyncio.sleep(0, result=agent)
    ws = _WS()
    asyncio.run(mod.websocket_chat(ws))
    assert ws.closed[0] == 1008
    assert "missing" in ws.closed[1].lower()
