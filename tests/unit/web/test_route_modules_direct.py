from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes.agent import build_agent_router
from web.routes.auth_admin import build_auth_admin_router
from web.routes.hitl import build_hitl_router
from web.routes.metrics import build_metrics_router
from web.routes.orchestration import build_orchestration_router
from web.routes.project_ops import build_project_ops_router
from web.routes.rag import build_rag_router


def _admin_user() -> dict[str, Any]:
    return {"id": "u1", "username": "admin", "role": "admin"}


async def _async_value(value: Any) -> Any:
    return value


@dataclass
class _AgentRegisterReq:
    role_name: str
    source_code: str
    class_name: str | None = None
    capabilities: list[str] | None = None
    description: str = ""
    version: str = "1.0.0"


@dataclass
class _PluginInstallReq:
    plugin_id: str


def test_agent_router_catalog_endpoint_direct() -> None:
    router = build_agent_router(
        require_admin_user=_admin_user,
        register_plugin_agent=lambda **_: {"ok": True},
        persist_and_import_plugin_file=lambda *_: None,
        max_file_content_bytes=1024,
        read_plugin_marketplace_state=lambda: {},
        serialize_marketplace_plugin=lambda plugin_id, installed_state=None: {"id": plugin_id},
        plugin_marketplace_catalog={"p1": {}},
        install_marketplace_plugin=lambda plugin_id: {"success": True, "plugin_id": plugin_id},
        uninstall_marketplace_plugin=lambda plugin_id: {"success": True, "plugin_id": plugin_id},
        agent_plugin_register_request_model=_AgentRegisterReq,
        plugin_marketplace_install_request_model=_PluginInstallReq,
    )
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).get("/api/plugin-marketplace/catalog")
    assert res.status_code == 200
    assert res.json()["items"][0]["id"] == "p1"


@dataclass
class _RegisterReq:
    username: str
    password: str
    tenant_id: str = "default"


@dataclass
class _LoginReq:
    username: str
    password: str


@dataclass
class _PromptReq:
    role_name: str
    prompt_text: str
    activate: bool = False


@dataclass
class _PromptActivateReq:
    prompt_id: str


@dataclass
class _PolicyReq:
    user_id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    action: str
    effect: str


def test_auth_admin_router_register_direct() -> None:
    db = SimpleNamespace(
        register_user=lambda **_: SimpleNamespace(id="1", username="alice", role="user"),
        authenticate_user=lambda **_: None,
        get_admin_stats=lambda: {"ok": True},
        list_prompts=lambda **_: [],
        get_active_prompt=lambda *_: None,
        upsert_prompt=lambda **_: None,
        activate_prompt=lambda *_: None,
        list_access_policies=lambda **_: [],
        upsert_access_policy=lambda **_: None,
    )
    agent = SimpleNamespace(memory=SimpleNamespace(db=db), system_prompt="")
    router = build_auth_admin_router(
        resolve_agent_instance=lambda: _async_value(agent),
        await_if_needed=lambda x: x,
        get_request_user=_admin_user,
        require_admin_user=_admin_user,
        issue_auth_token=lambda *_: _async_value("tkn"),
        serialize_prompt=lambda p: {},
        serialize_policy=lambda p: {},
        register_request_model=_RegisterReq,
        login_request_model=_LoginReq,
        prompt_upsert_request_model=_PromptReq,
        prompt_activate_request_model=_PromptActivateReq,
        policy_upsert_request_model=_PolicyReq,
    )
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).post("/auth/register", json={"username": "alice", "password": "123456"})
    assert res.status_code == 200
    assert res.json()["access_token"] == "tkn"


def test_hitl_router_pending_direct() -> None:
    store = SimpleNamespace(pending=lambda: _async_value([]))
    router = build_hitl_router(
        get_request_user=_admin_user,
        resolve_agent_instance=lambda: _async_value(SimpleNamespace()),
        await_if_needed=lambda x: x,
        resolve_user_from_token=lambda *_: _async_value(_admin_user()),
        ws_close_policy_violation=lambda *_: None,
        hitl_ws_clients=set(),
        get_hitl_store=lambda: store,
        get_hitl_gate=lambda: SimpleNamespace(
            timeout=10, respond=lambda *_args, **_kwargs: _async_value(None)
        ),
    )
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).get("/api/hitl/pending")
    assert res.status_code == 200
    assert res.json()["count"] == 0


def test_metrics_router_json_direct() -> None:
    class _Memory:
        def get_all_sessions(self):
            return []

        def __len__(self):
            return 0

    agent = SimpleNamespace(
        VERSION="x",
        docs=SimpleNamespace(doc_count=0),
        memory=_Memory(),
        cfg=SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False),
    )
    router = build_metrics_router(
        require_metrics_access=lambda: {"ok": True},
        resolve_agent_instance=lambda: _async_value(agent),
        start_time=0.0,
        local_rate_limits={},
        get_llm_metrics_collector=lambda: SimpleNamespace(snapshot=lambda: {"totals": {"calls": 0, "total_tokens": 0}}),
        render_llm_metrics_prometheus=lambda _: "",
        set_current_metrics_user_id=lambda *_: None,
        reset_current_metrics_user_id=lambda *_: None,
        logger=SimpleNamespace(debug=lambda *_: None),
    )
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).get("/metrics")
    assert res.status_code == 200
    assert res.json()["version"] == "x"


def test_orchestration_router_clear_direct() -> None:
    agent = SimpleNamespace(memory=SimpleNamespace(clear=lambda: None))
    router = build_orchestration_router(
        require_admin_user=_admin_user,
        get_request_user=_admin_user,
        resolve_agent_instance=lambda: _async_value(agent),
        await_if_needed=lambda x: _async_value(None if callable(x) else x),
        cfg=SimpleNamespace(),
        swarm_orchestrator_cls=lambda *_: None,
        swarm_task_cls=SimpleNamespace,
        swarm_request_model=SimpleNamespace,
        serialize_swarm_result=lambda x: x,
    )
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).post("/clear")
    assert res.status_code == 200
    assert res.json()["result"] is True


def test_project_ops_router_git_info_direct(tmp_path) -> None:
    agent = SimpleNamespace(memory=SimpleNamespace(db=None))
    router = build_project_ops_router(
        get_request_user=_admin_user,
        resolve_agent_instance=lambda: _async_value(agent),
        max_file_content_bytes=1024,
        server_root=tmp_path,
        cfg=SimpleNamespace(GITHUB_REPO=""),
        logger=SimpleNamespace(warning=lambda *_: None),
    )
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).get("/git-info")
    assert res.status_code == 200
    assert "branch" in res.json()


def test_rag_router_search_direct() -> None:
    docs = SimpleNamespace(search=lambda *_: (True, [{"id": "d1"}]))
    agent = SimpleNamespace(memory=SimpleNamespace(active_session_id="s1"), docs=docs)
    router = build_rag_router(
        resolve_agent_instance=lambda: _async_value(agent),
        await_if_needed=lambda x: x,
        max_rag_upload_bytes=1024,
        server_root=Path("."),
        logger=SimpleNamespace(debug=lambda *_: None),
    )
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).get("/rag/search?q=test")
    assert res.status_code == 200
    assert res.json()["success"] is True
