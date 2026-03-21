import asyncio
import types

from tests.test_web_server_runtime import _load_web_server


def test_operations_campaign_api_roundtrip():
    mod = _load_web_server()
    calls = {}

    class _Db:
        async def upsert_marketing_campaign(self, **kwargs):
            calls["campaign"] = kwargs
            return types.SimpleNamespace(
                id=11,
                tenant_id=kwargs["tenant_id"],
                name=kwargs["name"],
                channel=kwargs["channel"],
                objective=kwargs["objective"],
                status=kwargs["status"],
                owner_user_id=kwargs["owner_user_id"],
                budget=kwargs["budget"],
                metadata_json='{"region":"TR"}',
                created_at="2026-03-21T00:00:00+00:00",
                updated_at="2026-03-21T00:00:00+00:00",
            )

        async def add_content_asset(self, **kwargs):
            calls.setdefault("assets", []).append(kwargs)
            return types.SimpleNamespace(
                id=21,
                campaign_id=kwargs["campaign_id"],
                tenant_id=kwargs["tenant_id"],
                asset_type=kwargs["asset_type"],
                title=kwargs["title"],
                content=kwargs["content"],
                channel=kwargs["channel"],
                metadata_json="{}",
                created_at="2026-03-21T00:00:00+00:00",
                updated_at="2026-03-21T00:00:00+00:00",
            )

        async def add_operation_checklist(self, **kwargs):
            calls.setdefault("checklists", []).append(kwargs)
            return types.SimpleNamespace(
                id=31,
                campaign_id=kwargs["campaign_id"],
                tenant_id=kwargs["tenant_id"],
                title=kwargs["title"],
                items_json='["UTM"]',
                status=kwargs["status"],
                owner_user_id=kwargs["owner_user_id"],
                created_at="2026-03-21T00:00:00+00:00",
                updated_at="2026-03-21T00:00:00+00:00",
            )

        async def list_marketing_campaigns(self, **kwargs):
            calls["list_campaigns"] = kwargs
            return [
                types.SimpleNamespace(
                    id=11,
                    tenant_id=kwargs["tenant_id"],
                    name="Bahar Kampanyası",
                    channel="instagram",
                    objective="lead",
                    status="draft",
                    owner_user_id="u-1",
                    budget=1200.0,
                    metadata_json="{}",
                    created_at="2026-03-21T00:00:00+00:00",
                    updated_at="2026-03-21T00:00:00+00:00",
                )
            ]

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_Db()))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    user = types.SimpleNamespace(id="u-1", username="alice", role="user", tenant_id="tenant-a")

    payload = mod._CampaignCreateRequest(
        name="Bahar Kampanyası",
        channel="instagram",
        objective="lead",
        status="draft",
        budget=1200.0,
        metadata={"region": "TR"},
        initial_assets=[
            mod._ContentAssetCreateRequest(
                asset_type="landing_page",
                title="LP",
                content="<section>demo</section>",
                channel="web",
                metadata={},
            )
        ],
        initial_checklists=[
            mod._OperationChecklistCreateRequest(title="Kontrol", items=["UTM"], status="pending")
        ],
    )

    created = asyncio.run(mod.api_operations_create_campaign(payload, _user=user))
    listed = asyncio.run(mod.api_operations_list_campaigns(status="draft", limit=5, _user=user))

    assert created.content["success"] is True
    assert created.content["campaign"]["id"] == 11
    assert created.content["assets"][0]["asset_type"] == "landing_page"
    assert created.content["checklists"][0]["title"] == "Kontrol"
    assert calls["campaign"]["tenant_id"] == "tenant-a"
    assert calls["list_campaigns"] == {"tenant_id": "tenant-a", "status": "draft", "limit": 5}
    assert listed.content["campaigns"][0]["name"] == "Bahar Kampanyası"


def test_operations_asset_and_checklist_listing_endpoints():
    mod = _load_web_server()

    class _Db:
        async def list_content_assets(self, **kwargs):
            return [
                types.SimpleNamespace(
                    id=1,
                    campaign_id=kwargs["campaign_id"],
                    tenant_id=kwargs["tenant_id"],
                    asset_type="campaign_copy",
                    title="Copy",
                    content="Metin",
                    channel="instagram",
                    metadata_json="{}",
                    created_at="2026-03-21T00:00:00+00:00",
                    updated_at="2026-03-21T00:00:00+00:00",
                )
            ]

        async def list_operation_checklists(self, **kwargs):
            return [
                types.SimpleNamespace(
                    id=2,
                    campaign_id=kwargs["campaign_id"],
                    tenant_id=kwargs["tenant_id"],
                    title="Yayın",
                    items_json='["Check"]',
                    status="pending",
                    owner_user_id="u-1",
                    created_at="2026-03-21T00:00:00+00:00",
                    updated_at="2026-03-21T00:00:00+00:00",
                )
            ]

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_Db()))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    user = types.SimpleNamespace(id="u-1", username="alice", role="user", tenant_id="tenant-a")

    assets_resp = asyncio.run(mod.api_operations_list_assets(campaign_id=7, limit=10, _user=user))
    checklists_resp = asyncio.run(mod.api_operations_list_checklists(campaign_id=7, limit=10, _user=user))

    assert assets_resp.content["assets"][0]["campaign_id"] == 7
    assert checklists_resp.content["checklists"][0]["title"] == "Yayın"


def test_operations_add_asset_and_checklist_endpoints():
    mod = _load_web_server()
    calls = {}

    class _Db:
        async def add_content_asset(self, **kwargs):
            calls["asset"] = kwargs
            return types.SimpleNamespace(
                id=41,
                campaign_id=kwargs["campaign_id"],
                tenant_id=kwargs["tenant_id"],
                asset_type=kwargs["asset_type"],
                title=kwargs["title"],
                content=kwargs["content"],
                channel=kwargs["channel"],
                metadata_json='{"region":"TR"}',
                created_at="2026-03-21T00:00:00+00:00",
                updated_at="2026-03-21T00:00:00+00:00",
            )

        async def add_operation_checklist(self, **kwargs):
            calls["checklist"] = kwargs
            return types.SimpleNamespace(
                id=51,
                campaign_id=kwargs["campaign_id"],
                tenant_id=kwargs["tenant_id"],
                title=kwargs["title"],
                items_json='["UTM","QA"]',
                status=kwargs["status"],
                owner_user_id=kwargs["owner_user_id"],
                created_at="2026-03-21T00:00:00+00:00",
                updated_at="2026-03-21T00:00:00+00:00",
            )

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_Db()))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    user = types.SimpleNamespace(id="u-7", username="alice", role="user", tenant_id="tenant-a")

    asset_req = mod._ContentAssetCreateRequest(
        asset_type="campaign_copy",
        title="Hero Copy",
        content="Launch now",
        channel="instagram",
        metadata={"region": "TR"},
    )
    checklist_req = mod._OperationChecklistCreateRequest(
        title="Go Live",
        items=["UTM", "QA"],
        status="pending",
    )

    asset_resp = asyncio.run(mod.api_operations_add_asset(campaign_id=9, req=asset_req, _user=user))
    checklist_resp = asyncio.run(mod.api_operations_add_checklist(campaign_id=9, req=checklist_req, _user=user))

    assert calls["asset"] == {
        "campaign_id": 9,
        "tenant_id": "tenant-a",
        "asset_type": "campaign_copy",
        "title": "Hero Copy",
        "content": "Launch now",
        "channel": "instagram",
        "metadata": {"region": "TR"},
    }
    assert asset_resp.content["asset"]["id"] == 41
    assert asset_resp.content["asset"]["metadata_json"] == '{"region":"TR"}'

    assert calls["checklist"] == {
        "campaign_id": 9,
        "tenant_id": "tenant-a",
        "title": "Go Live",
        "items": ["UTM", "QA"],
        "status": "pending",
        "owner_user_id": "u-7",
    }
    assert checklist_resp.content["checklist"]["id"] == 51
    assert checklist_resp.content["checklist"]["items_json"] == '["UTM","QA"]'
