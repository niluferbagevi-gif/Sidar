import asyncio

from core.db import Database


class _Cfg:
    DB_POOL_SIZE = 2
    DB_SCHEMA_VERSION_TABLE = "schema_versions"
    DB_SCHEMA_TARGET_VERSION = 1
    JWT_SECRET_KEY = "sidar-dev-secret"
    JWT_ALGORITHM = "HS256"


def test_prompt_registry_seed_and_activation(tmp_path):
    cfg = _Cfg()
    cfg.BASE_DIR = tmp_path
    cfg.DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'sidar.db').as_posix()}"
    db = Database(cfg=cfg)

    async def _run():
        await db.connect()
        await db.init_schema()
        active = await db.get_active_prompt("system")
        assert active is not None
        assert active.role_name == "system"
        assert active.is_active is True

        created = await db.upsert_prompt("system", "Yeni system prompt", activate=True)
        assert created.version >= 2
        assert created.is_active is True

        items = await db.list_prompts("system")
        assert len(items) >= 2
        assert sum(1 for x in items if x.is_active) == 1

        oldest = items[-1]
        switched = await db.activate_prompt(oldest.id)
        assert switched is not None
        assert switched.id == oldest.id
        assert switched.is_active is True

        await db.close()

    asyncio.run(_run())
