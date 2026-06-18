from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from web.routes import autonomy, federation


class _Request:
    def __init__(self, payload: dict[str, Any] | bytes) -> None:
        self._payload = (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        )

    async def body(self) -> bytes:
        return self._payload


@pytest.mark.asyncio
async def test_autonomy_webhook_dispatches_general_event() -> None:
    calls: list[dict[str, Any]] = []

    async def _dispatch(**kwargs):
        calls.append(kwargs)
        return {"trigger_id": "t1"}

    async def _await_if_needed(value):
        return await value if hasattr(value, "__await__") else value

    autonomy.configure_autonomy_dependencies(
        lambda: SimpleNamespace(
            cfg=SimpleNamespace(ENABLE_EVENT_WEBHOOKS=True, AUTONOMY_WEBHOOK_SECRET=""),
            verify_hmac_signature=lambda *_args, **_kwargs: None,
            resolve_ci_failure_context=lambda *_args, **_kwargs: None,
            run_event_driven_federation_workflow=lambda **_kwargs: None,
            embed_event_driven_federation_payload=lambda payload, _workflow: payload,
            dispatch_autonomy_trigger=_dispatch,
            await_if_needed=_await_if_needed,
            resolve_agent_instance=lambda: None,
        )
    )

    response = await autonomy.autonomy_webhook("jira", _Request({"event_name": "issue_created"}))

    assert response.status_code == 200
    assert calls[0]["trigger_source"] == "webhook:jira"
    assert calls[0]["event_name"] == "issue_created"


@dataclass
class _Envelope:
    task_id: str
    source_system: str
    source_agent: str
    target_system: str
    target_agent: str
    goal: str
    protocol: str
    intent: str
    context: dict[str, str]
    inputs: list[str]
    meta: dict[str, str]
    correlation_id: str

    def to_prompt(self) -> str:
        return self.goal


@dataclass
class _Result:
    task_id: str
    source_system: str
    source_agent: str
    target_system: str
    target_agent: str
    status: str
    summary: str
    protocol: str
    correlation_id: str
    meta: dict[str, str] = field(default_factory=dict)


@pytest.mark.asyncio
async def test_federation_execute_builds_autonomy_payload() -> None:
    calls: list[dict[str, Any]] = []

    async def _dispatch(**kwargs):
        calls.append(kwargs)
        return {"trigger_id": "tr1", "summary": "done"}

    federation.configure_federation_dependencies(
        lambda: SimpleNamespace(
            cfg=SimpleNamespace(ENABLE_SWARM_FEDERATION=True, SWARM_FEDERATION_SHARED_SECRET=""),
            verify_hmac_signature=lambda *_args, **_kwargs: None,
            federation_task_envelope_cls=_Envelope,
            federation_task_result_cls=_Result,
            normalize_federation_protocol=lambda protocol: protocol or "federation.v1",
            legacy_federation_protocol_v1="v1",
            dispatch_autonomy_trigger=_dispatch,
            action_feedback_cls=None,
            derive_correlation_id=lambda *parts: "corr",
        )
    )

    response = await federation.swarm_federation_execute(
        federation.FederationTaskRequest(
            task_id="task-1",
            source_system="external",
            source_agent="crew",
            goal="run it",
        )
    )

    assert response.status_code == 200
    assert calls[0]["trigger_source"] == "federation:external"
    assert calls[0]["payload"]["federation_task"]["task_id"] == "task-1"
