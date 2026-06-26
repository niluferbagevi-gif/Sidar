"""Integration coverage for swarm federation handoff and timeout behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent.core.contracts import DelegationRequest, FederationTaskEnvelope, TaskResult
from agent.registry import AgentSpec
from agent.swarm import SwarmOrchestrator, SwarmTask


@pytest.mark.asyncio
@pytest.mark.integration
async def test_swarm_federation_protocol_handoff_fails_closed_on_cascade_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = SimpleNamespace(
        SWARM_TASK_MAX_RETRIES=0,
        SWARM_TASK_TIMEOUT_SECONDS=0.01,
        SWARM_MAX_HANDOFF_HOPS=3,
    )
    orchestrator = SwarmOrchestrator(cfg=cfg)
    envelope = FederationTaskEnvelope(
        task_id="fed-timeout-1",
        source_system="external-swarm",
        source_agent="planner",
        target_system="sidar",
        target_agent="researcher",
        goal="Federated cascade timeout should fail closed",
        intent="rag_search",
        context={"tenant": "acme"},
        correlation_id="corr-fed-1",
    )

    specs = {
        "researcher": AgentSpec(role_name="researcher", capabilities=["rag_search"]),
        "reviewer": AgentSpec(role_name="reviewer", capabilities=["code_review"]),
    }
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role: specs.get(role or ""))

    class _FederationAgent:
        def __init__(self, role: str) -> None:
            self.role = role

        async def handle(self, task_envelope):
            if self.role == "researcher":
                return TaskResult(
                    task_id=task_envelope.task_id,
                    status="success",
                    summary=DelegationRequest(
                        task_id=task_envelope.task_id,
                        reply_to="researcher",
                        target_agent="reviewer",
                        payload="Reviewer cascade step",
                        intent="code_review",
                        parent_task_id=task_envelope.task_id,
                        meta={"reason": "federation-cascade"},
                    ),
                    evidence=[task_envelope.context["correlation_id"]],
                )
            await asyncio.sleep(0.05)
            return TaskResult(task_id=task_envelope.task_id, status="success", summary="late")

    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda role_name, **_kwargs: _FederationAgent(role_name),
    )

    result = await orchestrator._execute_task(
        SwarmTask(
            goal=envelope.to_prompt(),
            intent=envelope.intent,
            context={**envelope.context, "correlation_id": envelope.correlation_id},
            task_id=envelope.task_id,
            preferred_agent=envelope.target_agent,
        ),
        session_id="fed-session",
    )

    assert result.status == "failed"
    assert result.agent_role == "reviewer"
    assert "timeout" in result.summary.lower()
    assert result.handoffs == [
        {
            "task_id": "fed-timeout-1",
            "sender": "researcher",
            "receiver": "reviewer",
            "reason": "federation-cascade",
            "intent": "code_review",
            "handoff_depth": "1",
            "swarm_hop": "1",
        }
    ]
