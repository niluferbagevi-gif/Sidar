from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

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


class _RaisingMemory:
    db = _RaisingDb()


async def _resolve_agent_instance_with_raising_db():
    return SimpleNamespace(memory=_RaisingMemory())


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


def test_operations_serializers_normalize_optional_campaign_id() -> None:
    payload = operations.serialize_operation_checklist(
        SimpleNamespace(id="5", campaign_id=None, items_json=None)
    )

    assert payload["campaign_id"] is None
    assert payload["items_json"] == "[]"


@pytest.mark.asyncio
async def test_operations_router_returns_controlled_db_error_when_agent_resolution_fails() -> None:
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
