from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.auto_handle import AutoHandle
from agent.roles.coverage_agent import CoverageAgent
from agent.roles.poyraz_agent import PoyrazAgent
from agent.roles.reviewer_agent import ReviewerAgent
from agent.sidar_agent import SidarAgent
from agent.swarm import SwarmOrchestrator, SwarmTask
from agent.registry import AgentSpec
from managers.package_info import PackageInfoManager
from managers.system_health import SystemHealthManager
from managers.todo_manager import TodoManager
from managers.web_search import WebSearchManager


RED_ZONE_MODULES = {
    "agent/sidar_agent.py",
    "agent/swarm.py",
    "agent/auto_handle.py",
    "agent/roles/reviewer_agent.py",
    "agent/roles/coverage_agent.py",
    "agent/roles/poyraz_agent.py",
    "managers/system_health.py",
    "managers/todo_manager.py",
    "managers/web_search.py",
    "managers/package_info.py",
}


def test_red_zone_module_inventory_is_explicit_and_complete() -> None:
    assert len(RED_ZONE_MODULES) == 10
    assert "agent/roles/poyraz_agent.py" in RED_ZONE_MODULES
    assert "managers/package_info.py" in RED_ZONE_MODULES


async def test_sidar_agent_respond_critical_flow_uses_shared_fixtures(
    agent_factory,
    fake_llm_response,
    fake_event_stream,
) -> None:
    agent = agent_factory(SidarAgent)
    agent.initialize = AsyncMock()
    agent._memory_add = AsyncMock()

    async def _fake_multi(user_input: str) -> str:
        llm_payload = await fake_llm_response(user_input)
        last_event = ""
        async for event in fake_event_stream():
            last_event = event.message
        return f"{llm_payload['content']}::{last_event}"

    agent._try_multi_agent = AsyncMock(side_effect=_fake_multi)

    chunks = [chunk async for chunk in agent.respond("kritik akış testi")]

    assert len(chunks) == 1
    assert "mock-response" in chunks[0]
    assert "İşlem tamam." in chunks[0]


async def test_swarm_execute_task_and_auto_handle_are_isolated(monkeypatch) -> None:
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    spec = AgentSpec(role_name="researcher", capabilities=["web_search"])

    class _RunTaskAgent:
        async def run_task(self, _goal: str) -> str:
            return "isolated-ok"

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: spec)
    monkeypatch.setattr("agent.swarm.AgentCatalog.create", lambda *_args, **_kwargs: _RunTaskAgent())

    result = await orchestrator._execute_task(SwarmTask(goal="araştır", intent="research"), session_id="s-1")
    assert result.status == "success"
    assert result.summary == "isolated-ok"

    web = SimpleNamespace(search=AsyncMock(return_value=(True, "aranan-sonuç")))
    auto = AutoHandle(
        code=SimpleNamespace(),
        health=SimpleNamespace(),
        github=SimpleNamespace(),
        memory=SimpleNamespace(),
        web=web,
        pkg=SimpleNamespace(),
        docs=SimpleNamespace(),
        cfg=SimpleNamespace(),
    )
    handled, out = await auto._try_web_search("web'de ara sidar", "web'de ara sidar")
    assert handled is True
    assert out == "aranan-sonuç"


async def test_reviewer_and_coverage_agent_generate_candidates_with_fake_llm(
    fake_llm_response,
    agent_factory,
) -> None:
    reviewer = agent_factory(ReviewerAgent)

    async def _reviewer_llm(*_args, **_kwargs):
        _ = await fake_llm_response("reviewer")
        return "def test_generated_reviewer_case():\n    assert True\n"

    reviewer.call_llm = _reviewer_llm
    dynamic_test = await reviewer._build_dynamic_test_content("diff --git a/x.py b/x.py")
    assert "def test_generated_reviewer_case" in dynamic_test

    coverage = agent_factory(CoverageAgent)

    async def _coverage_llm(*_args, **_kwargs):
        payload = await fake_llm_response("coverage")
        return f"# {payload['content']}\ndef test_generated_coverage_case():\n    assert 1 == 1\n"

    coverage.call_llm = _coverage_llm
    generated = await coverage._tool_generate_missing_tests(
        json.dumps(
            {
                "coverage_finding": {
                    "target_path": "core/vision.py",
                    "missing_lines": [10, 11],
                },
                "coveragerc": {"fail_under": 90},
            }
        )
    )
    assert "test_generated_coverage_case" in generated


async def test_poyraz_social_and_video_flows_use_shared_fakes(
    fake_social_api,
    fake_video_stream,
    monkeypatch,
    agent_factory,
) -> None:
    agent = agent_factory(PoyrazAgent)
    agent.social = fake_social_api
    agent.docs = SimpleNamespace()
    agent.llm = object()
    agent.cfg = SimpleNamespace()

    agent.social.publish_content = AsyncMock(return_value=(True, {"id": "post-1"}))
    social_result = await agent._tool_publish_social("instagram|||Merhaba dünya|||sidar")
    assert "[SOCIAL:PUBLISHED]" in social_result

    class _FakePipeline:
        def __init__(self, *_args, **_kwargs):
            self.stream = fake_video_stream

        async def analyze_media_source(self, **_kwargs):
            frames = await self.stream.read_frames()
            return {
                "success": True,
                "scene_summary": f"frames={len(frames)}",
                "document_ingest": {"doc_id": "doc-123"},
            }

    monkeypatch.setattr("core.multimodal.MultimodalPipeline", _FakePipeline)
    ingested = await agent._tool_ingest_video_insights("https://video.example/test.mp4|||ürün analizi")
    assert "[VIDEO:INGESTED]" in ingested
    assert "doc-123" in ingested


async def test_external_managers_smoke_with_isolated_dependencies(tmp_path, monkeypatch, frozen_time) -> None:
    health_cfg = SimpleNamespace(
        ENABLE_DEPENDENCY_HEALTHCHECKS=True,
        REDIS_URL="",
        DATABASE_URL="",
        HEALTHCHECK_CONNECT_TIMEOUT_MS=50,
    )
    health = SystemHealthManager(cfg=health_cfg)
    monkeypatch.setattr(health, "get_cpu_usage", lambda interval=None: 12.5)
    monkeypatch.setattr(health, "get_memory_info", lambda: {"percent": 34.0})
    monkeypatch.setattr(health, "get_gpu_info", lambda: {"available": False})
    monkeypatch.setattr(health, "check_ollama", lambda: True)
    summary = health.get_health_summary()
    assert summary["status"] in {"healthy", "degraded"}
    assert "dependencies" in summary

    todo = TodoManager(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    assert "eklendi" in todo.add_task("kritik test görevi")

    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    web = WebSearchManager(
        SimpleNamespace(
            SEARCH_ENGINE="tavily",
            TAVILY_API_KEY="test-key",
            GOOGLE_SEARCH_API_KEY="",
            GOOGLE_SEARCH_CX="",
            WEB_SEARCH_MAX_RESULTS=5,
            WEB_FETCH_TIMEOUT=5,
            WEB_SCRAPE_MAX_CHARS=1000,
        )
    )

    async def _fake_tavily(_query, _n):
        return True, "web-ok"

    web._search_tavily = _fake_tavily
    ok, text = await web.search("sidar")
    assert ok is True and text == "web-ok"

    pkg = PackageInfoManager()

    async def _fake_fetch(_package):
        return True, {"info": {"version": "1.2.3"}, "releases": {"1.2.3": {}}}, ""

    pkg._fetch_pypi_json = _fake_fetch
    ok, latest = await pkg.pypi_latest_version("sidar")
    assert ok is True
    assert latest == "sidar==1.2.3"


async def test_sidar_agent_llm_error_flow(
    agent_factory,
    fake_llm_error,
    fake_event_stream,
) -> None:
    _ = fake_event_stream
    agent = agent_factory(SidarAgent)
    agent.initialize = AsyncMock()
    agent._try_multi_agent = AsyncMock(side_effect=fake_llm_error)

    with pytest.raises(RuntimeError, match="rate limit exceeded"):
        _chunks = [chunk async for chunk in agent.respond("hata tetikle")]


async def test_poyraz_agent_error_flows(
    agent_factory,
    fake_social_api,
    fake_video_stream_error,
    monkeypatch,
) -> None:
    agent = agent_factory(PoyrazAgent)
    agent.social = fake_social_api
    agent.docs = SimpleNamespace()
    agent.llm = object()
    agent.cfg = SimpleNamespace()

    agent.social.set_rate_limit_error()
    agent.social.publish_content = AsyncMock(side_effect=RuntimeError("API Rate Limit"))

    with pytest.raises(RuntimeError, match="API Rate Limit"):
        await agent._tool_publish_social("instagram|||hata testi|||sidar")

    class _FakeErrorPipeline:
        def __init__(self, *_args, **_kwargs):
            self.stream = fake_video_stream_error

        async def analyze_media_source(self, **_kwargs):
            await self.stream.read_frames()

    monkeypatch.setattr("core.multimodal.MultimodalPipeline", _FakeErrorPipeline)

    with pytest.raises(RuntimeError, match="corrupted video stream"):
        await agent._tool_ingest_video_insights("https://video.example/broken.mp4|||analiz")
