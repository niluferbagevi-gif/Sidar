from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from web.routes.hitl import build_hitl_router
from web.routes.metrics import _resolve_web_server_helper, build_metrics_router


async def _async_value(value: Any) -> Any:
    return value


def test_hitl_pending_accepts_synchronous_store_result(make_test_client: Any) -> None:
    item = SimpleNamespace(to_dict=lambda: {"request_id": "req-1"})
    router = build_hitl_router(
        get_request_user=lambda: None,
        resolve_agent_instance=lambda: _async_value(SimpleNamespace()),
        await_if_needed=lambda value: value,
        resolve_user_from_token=lambda *_args: None,
        ws_close_policy_violation=lambda *_args: _async_value(None),
        hitl_ws_clients=set(),
        get_hitl_store=lambda: SimpleNamespace(pending=lambda: [item]),
        get_hitl_gate=lambda: SimpleNamespace(timeout=10),
    )

    app = FastAPI()
    app.include_router(router)
    response = make_test_client(app).get("/api/hitl/pending")

    assert response.status_code == 200
    assert response.json() == {"pending": [{"request_id": "req-1"}], "count": 1}


@pytest.mark.asyncio
async def test_hitl_websocket_extracts_bearer_token_and_rejects_invalid_user() -> None:
    closed: list[str] = []

    class _WebSocket:
        headers = {"authorization": "Bearer invalid-token"}
        accepted: list[str | None] = []

        async def accept(self, subprotocol: str | None = None) -> None:
            self.accepted.append(subprotocol)

    websocket = _WebSocket()

    async def _close_policy_violation(_websocket: Any, reason: str) -> None:
        closed.append(reason)

    router = build_hitl_router(
        get_request_user=lambda: None,
        resolve_agent_instance=lambda: _async_value(SimpleNamespace()),
        await_if_needed=_async_value,
        resolve_user_from_token=lambda _agent, _token: None,
        ws_close_policy_violation=_close_policy_violation,
        hitl_ws_clients=set(),
        get_hitl_store=lambda: SimpleNamespace(pending=lambda: []),
        get_hitl_gate=lambda: SimpleNamespace(timeout=10),
    )

    await router.legacy_exports["websocket_hitl"](websocket)

    assert websocket.accepted == [None]
    assert closed == ["Invalid or expired token"]


def test_metrics_helper_returns_default_when_legacy_module_lacks_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "web_server", ModuleType("web_server"))
    default = object()

    assert _resolve_web_server_helper("missing_helper", default) is default


def test_metrics_temporarily_sets_empty_username_and_awaits_sync_named_session_provider(make_test_client: Any) -> None:
    class _Memory:
        active_user_id = "previous-user"
        active_username = ""

        async def get_all_sessions(self) -> list[str]:
            return ["session-1", "session-2"]

        def __len__(self) -> int:
            return 0

    memory = _Memory()
    agent = SimpleNamespace(
        VERSION="test",
        docs=SimpleNamespace(doc_count=0),
        memory=memory,
        cfg=SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False),
    )
    router = build_metrics_router(
        require_metrics_access=lambda: {"id": "metrics-user"},
        resolve_agent_instance=lambda: _async_value(agent),
        start_time=0.0,
        local_rate_limits={},
        get_llm_metrics_collector=lambda: SimpleNamespace(snapshot=lambda: {"totals": {}}),
        render_llm_metrics_prometheus=lambda _snapshot: "",
        set_current_metrics_user_id=lambda _user_id: "token",
        reset_current_metrics_user_id=lambda _token: None,
        logger=SimpleNamespace(debug=lambda *_args: None),
    )

    app = FastAPI()
    app.include_router(router)
    response = make_test_client(app).get("/metrics")

    assert response.status_code == 200
    assert response.json()["sessions_total"] == 2
    assert memory.active_user_id == "previous-user"
    assert memory.active_username == ""
