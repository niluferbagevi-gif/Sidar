from __future__ import annotations

import asyncio
from types import SimpleNamespace

import core.active_learning as mod


class _Result:
    def __init__(self, rows=None, scalar_value=0):
        self._rows = rows or []
        self._scalar = scalar_value

    def fetchall(self):
        return [SimpleNamespace(_mapping=row) for row in self._rows]

    def scalar(self):
        return self._scalar


class _Conn:
    def __init__(self, queued_results=None):
        self.calls = []
        self._results = list(queued_results or [])

    async def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        return self._results.pop(0) if self._results else _Result()


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Connect(_Begin):
    pass


class _Engine:
    def __init__(self, conn):
        self.conn = conn
        self.disposed = False

    def begin(self):
        return _Begin(self.conn)

    def connect(self):
        return _Connect(self.conn)

    async def dispose(self):
        self.disposed = True


def test_feedback_store_record_and_pending_signals_tag_parsing(monkeypatch) -> None:
    monkeypatch.setattr(mod, "sql_text", lambda q: q, raising=False)
    conn = _Conn(queued_results=[_Result(), _Result(rows=[{"id": 1, "tags": "not-json"}])])
    store = mod.FeedbackStore(config=SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    store._engine = _Engine(conn)

    async def _run():
        ok = await store.record(prompt="p", response="r", rating=1, tags=["a"])
        assert ok is True
        items = await store.get_pending_signals(limit=10)
        return items

    items = asyncio.run(_run())
    assert items[0]["tags"] == []


def test_feedback_store_mark_exported_and_stats_and_close(monkeypatch) -> None:
    monkeypatch.setattr(mod, "sql_text", lambda q: q, raising=False)
    conn = _Conn(
        queued_results=[
            _Result(),
            _Result(scalar_value=3),
            _Result(scalar_value=1),
            _Result(scalar_value=2),
            _Result(scalar_value=1),
        ]
    )
    engine = _Engine(conn)
    store = mod.FeedbackStore(config=SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    store._engine = engine

    monkeypatch.setattr(mod.time, "time", lambda: 123.0)

    async def _run():
        await store.mark_exported([1, 2, 3])
        stats = await store.stats()
        await store.close()
        return stats

    stats = asyncio.run(_run())
    assert stats == {"total": 3, "positive": 1, "negative": 2, "pending_export": 1}
    assert engine.disposed is True


def test_flag_weak_response_builds_tags_and_calls_initialize(monkeypatch) -> None:
    store = mod.FeedbackStore(config=SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    called = {"init": 0, "record": None}

    async def _init():
        called["init"] += 1
        store._engine = object()

    async def _record(**kwargs):
        called["record"] = kwargs
        return True

    monkeypatch.setattr(store, "initialize", _init)
    monkeypatch.setattr(store, "record", _record)

    result = asyncio.run(store.flag_weak_response(prompt="p", response="r", score=99, reasoning=" why "))

    assert result is True
    assert called["init"] == 1
    assert "score:10" in called["record"]["tags"]
    assert "judge_reasoning" in called["record"]["tags"]
