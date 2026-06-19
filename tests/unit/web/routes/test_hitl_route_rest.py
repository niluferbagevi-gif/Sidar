from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI

import core.hitl as hitl_core
from web.routes.hitl import build_hitl_router


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def test_hitl_rest_routes_create_list_respond_and_report_missing(
    monkeypatch: Any,
    make_test_client: Any,
) -> None:
    stored: list[Any] = []
    notifications: list[str] = []

    class _Store:
        def pending(self) -> list[Any]:
            return stored

        def add(self, request: Any) -> None:
            stored.append(request)

    class _Gate:
        timeout = 60.0

        async def respond(self, request_id: str, **kwargs: Any) -> Any:
            if request_id == "missing":
                return None
            return SimpleNamespace(
                request_id=request_id, decision=SimpleNamespace(value="approved")
            )

    async def _notify(request: Any) -> None:
        notifications.append(request.request_id)

    monkeypatch.setattr(hitl_core, "notify", _notify)
    app = FastAPI()
    app.include_router(
        build_hitl_router(
            get_request_user=lambda: SimpleNamespace(username="admin"),
            resolve_agent_instance=lambda: None,
            await_if_needed=_await_if_needed,
            resolve_user_from_token=lambda *_args: None,
            ws_close_policy_violation=lambda *_args: None,
            hitl_ws_clients=set(),
            get_hitl_store=_Store,
            get_hitl_gate=_Gate,
        )
    )
    client = make_test_client(app)

    created = client.post(
        "/api/hitl/request",
        json={"action": "deploy", "description": "Approve deploy", "payload": {"env": "prod"}},
    )
    assert created.status_code == 200
    request_id = created.json()["request_id"]
    assert notifications == [request_id]

    pending = client.get("/api/hitl/pending")
    assert pending.status_code == 200
    assert pending.json()["count"] == 1
    assert pending.json()["pending"][0]["action"] == "deploy"

    approved = client.post(f"/api/hitl/respond/{request_id}", json={"approved": True})
    assert approved.json() == {"request_id": request_id, "decision": "approved"}
    assert client.post("/api/hitl/respond/missing", json={"approved": False}).status_code == 404


def test_hitl_websocket_without_token_sends_snapshot_and_unregisters_client(make_test_client: Any) -> None:
    item = SimpleNamespace(to_dict=lambda: {"request_id": "req-1"})
    clients: set[Any] = set()
    app = FastAPI()
    app.include_router(
        build_hitl_router(
            get_request_user=lambda: None,
            resolve_agent_instance=lambda: _await_if_needed(SimpleNamespace()),
            await_if_needed=_await_if_needed,
            resolve_user_from_token=lambda *_args: None,
            ws_close_policy_violation=lambda *_args: None,
            hitl_ws_clients=clients,
            get_hitl_store=lambda: SimpleNamespace(pending=lambda: [item]),
            get_hitl_gate=lambda: SimpleNamespace(timeout=60.0),
        )
    )

    with make_test_client(app).websocket_connect("/ws/hitl") as websocket:
        assert websocket.receive_json() == {
            "type": "hitl_snapshot",
            "pending": [{"request_id": "req-1"}],
        }
    assert clients == set()
