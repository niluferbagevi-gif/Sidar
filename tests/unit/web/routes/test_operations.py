from __future__ import annotations

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
