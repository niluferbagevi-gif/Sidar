from __future__ import annotations

import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI

from web.routes.agent import build_agent_router
from web.routes.auth_admin import build_auth_admin_router
from web.routes.hitl import build_hitl_router
from web.routes.metrics import build_metrics_router
from web.routes.orchestration import _parse_payload, build_orchestration_router
from web.routes.project_ops import build_project_ops_router
from web.routes.rag import build_rag_router


def _admin_user() -> dict[str, Any]:
    return {"id": "u1", "username": "admin", "role": "admin"}


async def _async_value(value: Any) -> Any:
    return value


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
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


def test_agent_router_catalog_endpoint_direct(make_test_client) -> None:
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
    res = make_test_client(app).get("/api/plugin-marketplace/catalog")
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


def test_auth_admin_router_register_direct(make_test_client) -> None:
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
        await_if_needed=_await_if_needed,
        get_request_user=_admin_user,
        require_admin_user=_admin_user,
        issue_auth_token=lambda *_: _async_value("tkn"),
        serialize_prompt=lambda p: {},
        serialize_policy=lambda p: {},
        serialize_audit_log=lambda audit_log: {"id": audit_log.id},
        register_request_model=_RegisterReq,
        login_request_model=_LoginReq,
        prompt_upsert_request_model=_PromptReq,
        prompt_activate_request_model=_PromptActivateReq,
        policy_upsert_request_model=_PolicyReq,
    )
    app = FastAPI()
    app.include_router(router)
    res = make_test_client(app).post(
        "/auth/register", json={"username": "alice", "password": "123456"}
    )
    assert res.status_code == 200
    assert res.json()["access_token"] == "tkn"


def test_auth_admin_router_json_posts_read_request_body_direct(make_test_client) -> None:
    prompt = SimpleNamespace(id="p1", role_name="system", prompt_text="hello", is_active=1)
    policy = SimpleNamespace(id="a1", user_id="u1", tenant_id="default")

    async def _upsert_prompt(**_: Any) -> Any:
        return prompt

    async def _activate_prompt(_: str) -> Any:
        return prompt

    async def _upsert_access_policy(**_: Any) -> None:
        return None

    async def _list_access_policies(**_: Any) -> list[Any]:
        return [policy]

    async def _list_audit_logs(**kwargs: Any) -> list[Any]:
        assert kwargs == {"user_id": "u1", "tenant_id": "tenant-a", "limit": 5}
        return [SimpleNamespace(id="audit-1")]

    db = SimpleNamespace(
        upsert_prompt=_upsert_prompt,
        activate_prompt=_activate_prompt,
        upsert_access_policy=_upsert_access_policy,
        list_access_policies=_list_access_policies,
        list_audit_logs=_list_audit_logs,
    )
    agent = SimpleNamespace(memory=SimpleNamespace(db=db), system_prompt="")
    router = build_auth_admin_router(
        resolve_agent_instance=lambda: _async_value(agent),
        await_if_needed=_await_if_needed,
        get_request_user=_admin_user,
        require_admin_user=_admin_user,
        issue_auth_token=lambda *_: _async_value("tkn"),
        serialize_prompt=lambda item: {"id": item.id, "prompt_text": item.prompt_text},
        serialize_policy=lambda item: {"id": item.id, "user_id": item.user_id},
        serialize_audit_log=lambda audit_log: {"id": audit_log.id},
        register_request_model=_RegisterReq,
        login_request_model=_LoginReq,
        prompt_upsert_request_model=_PromptReq,
        prompt_activate_request_model=_PromptActivateReq,
        policy_upsert_request_model=_PolicyReq,
    )
    app = FastAPI()
    app.include_router(router)
    client = make_test_client(app)

    upsert_prompt = client.post(
        "/admin/prompts", json={"role_name": "system", "prompt_text": "hello"}
    )
    activate_prompt = client.post("/admin/prompts/activate", json={"prompt_id": "p1"})
    audit_logs = client.get("/admin/audit-logs?user_id=u1&tenant_id=tenant-a&limit=5")
    upsert_policy = client.post(
        "/admin/policies",
        json={
            "user_id": "u1",
            "tenant_id": "default",
            "resource_type": "project",
            "resource_id": "*",
            "action": "read",
            "effect": "allow",
        },
    )

    assert upsert_prompt.status_code == 200
    assert upsert_prompt.json() == {"id": "p1", "prompt_text": "hello"}
    assert activate_prompt.status_code == 200
    assert activate_prompt.json() == {"id": "p1", "prompt_text": "hello"}
    assert audit_logs.status_code == 200
    assert audit_logs.json() == {"items": [{"id": "audit-1"}]}
    assert upsert_policy.status_code == 200
    assert upsert_policy.json() == {"success": True, "items": [{"id": "a1", "user_id": "u1"}]}


@pytest.mark.asyncio
async def test_hitl_router_pending_direct() -> None:
    store = SimpleNamespace(pending=lambda: _async_value([]))
    router = build_hitl_router(
        get_request_user=_admin_user,
        resolve_agent_instance=lambda: _async_value(SimpleNamespace()),
        await_if_needed=_await_if_needed,
        resolve_user_from_token=lambda *_: _async_value(_admin_user()),
        ws_close_policy_violation=lambda *_: None,
        hitl_ws_clients=set(),
        get_hitl_store=lambda: store,
        get_hitl_gate=lambda: SimpleNamespace(
            timeout=10, respond=lambda *_args, **_kwargs: _async_value(None)
        ),
    )

    res = await router.legacy_exports["hitl_pending"](user=_admin_user())

    assert res.status_code == 200
    assert json.loads(res.body)["count"] == 0


def test_metrics_router_json_direct(make_test_client) -> None:
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
        get_llm_metrics_collector=lambda: SimpleNamespace(
            snapshot=lambda: {"totals": {"calls": 0, "total_tokens": 0}}
        ),
        render_llm_metrics_prometheus=lambda _: "",
        set_current_metrics_user_id=lambda *_: None,
        reset_current_metrics_user_id=lambda *_: None,
        logger=SimpleNamespace(debug=lambda *_: None),
    )
    app = FastAPI()
    app.include_router(router)
    res = make_test_client(app).get("/metrics")
    assert res.status_code == 200
    assert res.json()["version"] == "x"


def test_orchestration_parse_payload_supports_constructor_and_passthrough() -> None:
    class _Payload:
        def __init__(self, **kwargs):
            self.value = kwargs["value"]

    payload = _parse_payload(_Payload, {"value": "ok"})

    assert payload.value == "ok"
    marker = object()
    assert _parse_payload(_Payload, marker) is marker


def test_orchestration_router_requires_request_model() -> None:
    with pytest.raises(ValueError, match="swarm_execute_request_model"):
        build_orchestration_router(
            require_admin_user=_admin_user,
            get_request_user=_admin_user,
            resolve_agent_instance=lambda: _async_value(None),
            await_if_needed=_await_if_needed,
            cfg=SimpleNamespace(),
            swarm_orchestrator_cls=SimpleNamespace,
            swarm_task_cls=SimpleNamespace,
        )


def test_orchestration_router_clear_direct(make_test_client) -> None:
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
    res = make_test_client(app).post("/clear")
    assert res.status_code == 200
    assert res.json()["result"] is True


def test_project_ops_router_git_info_direct(tmp_path, make_test_client) -> None:
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
    res = make_test_client(app).get("/git-info")
    assert res.status_code == 200
    assert "branch" in res.json()


def test_rag_router_search_direct(make_test_client) -> None:
    docs = SimpleNamespace(search=lambda *_: (True, [{"id": "d1"}]))
    agent = SimpleNamespace(memory=SimpleNamespace(active_session_id="s1"), docs=docs)
    router = build_rag_router(
        resolve_agent_instance=lambda: _async_value(agent),
        await_if_needed=_await_if_needed,
        max_rag_upload_bytes=1024,
        server_root=Path("."),
        logger=SimpleNamespace(debug=lambda *_: None),
    )
    app = FastAPI()
    app.include_router(router)
    res = make_test_client(app).get("/rag/search?q=test")
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_agent_parse_payload_supports_modern_and_passthrough_models() -> None:
    from web.routes.agent import _parse_payload

    class _Modern:
        @classmethod
        def model_validate(cls, payload: Any) -> tuple[str, Any]:
            return ("validated", payload)

    marker = object()
    assert _parse_payload(_Modern, {"x": 1}) == ("validated", {"x": 1})
    assert _parse_payload(_AgentRegisterReq, marker) is marker


def test_agent_router_json_posts_and_file_upload_direct(
    monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    def _unexpected_web_server_helper(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Agent router must use its injected dependencies")

    web_server_mod = ModuleType("web_server")
    web_server_mod._register_plugin_agent = _unexpected_web_server_helper
    web_server_mod._persist_and_import_plugin_file = _unexpected_web_server_helper
    web_server_mod._install_marketplace_plugin = _unexpected_web_server_helper
    web_server_mod._uninstall_marketplace_plugin = _unexpected_web_server_helper
    monkeypatch.setitem(sys.modules, "web_server", web_server_mod)

    registered: list[dict[str, Any]] = []
    persisted: list[tuple[str, bytes, str]] = []
    installed: list[str] = []

    def _register(**kwargs: Any) -> dict[str, Any]:
        registered.append(kwargs)
        return {"role_name": kwargs["role_name"]}

    def _persist(filename: str, data: bytes, module_label: str) -> None:
        persisted.append((filename, data, module_label))

    def _install(plugin_id: str) -> dict[str, Any]:
        installed.append(plugin_id)
        return {"success": True, "plugin_id": plugin_id}

    router = build_agent_router(
        require_admin_user=_admin_user,
        register_plugin_agent=_register,
        persist_and_import_plugin_file=_persist,
        max_file_content_bytes=lambda: 128,
        read_plugin_marketplace_state=lambda: {"p1": {"enabled": True}},
        serialize_marketplace_plugin=lambda plugin_id, installed_state=None: {
            "enabled": bool(installed_state)
        },
        plugin_marketplace_catalog=lambda: {"p1": {}},
        install_marketplace_plugin=_install,
        uninstall_marketplace_plugin=lambda plugin_id: {"removed": plugin_id},
        agent_plugin_register_request_model=_AgentRegisterReq,
        plugin_marketplace_install_request_model=_PluginInstallReq,
    )
    app = FastAPI()
    app.include_router(router)
    client = make_test_client(app)

    response = client.post(
        "/api/agents/register",
        json={"role_name": "demo", "source_code": "class Demo: pass", "capabilities": ["qa"]},
    )
    assert response.status_code == 200
    assert response.json()["agent"]["role_name"] == "demo"

    upload = client.post(
        "/api/agents/register-file?capabilities=qa%2C%20review&description=uploaded",
        files={"file": ("uploaded.py", b"class Uploaded: pass\n", "text/x-python")},
    )
    assert upload.status_code == 200
    assert upload.json()["agent"]["role_name"] == "uploaded"
    assert persisted[0][0:2] == ("uploaded.py", b"class Uploaded: pass\n")
    assert registered[-1]["capabilities"] == ["qa", "review"]

    assert client.get("/api/plugin-marketplace/catalog").json() == {
        "items": [{"enabled": True, "id": "p1"}]
    }
    assert (
        client.post("/api/plugin-marketplace/install", json={"plugin_id": "p1"}).status_code == 200
    )
    assert (
        client.post("/api/plugin-marketplace/reload", json={"plugin_id": "p1"}).status_code == 200
    )
    assert installed == ["p1", "p1"]
    assert client.delete("/api/plugin-marketplace/install/p1").json() == {"removed": "p1"}


def test_agent_router_file_upload_validation_direct(make_test_client) -> None:
    router = build_agent_router(
        require_admin_user=_admin_user,
        register_plugin_agent=lambda **_: {},
        persist_and_import_plugin_file=lambda *_: None,
        max_file_content_bytes=3,
        read_plugin_marketplace_state=lambda: {},
        serialize_marketplace_plugin=lambda *_args, **_kwargs: {},
        plugin_marketplace_catalog={},
        install_marketplace_plugin=lambda _plugin_id: {},
        uninstall_marketplace_plugin=lambda _plugin_id: {},
        agent_plugin_register_request_model=_AgentRegisterReq,
        plugin_marketplace_install_request_model=_PluginInstallReq,
    )
    app = FastAPI()
    app.include_router(router)
    client = make_test_client(app)

    empty = client.post("/api/agents/register-file", files={"file": ("empty.py", b"")})
    assert empty.status_code == 400
    assert empty.json()["detail"] == "Yüklü dosya boş"

    large = client.post("/api/agents/register-file", files={"file": ("large.py", b"abcd")})
    assert large.status_code == 413
    assert large.json()["detail"] == "Dosya çok büyük"

    invalid_utf8 = client.post("/api/agents/register-file", files={"file": ("bad.py", b"\xff")})
    assert invalid_utf8.status_code == 400
    assert invalid_utf8.json()["detail"] == "Plugin dosyası UTF-8 olmalıdır"


def test_metrics_router_prometheus_llm_and_context_restore_direct(
    monkeypatch: pytest.MonkeyPatch,
    make_test_client,
) -> None:
    monkeypatch.delitem(sys.modules, "web_server", raising=False)

    prometheus_mod = ModuleType("prometheus_client")

    class _Registry:
        def __init__(self) -> None:
            self.values: dict[str, float] = {}

    class _Gauge:
        def __init__(self, name: str, _description: str, *, registry: _Registry) -> None:
            self.name = name
            self.registry = registry

        def set(self, value: float) -> None:
            self.registry.values[self.name] = value

    prometheus_api = cast(Any, prometheus_mod)
    prometheus_api.CONTENT_TYPE_LATEST = "text/plain"
    prometheus_api.CollectorRegistry = _Registry
    prometheus_api.Gauge = _Gauge
    prometheus_api.generate_latest = lambda registry: "\n".join(
        f"{name} {value}" for name, value in registry.values.items()
    ).encode()
    monkeypatch.setitem(sys.modules, "prometheus_client", prometheus_mod)
    reset_tokens: list[str] = []

    class _Memory:
        active_user_id = "previous-user"
        active_username = "previous-name"

        async def count_sessions_any_user(self) -> int:
            return 4

        async def aget_all_sessions(self) -> list[str]:
            return ["session"]

        def __len__(self) -> int:
            return 2

    memory = _Memory()
    collector = SimpleNamespace(snapshot=lambda: {"totals": {"calls": 3, "total_tokens": 9}})
    health = SimpleNamespace(
        get_gpu_info=lambda: {
            "available": True,
            "devices": [
                {
                    "id": 0,
                    "name": "RTX 4090",
                    "utilization_pct": 97,
                    "temperature_c": 68,
                    "mem_utilization_pct": 80,
                    "total_vram_gb": 24.0,
                    "allocated_gb": 19.2,
                }
            ],
        },
        check_ollama=lambda: True,
    )
    agent = SimpleNamespace(
        VERSION="test",
        docs=SimpleNamespace(doc_count=5),
        memory=memory,
        cfg=SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=True),
        health=health,
    )
    router = build_metrics_router(
        require_metrics_access=lambda: {"id": "metrics-user"},
        resolve_agent_instance=lambda: _async_value(agent),
        start_time=0.0,
        local_rate_limits=lambda: {"metrics-user": [1.0, 2.0]},
        get_llm_metrics_collector=lambda: collector,
        render_llm_metrics_prometheus=lambda snapshot: f"calls {snapshot['totals']['calls']}\n",
        set_current_metrics_user_id=lambda user_id: f"token:{user_id}",
        reset_current_metrics_user_id=reset_tokens.append,
        logger=SimpleNamespace(debug=lambda *_: None),
    )
    app = FastAPI()
    app.include_router(router)
    client = make_test_client(app)

    prometheus_response = client.get("/metrics", headers={"Accept": "text/plain"})
    assert prometheus_response.status_code == 200
    assert "sidar_sessions_total 4" in prometheus_response.text
    assert "sidar_gpu_available 1" in prometheus_response.text
    assert "sidar_ollama_online 1" in prometheus_response.text
    assert "sidar_gpu_utilization_percent 97" in prometheus_response.text
    assert "sidar_gpu_temperature_celsius 68" in prometheus_response.text
    assert "sidar_gpu_memory_utilization_percent 80" in prometheus_response.text
    assert "sidar_gpu_vram_total_gb 24.0" in prometheus_response.text
    assert "sidar_gpu_vram_allocated_gb 19.2" in prometheus_response.text
    assert memory.active_user_id == "previous-user"
    assert memory.active_username == "previous-name"
    assert reset_tokens == ["token:metrics-user"]

    assert client.get("/metrics/llm/prometheus").text == "calls 3\n"
    assert client.get("/metrics/llm").json()["totals"]["total_tokens"] == 9
    assert client.get("/api/budget").json()["totals"]["calls"] == 3


def test_metrics_router_prometheus_reports_no_gpu_without_health_attribute(
    monkeypatch: pytest.MonkeyPatch,
    make_test_client,
) -> None:
    """A CPU-only agent (or a test double without a `health` attribute at all)
    must still render valid Prometheus output, with gpu_available/ollama_online
    at 0 and no device-specific gauges emitted."""
    monkeypatch.delitem(sys.modules, "web_server", raising=False)

    prometheus_mod = ModuleType("prometheus_client")

    class _Registry:
        def __init__(self) -> None:
            self.values: dict[str, float] = {}

    class _Gauge:
        def __init__(self, name: str, _description: str, *, registry: _Registry) -> None:
            self.name = name
            self.registry = registry

        def set(self, value: float) -> None:
            self.registry.values[self.name] = value

    prometheus_api = cast(Any, prometheus_mod)
    prometheus_api.CONTENT_TYPE_LATEST = "text/plain"
    prometheus_api.CollectorRegistry = _Registry
    prometheus_api.Gauge = _Gauge
    prometheus_api.generate_latest = lambda registry: "\n".join(
        f"{name} {value}" for name, value in registry.values.items()
    ).encode()
    monkeypatch.setitem(sys.modules, "prometheus_client", prometheus_mod)

    class _Memory:
        active_user_id = None
        active_username = None

        def get_all_sessions(self) -> list[str]:
            return []

        def __len__(self) -> int:
            return 0

    agent = SimpleNamespace(
        VERSION="test",
        docs=SimpleNamespace(doc_count=0),
        memory=_Memory(),
        cfg=SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False),
    )
    router = build_metrics_router(
        require_metrics_access=lambda: {"id": "metrics-user"},
        resolve_agent_instance=lambda: _async_value(agent),
        start_time=0.0,
        local_rate_limits=lambda: {},
        get_llm_metrics_collector=lambda: SimpleNamespace(
            snapshot=lambda: {"totals": {"calls": 0, "total_tokens": 0}}
        ),
        render_llm_metrics_prometheus=lambda _snapshot: "",
        set_current_metrics_user_id=lambda user_id: f"token:{user_id}",
        reset_current_metrics_user_id=lambda _token: None,
        logger=SimpleNamespace(debug=lambda *_: None),
    )
    app = FastAPI()
    app.include_router(router)
    client = make_test_client(app)

    response = client.get("/metrics", headers={"Accept": "text/plain"})
    assert response.status_code == 200
    assert "sidar_gpu_available 0" in response.text
    assert "sidar_ollama_online 0" in response.text
    assert "sidar_gpu_utilization_percent" not in response.text
    assert "sidar_gpu_temperature_celsius" not in response.text


def test_metrics_router_plain_text_falls_back_to_json_without_prometheus(
    monkeypatch: pytest.MonkeyPatch,
    make_test_client,
) -> None:
    monkeypatch.delitem(sys.modules, "web_server", raising=False)
    monkeypatch.setitem(sys.modules, "prometheus_client", None)

    class _Memory:
        def get_all_sessions(self) -> list[str]:
            return []

        def __len__(self) -> int:
            return 0

    agent = SimpleNamespace(
        VERSION="fallback",
        docs=SimpleNamespace(doc_count=0),
        memory=_Memory(),
        cfg=SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False),
    )
    router = build_metrics_router(
        require_metrics_access=lambda: {},
        resolve_agent_instance=lambda: _async_value(agent),
        start_time=0.0,
        local_rate_limits={},
        get_llm_metrics_collector=lambda: SimpleNamespace(snapshot=lambda: {"totals": {}}),
        render_llm_metrics_prometheus=lambda _snapshot: "",
        set_current_metrics_user_id=lambda _user_id: "token",
        reset_current_metrics_user_id=lambda _token: None,
        logger=SimpleNamespace(debug=lambda *_: None),
    )
    app = FastAPI()
    app.include_router(router)
    response = make_test_client(app).get("/metrics", headers={"Accept": "text/plain"})
    assert response.status_code == 200
    assert response.json()["version"] == "fallback"


def test_frontend_static_router_injects_config_without_head_tag(
    tmp_path: Path, make_test_client
) -> None:
    from web.routes.static import build_frontend_router

    (tmp_path / "index.html").write_text("<body>SPA</body>", encoding="utf-8")
    router = build_frontend_router(web_dir=lambda: tmp_path, grafana_url=lambda: "http://grafana")
    app = FastAPI()
    app.include_router(router)

    res = make_test_client(app).get("/")

    assert res.status_code == 200
    assert res.text.startswith("<script>window.__SIDAR_CONFIG__")
    assert "http://grafana" in res.text
    assert "<body>SPA</body>" in res.text


def test_frontend_static_router_legacy_exports_cover_asset_paths(tmp_path: Path) -> None:
    from web.routes.static import build_frontend_router

    router = build_frontend_router(web_dir=lambda: tmp_path, grafana_url=lambda: "http://grafana")

    assert {"favicon", "serve_vendor", "index"}.issubset(router.legacy_exports)


def test_configure_loopback_cors_adds_middleware() -> None:
    from web.middleware.cors import LOOPBACK_ORIGIN_REGEX, configure_loopback_cors

    app = FastAPI()
    configure_loopback_cors(app)

    assert app.user_middleware
    options = app.user_middleware[0].kwargs
    assert options["allow_origin_regex"] == LOOPBACK_ORIGIN_REGEX
    assert options["allow_methods"] == ["GET", "POST", "DELETE"]
