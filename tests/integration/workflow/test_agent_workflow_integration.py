import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.core.contracts import DelegationRequest, TaskResult
from agent.registry import AgentSpec
from agent.swarm import SwarmOrchestrator, SwarmTask
from managers.web_search import WebSearchManager
from tests.helpers import collect_async_chunks as _collect_stream


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_runs_research_pipeline_with_real_supervisor(
    sidar_agent_factory,
    fake_llm_response,
    fake_web_search_result,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Gerçek supervisor + researcher akışını, yalnızca dış web bağımlılığını izole ederek doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    # LLM bağımlılığını izole ederek testi deterministik hale getir.
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=fake_llm_response))

    await agent.memory.set_active_user("integration-user", "Integration User")

    search_mock = fake_web_search_result(True, "docs:ok:docs için araştırma yap")
    monkeypatch.setattr(WebSearchManager, "search", search_mock)

    out = await _collect_stream(agent.respond("docs için araştırma yap"))

    assert len(out) > 0
    history = await agent.memory.get_history()
    assert any(
        msg.get("role") == "user" and "docs için araştırma yap" in msg.get("content", "")
        for msg in history
    )
    assert any(msg.get("role") == "assistant" for msg in history)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_handles_search_failure(
    sidar_agent_factory,
    fake_llm_response,
    fake_web_search_result,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Arama başarısız olduğunda supervisor'ın çökmediğini ve durumu yönettiğini doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    # LLM bağımlılığını izole ederek testi deterministik hale getir.
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=fake_llm_response))

    await agent.memory.set_active_user("integration-user", "Integration User")

    search_mock = fake_web_search_result(
        False, "Arama sırasında hata oluştu: docs için araştırma yap"
    )
    monkeypatch.setattr(WebSearchManager, "search", search_mock)

    out = await _collect_stream(agent.respond("docs için araştırma yap"))

    assert len(out) > 0
    assert any("hata" in msg.lower() or "yapılamadı" in msg.lower() for msg in out)
    history = await agent.memory.get_history()
    assert any(
        msg.get("role") == "user" and "docs için araştırma yap" in msg.get("content", "")
        for msg in history
    )
    assert any(msg.get("role") == "assistant" for msg in history)
    assert agent._supervisor is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_executes_tool_sequence(
    sidar_agent_factory,
    fake_llm_tool_sequence,
    fake_web_search_result,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """LLM araç kararı + araç icrası + memory kaydını uçtan uca doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    agent.llm = types.SimpleNamespace(
        chat=fake_llm_tool_sequence(
            [
                '{"thought": "Önce web araması yapmalıyım.", "tool": "web_search", "argument": "pytest integration"}',
                '{"thought": "Artık nihai yanıtı verebilirim.", "tool": "final_answer", "argument": "Araştırma tamamlandı."}',
            ]
        )
    )

    await agent.memory.set_active_user("integration-user", "Integration User")

    search_mock = fake_web_search_result(True, "bulunan sonuc: pytest harikadır")
    monkeypatch.setattr(WebSearchManager, "search", search_mock)

    out = await _collect_stream(agent.respond("Pytest entegrasyonunu araştır"))

    search_mock.assert_awaited_once_with(agent.web, "pytest integration")
    assert any("Araştırma tamamlandı." in msg for msg in out)
    history = await agent.memory.get_history()
    assert any(
        msg.get("role") == "user" and "Pytest entegrasyonunu araştır" in msg.get("content", "")
        for msg in history
    )
    assert any(
        msg.get("role") == "assistant" and "Araştırma tamamlandı." in msg.get("content", "")
        for msg in history
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_handles_docs_search_vector_failure(
    sidar_agent_factory,
    fake_llm_tool_sequence,
    fake_vector_store,
    tmp_path,
) -> None:
    """RAG/vector araması patladığında akışın zarifçe sürdüğünü doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    agent.llm = types.SimpleNamespace(
        chat=fake_llm_tool_sequence(
            [
                '{"thought":"Önce depoda arama yap.", "tool":"docs_search", "argument":"vektör araması"}',
                '{"thought":"Hata durumunu kullanıcıya açıkla.", "tool":"final_answer", "argument":"Doküman araması şu anda kullanılamıyor."}',
            ]
        )
    )

    await agent.memory.set_active_user("integration-user", "Integration User")

    fake_vector_store.set_db_error()
    agent.docs = types.SimpleNamespace(search=fake_vector_store.search)

    out = await _collect_stream(agent.respond("Depodaki dokümanları ara"))

    assert len(out) > 0
    assert any("kullanılamıyor" in msg.lower() or "hata" in msg.lower() for msg in out)
    assert fake_vector_store.search.called

    history = await agent.memory.get_history()
    assert any(
        msg.get("role") == "user" and "Depodaki dokümanları ara" in msg.get("content", "")
        for msg in history
    )
    assert any(msg.get("role") == "assistant" for msg in history)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_swarm_pipeline_coordinates_roles_and_passes_success_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coder -> reviewer -> QA pipeline'ında başarılı özetler sonraki role aktarılır."""

    cfg = SimpleNamespace(SWARM_TASK_MAX_RETRIES=0, SWARM_TASK_TIMEOUT_SECONDS=1)
    orchestrator = SwarmOrchestrator(cfg=cfg)

    specs = {
        "coder": AgentSpec(role_name="coder", capabilities=["code_generation"]),
        "reviewer": AgentSpec(role_name="reviewer", capabilities=["code_review"]),
        "qa": AgentSpec(role_name="qa", capabilities=["test_generation"]),
    }
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role: specs.get(role or ""))

    seen_context: dict[str, dict[str, str]] = {}

    class _PipelineAgent:
        def __init__(self, role: str) -> None:
            self.role = role

        async def handle(self, envelope):
            seen_context[self.role] = dict(envelope.context)
            prev_keys = ",".join(sorted(key for key in envelope.context if key.startswith("prev_")))
            return TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary=f"{self.role} ok [{prev_keys}]",
                evidence=[f"handled:{self.role}"],
            )

    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda role_name, **_kwargs: _PipelineAgent(role_name),
    )

    tasks = [
        SwarmTask(goal="Implement feature", intent="code_generation", preferred_agent="coder"),
        SwarmTask(goal="Review feature", intent="code_review", preferred_agent="reviewer"),
        SwarmTask(goal="Validate feature", intent="test_generation", preferred_agent="qa"),
    ]

    results = await orchestrator.run_pipeline(tasks, session_id="pipeline-int")

    assert [result.status for result in results] == ["success", "success", "success"]
    assert [result.agent_role for result in results] == ["coder", "reviewer", "qa"]
    assert "prev_coder" in seen_context["reviewer"]
    assert seen_context["reviewer"]["prev_coder"].startswith("coder ok")
    assert "prev_coder" in seen_context["qa"]
    assert "prev_reviewer" in seen_context["qa"]
    assert results[-1].graph["session_id"] == "pipeline-int"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_swarm_graphrag_reviewer_handoff_stops_at_max_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GraphRAG/reviewer P2P döngüsü hop limitini aşınca fail-closed sonlanmalıdır."""

    cfg = SimpleNamespace(SWARM_MAX_HANDOFF_HOPS=1, SWARM_TASK_MAX_RETRIES=0)
    orchestrator = SwarmOrchestrator(cfg=cfg)
    researcher = AgentSpec(role_name="researcher", capabilities=["rag_search"])
    reviewer = AgentSpec(role_name="reviewer", capabilities=["code_review"])

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: researcher)
    monkeypatch.setattr(
        orchestrator.router,
        "route_by_role",
        lambda role: reviewer
        if role == "reviewer"
        else researcher
        if role == "researcher"
        else None,
    )

    class _LoopingHandoffAgent:
        def __init__(self, role: str) -> None:
            self.role = role

        async def handle(self, envelope):
            target = "reviewer" if self.role == "researcher" else "researcher"
            delegation = DelegationRequest(
                task_id=envelope.task_id,
                reply_to=self.role,
                target_agent=target,
                payload="GraphRAG bulgusunu reviewer ile tekrar değerlendir",
                intent="code_review" if target == "reviewer" else "rag_search",
                parent_task_id=envelope.parent_task_id or envelope.task_id,
                meta={"reason": "rerun-loop-negative-case"},
            )
            return TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary=delegation,
                evidence=[f"{self.role}->handoff"],
            )

    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda role_name, **_kwargs: _LoopingHandoffAgent(role_name),
    )

    result = await orchestrator.run(
        "GraphRAG bulgusunu reviewer akışıyla doğrula",
        intent="rag_search",
        session_id="graph-review-hop-limit",
    )

    assert result.status == "failed"
    assert "maksimum devir sayısı" in result.summary
    assert [handoff["receiver"] for handoff in result.handoffs] == ["reviewer", "researcher"]
    assert result.handoffs[-1]["reason"] == "rerun-loop-negative-case"
