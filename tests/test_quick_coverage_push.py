import asyncio
import sys
import types
from types import SimpleNamespace

from agent.core.event_stream import AgentEventBus
from agent.sidar_agent import SidarAgent
from core.db import Database


class _AcquireCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self):
        self.fetchval_value = 0
        self.execute_calls = []
        self.fetchrow_value = None

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "EXECUTE 1"

    async def fetchval(self, query, *args):
        return self.fetchval_value

    async def fetchrow(self, query, *args):
        return self.fetchrow_value


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


class _DummySupervisor:
    def __init__(self, _cfg):
        pass

    async def run_task(self, _user_input):
        return ""


def test_event_bus_drops_full_subscriber():
    bus = AgentEventBus()

    async def _run():
        sid, _q = bus.subscribe(maxsize=10)
        for i in range(11):
            await bus.publish("supervisor", f"msg-{i}")
        assert sid not in bus._subscribers

    asyncio.run(_run())


def test_sidar_agent_try_multi_agent_handles_invalid_supervisor_output(monkeypatch):
    agent = object.__new__(SidarAgent)
    agent.cfg = SimpleNamespace()
    agent._supervisor = None

    fake_module = types.ModuleType("agent.core.supervisor")
    fake_module.SupervisorAgent = _DummySupervisor
    monkeypatch.setitem(sys.modules, "agent.core.supervisor", fake_module)

    result = asyncio.run(agent._try_multi_agent("test"))
    assert "geçerli bir çıktı" in result


def test_db_postgresql_early_return_and_remaining_branches(monkeypatch):
    cfg = SimpleNamespace(
        DATABASE_URL="postgresql://user:pass@localhost:5432/sidar",
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=2,
    )
    db = Database(cfg=cfg)
    conn = _FakeConn()
    conn.fetchval_value = 2
    db._pg_pool = _FakePool(conn)

    async def _run():
        await db._ensure_schema_version_postgresql()
        inserts = [q for q, _ in conn.execute_calls if "INSERT INTO schema_versions" in q]
        assert inserts == []

        conn.fetchrow_value = {
            "id": "u-1",
            "username": "alice",
            "password_hash": "hash",
            "role": "admin",
            "created_at": "now",
        }
        monkeypatch.setattr("core.db._verify_password", lambda *_: True)
        user = await db.authenticate_user("alice", "pw")
        assert user is not None and user.username == "alice"

        conn.fetchrow_value = None
        assert await db.get_user_by_token("missing") is None

    asyncio.run(_run())
