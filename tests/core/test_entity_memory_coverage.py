from __future__ import annotations

import asyncio
from dataclasses import dataclass

import core.entity_memory as entity_memory


@dataclass
class _Cfg:
    ENABLE_ENTITY_MEMORY: bool = True
    ENTITY_MEMORY_TTL_DAYS: int = 7
    ENTITY_MEMORY_MAX_PER_USER: int = 2
    DATABASE_URL: str = "sqlite+aiosqlite:///tmp/test.db"


class _Result:
    def __init__(self, *, scalar=None, one=None, many=None, rowcount=None):
        self._scalar = scalar
        self._one = one
        self._many = many or []
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _Conn:
    def __init__(self, responses, seen):
        self._responses = responses
        self.seen = seen

    async def execute(self, stmt, params=None):
        self.seen.append((str(stmt), params or {}))
        if self._responses:
            return self._responses.pop(0)
        return _Result()


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args):
        return False


class _Engine:
    def __init__(self, responses):
        self.seen = []
        self._responses = responses
        self.disposed = False

    def begin(self):
        return _Ctx(_Conn(self._responses, self.seen))

    def connect(self):
        return _Ctx(_Conn(self._responses, self.seen))

    async def dispose(self):
        self.disposed = True


def test_entity_memory_disabled_and_singleton(monkeypatch):
    disabled = entity_memory.EntityMemory(config=_Cfg(ENABLE_ENTITY_MEMORY=False))

    assert asyncio.run(disabled.initialize()) is None
    assert asyncio.run(disabled.upsert("u", "k", "v")) is False
    assert asyncio.run(disabled.get("u", "k")) is None
    assert asyncio.run(disabled.get_profile("u")) == {}
    assert asyncio.run(disabled.list_users()) == []
    assert asyncio.run(disabled.delete("u", "k")) is False
    assert asyncio.run(disabled.delete_user("u")) == 0
    assert asyncio.run(disabled.purge_expired()) == 0

    entity_memory._instance = None
    singleton = entity_memory.get_entity_memory(_Cfg())
    again = entity_memory.get_entity_memory(_Cfg())
    assert singleton is again

    entity_memory._instance = object()
    rebuilt = entity_memory.get_entity_memory(_Cfg())
    assert isinstance(rebuilt, entity_memory.EntityMemory)


def test_entity_memory_database_flow(monkeypatch):
    mem = entity_memory.EntityMemory(config=_Cfg(), ttl_days=1, max_per_user=1)
    monkeypatch.setattr(entity_memory, "sql_text", lambda stmt: stmt, raising=False)
    fake = _Engine(
        responses=[
            _Result(scalar=1),  # upsert count
            _Result(),          # eviction delete
            _Result(),          # upsert insert
            _Result(one=("value-1",)),
            _Result(many=[("k1", "v1"), ("k2", "v2")]),
            _Result(many=[("u1",), ("u2",)]),
            _Result(rowcount=1),
            _Result(rowcount=3),
            _Result(rowcount=2),
        ]
    )
    mem._engine = fake

    assert asyncio.run(mem.upsert(" user ", " key ", "v", metadata={"s": 1})) is True
    assert any("DELETE FROM entity_memory WHERE id" in sql for sql, _ in fake.seen)

    assert asyncio.run(mem.get("user", "key")) == "value-1"
    assert asyncio.run(mem.get_profile("user")) == {"k1": "v1", "k2": "v2"}
    assert asyncio.run(mem.list_users()) == ["u1", "u2"]
    assert asyncio.run(mem.delete("user", "key")) is True
    assert asyncio.run(mem.delete_user("user")) == 3
    assert asyncio.run(mem.purge_expired()) == 2

    asyncio.run(mem.close())
    assert mem._engine is None
    assert fake.disposed is True


def test_entity_memory_initialize_without_sqlalchemy(monkeypatch):
    mem = entity_memory.EntityMemory(config=_Cfg())
    monkeypatch.setattr(entity_memory, "_SA_AVAILABLE", False)

    assert asyncio.run(mem.initialize()) is None
    assert mem._engine is None
