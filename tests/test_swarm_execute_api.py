import asyncio
import types

from tests.test_web_server_runtime import _load_web_server


def test_resolve_policy_maps_swarm_api():
    mod = _load_web_server()
    request = types.SimpleNamespace(url=types.SimpleNamespace(path="/api/swarm/execute"), method="POST")
    assert mod._resolve_policy_from_request(request) == ("swarm", "execute", "*")


def test_execute_swarm_parallel_serializes_results(monkeypatch):
    mod = _load_web_server()
    calls = {}

    class _FakeOrchestrator:
        def __init__(self, cfg):
            calls["cfg"] = cfg

        async def run_parallel(self, tasks, *, session_id="", max_concurrency=4):
            calls["mode"] = "parallel"
            calls["session_id"] = session_id
            calls["max_concurrency"] = max_concurrency
            calls["tasks"] = tasks
            return [
                types.SimpleNamespace(
                    task_id="swarm-1",
                    agent_role="coder",
                    status="success",
                    summary="tamam",
                    elapsed_ms=12,
                    evidence=["e1"],
                )
            ]

    async def _get_agent():
        return types.SimpleNamespace(cfg=types.SimpleNamespace(AI_PROVIDER="openai"))

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "SwarmOrchestrator", _FakeOrchestrator)

    payload = types.SimpleNamespace(
        mode="parallel",
        session_id="sess-42",
        max_concurrency=3,
        tasks=[
            types.SimpleNamespace(goal="  Güvenlik taraması  ", intent="security_audit", context={"repo": "sidar"}, preferred_agent="reviewer"),
        ],
    )
    user = types.SimpleNamespace(id="u-1")

    response = asyncio.run(mod.execute_swarm(payload=payload, user=user))

    assert response.content["success"] is True
    assert response.content["mode"] == "parallel"
    assert response.content["results"][0]["agent_role"] == "coder"
    assert calls["mode"] == "parallel"
    assert calls["session_id"] == "sess-42"
    assert calls["max_concurrency"] == 3
    assert calls["tasks"][0].goal == "Güvenlik taraması"
    assert calls["tasks"][0].preferred_agent == "reviewer"


def test_execute_swarm_pipeline_uses_user_scoped_default_session(monkeypatch):
    mod = _load_web_server()
    calls = {}

    class _FakeOrchestrator:
        def __init__(self, cfg):
            calls["cfg"] = cfg

        async def run_pipeline(self, tasks, *, session_id=""):
            calls["mode"] = "pipeline"
            calls["session_id"] = session_id
            calls["tasks"] = tasks
            return [
                types.SimpleNamespace(
                    task_id="swarm-2",
                    agent_role="reviewer",
                    status="success",
                    summary="özet",
                    elapsed_ms=21,
                    evidence=[],
                )
            ]

    async def _get_agent():
        return types.SimpleNamespace(cfg=types.SimpleNamespace(AI_PROVIDER="ollama"))

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "SwarmOrchestrator", _FakeOrchestrator)

    payload = types.SimpleNamespace(
        mode="pipeline",
        session_id="   ",
        max_concurrency=4,
        tasks=[types.SimpleNamespace(goal="Refactor planı üret", intent="summarization", context={}, preferred_agent="")],
    )
    user = types.SimpleNamespace(id="tenant-user")

    response = asyncio.run(mod.execute_swarm(payload=payload, user=user))

    assert response.content["mode"] == "pipeline"
    assert response.content["session_id"] == "swarm-tenant-user"
    assert calls["mode"] == "pipeline"
    assert calls["session_id"] == "swarm-tenant-user"
    assert calls["tasks"][0].preferred_agent is None


def test_get_agent_initializes_sidar_agent_once(monkeypatch):
    mod = _load_web_server()
    mod._agent = None
    mod._agent_lock = asyncio.Lock()
    counters = {"init": 0, "bind": 0}

    class _FakeAgent:
        def __init__(self, cfg):
            self.cfg = cfg
            self.memory = types.SimpleNamespace(initialize=lambda: None)

        async def initialize(self):
            counters["init"] += 1

    monkeypatch.setattr(mod, "SidarAgent", _FakeAgent)
    monkeypatch.setattr(mod, "_bind_llm_usage_sink", lambda _agent: counters.__setitem__("bind", counters["bind"] + 1))

    first = asyncio.run(mod.get_agent())
    second = asyncio.run(mod.get_agent())

    assert first is second
    assert counters == {"init": 1, "bind": 1}