import asyncio
import types

from core.db import Database
from tests.test_web_server_runtime import _FakeRequest, _load_web_server


class _Cfg:
    BASE_DIR = "."
    DATABASE_URL = "sqlite+aiosqlite:///data/test_tenant_rbac.db"
    DB_POOL_SIZE = 2
    DB_SCHEMA_VERSION_TABLE = "schema_versions"
    DB_SCHEMA_TARGET_VERSION = 1
    JWT_SECRET_KEY = "sidar-dev-secret"
    JWT_ALGORITHM = "HS256"



def test_two_tenant_policy_matrix(tmp_path):
    cfg = _Cfg()
    cfg.BASE_DIR = str(tmp_path)
    cfg.DATABASE_URL = "sqlite+aiosqlite:///test_tenant_rbac.db"
    db = Database(cfg)

    async def _run():
        await db.connect()
        await db.init_schema()

        user_a = await db.create_user("tenant_a_user", password="123456", tenant_id="tenant_A")
        user_b = await db.create_user("tenant_b_user", password="123456", tenant_id="tenant_B")

        # tenant_A: sadece RAG read izni
        await db.upsert_access_policy(
            user_id=user_a.id,
            tenant_id="tenant_A",
            resource_type="rag",
            resource_id="*",
            action="read",
            effect="allow",
        )

        # tenant_B: RAG read + swarm execute tam yetki
        await db.upsert_access_policy(
            user_id=user_b.id,
            tenant_id="tenant_B",
            resource_type="rag",
            resource_id="*",
            action="read",
            effect="allow",
        )
        await db.upsert_access_policy(
            user_id=user_b.id,
            tenant_id="tenant_B",
            resource_type="swarm",
            resource_id="*",
            action="execute",
            effect="allow",
        )

        assert await db.check_access_policy(
            user_id=user_a.id,
            tenant_id="tenant_A",
            resource_type="rag",
            action="read",
            resource_id="*",
        ) is True
        assert await db.check_access_policy(
            user_id=user_a.id,
            tenant_id="tenant_A",
            resource_type="swarm",
            action="execute",
            resource_id="*",
        ) is False

        assert await db.check_access_policy(
            user_id=user_b.id,
            tenant_id="tenant_B",
            resource_type="rag",
            action="read",
            resource_id="*",
        ) is True
        assert await db.check_access_policy(
            user_id=user_b.id,
            tenant_id="tenant_B",
            resource_type="swarm",
            action="execute",
            resource_id="*",
        ) is True

        await db.close()

    asyncio.run(_run())



def test_middleware_returns_403_for_tenant_a_swarm_and_allows_tenant_b():
    mod = _load_web_server()

    allowed_matrix = {
        ("tenant_A", "rag", "read"): True,
        ("tenant_A", "swarm", "execute"): False,
        ("tenant_B", "rag", "read"): True,
        ("tenant_B", "swarm", "execute"): True,
    }

    async def _check_access_policy(*, tenant_id, resource_type, action, **_kwargs):
        return allowed_matrix.get((tenant_id, resource_type, action), False)

    async def _get_agent():
        db = types.SimpleNamespace(check_access_policy=_check_access_policy)
        return types.SimpleNamespace(memory=types.SimpleNamespace(db=db))

    mod.get_agent = _get_agent

    async def _next(_request):
        return mod.JSONResponse({"ok": True}, status_code=200)

    req_a_rag = _FakeRequest(path="/rag/docs", method="GET")
    req_a_rag.state.user = types.SimpleNamespace(id="u-a", role="user", username="alice", tenant_id="tenant_A")
    resp_a_rag = asyncio.run(mod.access_policy_middleware(req_a_rag, _next))
    assert resp_a_rag.status_code == 200

    req_a_swarm = _FakeRequest(path="/ws/chat", method="GET")
    req_a_swarm.state.user = types.SimpleNamespace(id="u-a", role="user", username="alice", tenant_id="tenant_A")
    resp_a_swarm = asyncio.run(mod.access_policy_middleware(req_a_swarm, _next))
    assert resp_a_swarm.status_code == 403
    assert resp_a_swarm.content["resource"] == "swarm"
    assert resp_a_swarm.content["action"] == "execute"

    req_b_swarm = _FakeRequest(path="/ws/chat", method="GET")
    req_b_swarm.state.user = types.SimpleNamespace(id="u-b", role="user", username="bob", tenant_id="tenant_B")
    resp_b_swarm = asyncio.run(mod.access_policy_middleware(req_b_swarm, _next))
    assert resp_b_swarm.status_code == 200