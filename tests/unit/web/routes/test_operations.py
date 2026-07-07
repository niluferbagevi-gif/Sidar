from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from web.routes import operations


class _Db:
    async def list_marketing_campaigns(self, **kwargs):
        assert kwargs == {"tenant_id": "tenant-route", "status": "active", "limit": 3}
        return [SimpleNamespace(id="7", tenant_id="tenant-route", name="Launch", budget="2.5")]


class _Memory:
    db = _Db()


async def _resolve_agent_instance():
    return SimpleNamespace(memory=_Memory())


async def _resolve_agent_instance_raises():
    raise RuntimeError("password authentication failed for user sidar")


class _RaisingDb:
    async def list_marketing_campaigns(self, **_kwargs):
        raise RuntimeError("db unavailable")

    async def upsert_marketing_campaign(self, **_kwargs):
        raise RuntimeError("db unavailable")

    async def list_content_assets(self, **_kwargs):
        raise RuntimeError("db unavailable")

    async def add_content_asset(self, **_kwargs):
        raise RuntimeError("db unavailable")

    async def list_operation_checklists(self, **_kwargs):
        raise RuntimeError("db unavailable")

    async def add_operation_checklist(self, **_kwargs):
        raise RuntimeError("db unavailable")

    async def list_coverage_tasks(self, **_kwargs):
        raise RuntimeError("db unavailable")


class _UnexpectedDb(_RaisingDb):
    async def list_content_assets(self, **_kwargs):
        raise ValueError("unexpected db serialization failure")


class _RaisingMemory:
    db = _RaisingDb()


class _UnexpectedMemory:
    db = _UnexpectedDb()


async def _resolve_agent_instance_with_raising_db():
    return SimpleNamespace(memory=_RaisingMemory())


async def _resolve_agent_instance_with_unexpected_db():
    return SimpleNamespace(memory=_UnexpectedMemory())


def _configure_raising_operations_db() -> None:
    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            resolve_agent_instance=_resolve_agent_instance_with_raising_db,
        )
    )


def _assert_database_unavailable_response(response) -> None:
    assert response.status_code == 503
    payload = json.loads(response.body)
    assert payload == {
        "success": False,
        "error": "database_unavailable",
        "message": "Veritabanı geçici olarak kullanılamıyor.",
    }


@pytest.mark.asyncio
async def test_operations_router_lists_campaigns_with_configured_dependencies() -> None:
    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            resolve_agent_instance=_resolve_agent_instance,
        )
    )

    response = await operations.api_operations_list_campaigns(
        status="active", limit=3, _user=SimpleNamespace(id="u1")
    )

    assert response.status_code == 200
    assert b'"name":"Launch"' in response.body
    assert b'"budget":2.5' in response.body


def test_allowed_poyraz_rest_tools_contract_excludes_direct_publish_tools() -> None:
    assert operations.ALLOWED_POYRAZ_REST_TOOLS == frozenset(
        {
            "build_landing_page",
            "generate_campaign_copy",
            "create_marketing_campaign",
            "store_content_asset",
            "create_operation_checklist",
            "plan_service_operations",
            "ingest_video_insights",
        }
    )
    assert "publish_social" not in operations.ALLOWED_POYRAZ_REST_TOOLS
    assert "publish_instagram_post" not in operations.ALLOWED_POYRAZ_REST_TOOLS
    assert "send_whatsapp_message" not in operations.ALLOWED_POYRAZ_REST_TOOLS


@pytest.mark.asyncio
async def test_get_request_user_proxy_delegates_to_configured_dependencies() -> None:
    request = object()
    user = SimpleNamespace(id="u-proxy")
    calls: list[object] = []

    async def _get_request_user(req: object) -> object:
        calls.append(req)
        return user

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(get_request_user=_get_request_user)
    )

    assert await operations._get_request_user_proxy(request) is user
    assert calls == [request]


def test_operations_serializers_normalize_optional_campaign_id() -> None:
    payload = operations.serialize_operation_checklist(
        SimpleNamespace(id="5", campaign_id=None, items_json=None)
    )

    assert payload["campaign_id"] is None
    assert payload["items_json"] == "[]"


@pytest.mark.asyncio
async def test_operations_router_returns_controlled_db_error_when_agent_resolution_fails(
    caplog,
) -> None:
    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            resolve_agent_instance=_resolve_agent_instance_raises,
        )
    )

    response = await operations.api_operations_list_campaigns(_user=SimpleNamespace(id="u1"))

    assert response.status_code == 503
    payload = json.loads(response.body)
    assert payload == {
        "success": False,
        "error": "database_unavailable",
        "message": "Veritabanı geçici olarak kullanılamıyor.",
    }
    assert "Operations database unavailable" in caplog.text
    assert "password authentication failed" in caplog.text


def test_decode_agent_tool_result_returns_dict_results_directly() -> None:
    raw = {"success": True}

    assert operations.decode_agent_tool_result(raw) is raw


def test_coverage_routes_are_split_to_coverage_ops_module() -> None:
    assert operations.api_qa_coverage_tasks.__module__ == "web.routes.coverage_ops"
    assert operations.api_qa_coverage_analyze.__module__ == "web.routes.coverage_ops"
    assert operations.serialize_coverage_task.__module__ == "web.routes.coverage_ops"


@pytest.mark.asyncio
async def test_poyraz_run_rejects_tools_outside_rest_allowlist() -> None:
    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(get_user_tenant=lambda _user: "tenant-route")
    )
    req = operations.PoyrazToolRunRequest(tool_name="publish_social", payload={})

    with pytest.raises(HTTPException) as exc_info:
        await operations.api_operations_poyraz_run(req, _user=SimpleNamespace(id="u1"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Bu Poyraz aracı REST operasyon köprüsünde desteklenmiyor."


def test_decode_agent_tool_result_wraps_json_non_dict_payloads() -> None:
    assert operations.decode_agent_tool_result('["item"]') == {
        "success": True,
        "output": ["item"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "args", "kwargs"),
    [
        ("api_operations_list_campaigns", (), {"status": "active", "limit": 3}),
        (
            "api_operations_create_campaign",
            (
                operations.CampaignCreateRequest(
                    name="Launch",
                    channel="email",
                    objective="Grow",
                    budget=1.0,
                ),
            ),
            {},
        ),
        ("api_operations_list_assets", (7,), {"limit": 2}),
        (
            "api_operations_add_asset",
            (
                7,
                operations.ContentAssetCreateRequest(
                    asset_type="copy", title="Subject", content="Hello", channel="email"
                ),
            ),
            {},
        ),
        ("api_operations_list_checklists", (7,), {"limit": 2}),
        (
            "api_operations_add_checklist",
            (7, operations.OperationChecklistCreateRequest(title="Prep", items=["one"])),
            {},
        ),
        ("api_qa_coverage_tasks", (), {"status": "pending", "limit": 2}),
    ],
)
async def test_operations_db_routes_return_503_when_database_methods_raise(
    route_name: str, args: tuple, kwargs: dict
) -> None:
    _configure_raising_operations_db()
    route = getattr(operations, route_name)

    response = await route(*args, **kwargs, _user=SimpleNamespace(id="u1"))

    _assert_database_unavailable_response(response)


@pytest.mark.asyncio
async def test_operations_db_routes_log_and_mask_unexpected_database_errors(caplog) -> None:
    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            resolve_agent_instance=_resolve_agent_instance_with_unexpected_db,
        )
    )

    response = await operations.api_operations_list_assets(
        7, limit=2, _user=SimpleNamespace(id="u1")
    )

    _assert_database_unavailable_response(response)
    assert "Unexpected operations route failure during database_operation" in caplog.text
    assert "unexpected db serialization failure" in caplog.text


@pytest.mark.asyncio
async def test_operations_plan_service_includes_owner_and_reports_tool_failure() -> None:
    events: list[dict] = []
    prompts: list[str] = []

    class _Poyraz:
        async def run_task(self, prompt: str) -> str:
            prompts.append(prompt)
            return '{"success": false, "error": "planning failed"}'

    async def _emit(room_id: str, **payload):
        events.append({"room_id": room_id, **payload})

    async def _await_if_needed(value):
        return value

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            emit_control_room_event=_emit,
            await_if_needed=_await_if_needed,
            get_poyraz_agent_instance=lambda: _Poyraz(),
        )
    )
    req = operations.ServiceOperationsPlanRequest(
        service_name="Catering", audience="Teams", room_id="ops:room"
    )

    response = await operations.api_operations_plan_service(req, _user=SimpleNamespace(id="u42"))
    payload = json.loads(response.body)
    tool_payload = json.loads(prompts[0].split("|", 1)[1])

    assert response.status_code == 200
    assert payload == {
        "success": False,
        "result": {"success": False, "error": "planning failed"},
    }
    assert tool_payload["tenant_id"] == "tenant-route"
    assert tool_payload["owner_user_id"] == "u42"
    assert events[-1]["payload"] == {"success": False}
@pytest.mark.asyncio
async def test_poyraz_rest_bridge_runs_allowed_tool_with_tenant_and_owner_payload() -> None:
    events: list[dict] = []
    prompts: list[str] = []

    class _Poyraz:
        async def run_task(self, prompt: str) -> str:
            prompts.append(prompt)
            return '{"success": true, "output": {"campaign_id": 9}}'

    async def _emit(room_id: str, **payload):
        events.append({"room_id": room_id, **payload})

    async def _await_if_needed(value):
        return value

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            emit_control_room_event=_emit,
            await_if_needed=_await_if_needed,
            get_poyraz_agent_instance=lambda: _Poyraz(),
        )
    )
    req = operations.PoyrazToolRunRequest(
        tool_name="create_marketing_campaign",
        payload={"name": "Launch"},
        room_id="ops:bridge",
    )

    response = await operations.api_operations_poyraz_run(req, _user=SimpleNamespace(id="u55"))
    payload = json.loads(response.body)
    tool_name, raw_payload = prompts[0].split("|", 1)
    tool_payload = json.loads(raw_payload)

    assert response.status_code == 200
    assert tool_name == "create_marketing_campaign"
    assert tool_payload == {"name": "Launch", "tenant_id": "tenant-route", "owner_user_id": "u55"}
    assert payload == {
        "success": True,
        "tool": "create_marketing_campaign",
        "result": {"success": True, "output": {"campaign_id": 9}},
    }
    assert events[0] == {
        "room_id": "ops:bridge",
        "kind": "tool_call",
        "source": "poyraz",
        "content": "Poyraz aracı başlatıldı: create_marketing_campaign",
        "payload": {"tool": "create_marketing_campaign"},
    }
    assert events[-1]["payload"] == {"tool": "create_marketing_campaign", "success": True}


@pytest.mark.asyncio
async def test_named_poyraz_request_uses_raw_output_fallback_when_result_has_no_output() -> None:
    prompts: list[str] = []

    class _Poyraz:
        async def run_task(self, prompt: str) -> str:
            prompts.append(prompt)
            return '{"success": true, "html": "<main>Landing</main>"}'

    async def _emit(_room_id: str, **_payload):
        return None

    async def _await_if_needed(value):
        return value

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            emit_control_room_event=_emit,
            await_if_needed=_await_if_needed,
            get_poyraz_agent_instance=lambda: _Poyraz(),
        )
    )
    req = operations.LandingPageDraftRequest(
        brand_name="Sidar",
        offer="AI ops",
        audience="Teams",
        call_to_action="Start",
        room_id="ops:landing",
    )

    response = await operations.api_operations_generate_landing_page(
        req, _user=SimpleNamespace(id="u99")
    )
    payload = json.loads(response.body)
    tool_payload = json.loads(prompts[0].split("|", 1)[1])

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["output"] == '{"success": true, "html": "<main>Landing</main>"}'
    assert payload["result"] == {"success": True, "html": "<main>Landing</main>"}
    assert tool_payload["tenant_id"] == "tenant-route"
    assert "room_id" not in tool_payload


@pytest.mark.asyncio
async def test_operations_create_campaign_masks_unexpected_database_errors(caplog) -> None:
    class _CreateUnexpectedDb(_RaisingDb):
        async def upsert_marketing_campaign(self, **_kwargs):
            raise ValueError("campaign metadata was not serializable")

    async def _resolve_agent_instance_with_create_unexpected_db():
        return SimpleNamespace(memory=SimpleNamespace(db=_CreateUnexpectedDb()))

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            resolve_agent_instance=_resolve_agent_instance_with_create_unexpected_db,
        )
    )

    response = await operations.api_operations_create_campaign(
        operations.CampaignCreateRequest(name="Launch"), _user=SimpleNamespace(id="u1")
    )

    _assert_database_unavailable_response(response)
    assert "Unexpected operations route failure during database_operation" in caplog.text
    assert "campaign metadata was not serializable" in caplog.text
@pytest.mark.asyncio
async def test_operations_create_campaign_serializes_initial_assets_and_checklists() -> None:
    class _CreateDb:
        async def upsert_marketing_campaign(self, **kwargs):
            assert kwargs["tenant_id"] == "tenant-route"
            assert kwargs["owner_user_id"] == "u-create"
            assert kwargs["metadata"] == {"segment": "smb"}
            return SimpleNamespace(id=12, tenant_id="tenant-route", name=kwargs["name"], budget=3)

        async def add_content_asset(self, **kwargs):
            assert kwargs["campaign_id"] == 12
            assert kwargs["metadata"] == {"variant": "a"}
            return SimpleNamespace(id=21, campaign_id=12, title=kwargs["title"], content=kwargs["content"])

        async def add_operation_checklist(self, **kwargs):
            assert kwargs["campaign_id"] == 12
            assert kwargs["items"] == ["book venue"]
            assert kwargs["owner_user_id"] == "u-create"
            return SimpleNamespace(id=31, campaign_id=12, title=kwargs["title"], items_json='["book venue"]')

    async def _resolve_agent_instance_with_create_db():
        return SimpleNamespace(memory=SimpleNamespace(db=_CreateDb()))

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            resolve_agent_instance=_resolve_agent_instance_with_create_db,
        )
    )
    req = operations.CampaignCreateRequest(
        name="Launch",
        channel="email",
        objective="Grow",
        budget=3,
        metadata={"segment": "smb"},
        initial_assets=[
            operations.ContentAssetCreateRequest(
                asset_type="copy",
                title="Subject",
                content="Hello",
                metadata={"variant": "a"},
            )
        ],
        initial_checklists=[
            operations.OperationChecklistCreateRequest(title="Prep", items=["book venue"])
        ],
    )

    response = await operations.api_operations_create_campaign(
        req, _user=SimpleNamespace(id="u-create")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["campaign"]["id"] == 12
    assert payload["assets"] == [
        {
            "id": 21,
            "campaign_id": 12,
            "tenant_id": "default",
            "asset_type": "",
            "title": "Subject",
            "content": "Hello",
            "channel": "",
            "metadata_json": "{}",
            "created_at": "",
            "updated_at": "",
        }
    ]
    assert payload["checklists"][0]["campaign_id"] == 12
    assert payload["checklists"][0]["items_json"] == '["book venue"]'


@pytest.mark.asyncio
async def test_poyraz_rest_bridge_preserves_existing_owner_user_id() -> None:
    prompts: list[str] = []

    class _Poyraz:
        async def run_task(self, prompt: str) -> str:
            prompts.append(prompt)
            return {"success": True}

    async def _emit(_room_id: str, **_payload):
        return None

    async def _await_if_needed(value):
        return value

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            emit_control_room_event=_emit,
            await_if_needed=_await_if_needed,
            get_poyraz_agent_instance=lambda: _Poyraz(),
        )
    )
    req = operations.PoyrazToolRunRequest(
        tool_name="store_content_asset",
        payload={"owner_user_id": "payload-owner"},
    )

    response = await operations.api_operations_poyraz_run(req, _user=SimpleNamespace(id="u-route"))
    tool_payload = json.loads(prompts[0].split("|", 1)[1])

    assert response.status_code == 200
    assert tool_payload["tenant_id"] == "tenant-route"
    assert tool_payload["owner_user_id"] == "payload-owner"



class _ExceptionDb:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def list_marketing_campaigns(self, **_kwargs):
        raise self.exc

    async def upsert_marketing_campaign(self, **_kwargs):
        raise self.exc

    async def list_content_assets(self, **_kwargs):
        raise self.exc

    async def add_content_asset(self, **_kwargs):
        raise self.exc

    async def list_operation_checklists(self, **_kwargs):
        raise self.exc

    async def add_operation_checklist(self, **_kwargs):
        raise self.exc


async def _resolve_agent_instance_with_db(db):
    return SimpleNamespace(memory=SimpleNamespace(db=db))


def _configure_operations_db_exception(exc: Exception) -> None:
    db = _ExceptionDb(exc)

    async def _resolve():
        return await _resolve_agent_instance_with_db(db)

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            resolve_agent_instance=_resolve,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("runtime db down"),
        OSError("socket closed"),
        AttributeError("missing db method"),
        ValueError("unexpected serialization failure"),
    ],
)
@pytest.mark.parametrize(
    ("route_name", "args", "kwargs"),
    [
        ("api_operations_list_campaigns", (), {"status": "active", "limit": 3}),
        ("api_operations_create_campaign", (operations.CampaignCreateRequest(name="Launch"),), {}),
        ("api_operations_list_assets", (7,), {"limit": 2}),
        (
            "api_operations_add_asset",
            (7, operations.ContentAssetCreateRequest(asset_type="copy", title="Subject", content="Hi")),
            {},
        ),
        ("api_operations_list_checklists", (7,), {"limit": 2}),
        (
            "api_operations_add_checklist",
            (7, operations.OperationChecklistCreateRequest(title="Prep", items=["one"])),
            {},
        ),
    ],
)
async def test_operations_db_routes_mask_expected_and_unexpected_exceptions(
    exc: Exception,
    route_name: str,
    args: tuple,
    kwargs: dict,
) -> None:
    _configure_operations_db_exception(exc)

    response = await getattr(operations, route_name)(*args, **kwargs, _user=SimpleNamespace(id="u1"))

    _assert_database_unavailable_response(response)


def _assert_poyraz_unavailable_response(response) -> None:
    assert response.status_code == 503
    assert json.loads(response.body) == {
        "success": False,
        "error": "poyraz_unavailable",
        "message": "Poyraz operasyon aracı geçici olarak kullanılamıyor.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("poyraz runtime down"),
        OSError("poyraz socket closed"),
        AttributeError("poyraz missing method"),
        ValueError("unexpected poyraz failure"),
    ],
)
async def test_poyraz_tool_bridge_returns_api_response_for_tool_exceptions(exc: Exception) -> None:
    class _Poyraz:
        async def run_task(self, _prompt: str) -> str:
            raise exc

    async def _emit(_room_id: str, **_payload):
        return None

    async def _await_if_needed(value):
        return value

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            emit_control_room_event=_emit,
            await_if_needed=_await_if_needed,
            get_poyraz_agent_instance=lambda: _Poyraz(),
        )
    )
    req = operations.PoyrazToolRunRequest(tool_name="store_content_asset", payload={})

    response = await operations.api_operations_poyraz_run(req, _user=SimpleNamespace(id="u1"))

    _assert_poyraz_unavailable_response(response)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("named runtime down"),
        OSError("named socket closed"),
        AttributeError("named missing method"),
        ValueError("unexpected named failure"),
    ],
)
async def test_named_poyraz_bridge_returns_api_response_for_tool_exceptions(exc: Exception) -> None:
    class _Poyraz:
        async def run_task(self, _prompt: str) -> str:
            raise exc

    async def _emit(_room_id: str, **_payload):
        return None

    async def _await_if_needed(value):
        return value

    operations.configure_operations_dependencies(
        lambda: SimpleNamespace(
            get_user_tenant=lambda _user: "tenant-route",
            emit_control_room_event=_emit,
            await_if_needed=_await_if_needed,
            get_poyraz_agent_instance=lambda: _Poyraz(),
        )
    )
    req = operations.LandingPageDraftRequest(
        brand_name="Sidar", offer="AI ops", audience="Teams", call_to_action="Start"
    )

    response = await operations.api_operations_generate_landing_page(
        req, _user=SimpleNamespace(id="u1")
    )

    _assert_poyraz_unavailable_response(response)
