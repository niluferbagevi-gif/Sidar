import asyncio
import types

from core.db import Database
from tests.test_web_server_runtime import _FakeRequest, _load_web_server


class _Cfg:
    BASE_DIR = "."
    DATABASE_URL = "sqlite+aiosqlite:///data/test_rbac_policy.db"
    DB_POOL_SIZE = 2
    DB_SCHEMA_VERSION_TABLE = "schema_versions"
    DB_SCHEMA_TARGET_VERSION = 1
    JWT_SECRET_KEY = "sidar-dev-secret"
    JWT_ALGORITHM = "HS256"


def test_db_access_policy_roundtrip(tmp_path):
    cfg = _Cfg()
    cfg.BASE_DIR = str(tmp_path)
    cfg.DATABASE_URL = "sqlite+aiosqlite:///test_rbac_policy.db"
    db = Database(cfg)

    async def _run():
        await db.connect()
        await db.init_schema()
        user = await db.create_user("rbac-user", password="123456", tenant_id="tenant-a")
        assert user.tenant_id == "tenant-a"

        await db.upsert_access_policy(
            user_id=user.id,
            tenant_id="tenant-a",
            resource_type="rag",
            resource_id="*",
            action="read",
            effect="allow",
        )
        allowed = await db.check_access_policy(
            user_id=user.id,
            tenant_id="tenant-a",
            resource_type="rag",
            action="read",
            resource_id="doc-1",
        )
        denied = await db.check_access_policy(
            user_id=user.id,
            tenant_id="tenant-a",
            resource_type="github",
            action="write",
            resource_id="org/repo",
        )
        assert allowed is True
        assert denied is False
        await db.close()

    asyncio.run(_run())


def test_web_server_access_policy_middleware_enforces():
    mod = _load_web_server()

    req = _FakeRequest(path="/rag/docs", method="GET")
    req.state.user = types.SimpleNamespace(id="u1", role="user", username="alice", tenant_id="tenant-a")

    async def _next(_request):
        return mod.JSONResponse({"ok": True})

    async def _get_agent():
        db = types.SimpleNamespace(
            check_access_policy=lambda **_kwargs: asyncio.sleep(0, result=False)
        )
        return types.SimpleNamespace(memory=types.SimpleNamespace(db=db))

    mod.get_agent = _get_agent
    resp = asyncio.run(mod.access_policy_middleware(req, _next))
    assert resp.status_code == 403
    assert resp.content["resource"] == "rag"
