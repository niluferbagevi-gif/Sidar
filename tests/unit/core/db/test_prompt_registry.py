import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.db import prompt_registry


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePgPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


class _TrackingTransaction:
    """Records enter/exit (including whether an exception was in flight)."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def __aenter__(self):
        self._events.append("enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._events.append("exit" if exc_type is None else f"exit-with-{exc_type.__name__}")
        return False


class _FakePostgresDb:
    _backend = "postgresql"

    def __init__(self, conn) -> None:
        self._pg_pool = _FakePgPool(conn)

    def _utc_now_pair(self):
        return "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00"


@pytest.mark.asyncio
async def test_ensure_default_prompt_registry_logs_upsert_failure(monkeypatch, caplog):
    class Loader:
        def exec_module(self, module):
            module.SIDAR_SYSTEM_PROMPT = "default prompt"

    monkeypatch.setattr(
        importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: SimpleNamespace(loader=Loader()),
    )
    monkeypatch.setattr(importlib.util, "module_from_spec", lambda _spec: SimpleNamespace())

    async def no_active_prompt(*_args, **_kwargs):
        return None

    monkeypatch.setattr(prompt_registry, "get_active_prompt", no_active_prompt)

    async def raise_upsert(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(prompt_registry, "upsert_prompt", raise_upsert)

    with caplog.at_level(logging.WARNING, logger=prompt_registry.logger.name):
        await prompt_registry.ensure_default_prompt_registry(
            SimpleNamespace(), prompt_record_cls=SimpleNamespace
        )

    assert "Varsayılan prompt kaydı oluşturulamadı: db down" in caplog.text


@pytest.mark.asyncio
async def test_upsert_prompt_postgresql_wraps_deactivate_and_insert_in_one_transaction() -> None:
    """Regression test: activation must be atomic, not two separately-committed

    statements, so a crash between them can't leave the role with zero (or two)
    active prompts.
    """
    events: list[str] = []
    conn = AsyncMock()
    conn.transaction = lambda: _TrackingTransaction(events)
    conn.fetchval = AsyncMock(return_value=1)

    call_order: list[str] = []

    async def _execute(*_args, **_kwargs):
        call_order.append("deactivate")

    async def _fetchrow(*_args, **_kwargs):
        call_order.append("insert")
        return {
            "id": 2,
            "role_name": "system",
            "prompt_text": "new",
            "version": 2,
            "is_active": True,
            "created_at": "c",
            "updated_at": "u",
        }

    conn.execute = _execute
    conn.fetchrow = _fetchrow
    db = _FakePostgresDb(conn)

    result = await prompt_registry.upsert_prompt(
        db, "system", "new", activate=True, prompt_record_cls=SimpleNamespace
    )

    assert result.id == 2
    assert call_order == ["deactivate", "insert"]
    assert events == ["enter", "exit"]


@pytest.mark.asyncio
async def test_upsert_prompt_postgresql_rolls_back_on_crash_between_statements() -> None:
    events: list[str] = []
    conn = AsyncMock()
    conn.transaction = lambda: _TrackingTransaction(events)
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock()

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated crash before insert commits")

    conn.fetchrow = _boom
    db = _FakePostgresDb(conn)

    with pytest.raises(RuntimeError):
        await prompt_registry.upsert_prompt(
            db, "system", "new", activate=True, prompt_record_cls=SimpleNamespace
        )

    assert events == ["enter", "exit-with-RuntimeError"]


@pytest.mark.asyncio
async def test_activate_prompt_postgresql_wraps_both_updates_in_one_transaction() -> None:
    """Regression test: deactivating the old row and activating the new one

    must happen inside a single transaction so a crash in between can't leave
    two (or zero) active rows for the same role.
    """
    events: list[str] = []
    conn = AsyncMock()
    conn.transaction = lambda: _TrackingTransaction(events)
    conn.fetchrow = AsyncMock(return_value={"id": 4, "role_name": "system"})

    call_order: list[str] = []

    async def _execute(query, *_args, **_kwargs):
        call_order.append("deactivate-all" if "is_active=FALSE" in query else "activate-one")

    conn.execute = _execute
    db = _FakePostgresDb(conn)

    async def _fake_get_active(role_name):
        return SimpleNamespace(id=4, role_name=role_name)

    db.get_active_prompt = _fake_get_active

    activated = await prompt_registry.activate_prompt(db, 4, prompt_record_cls=SimpleNamespace)

    assert activated is not None
    assert activated.id == 4
    assert call_order == ["deactivate-all", "activate-one"]
    assert events == ["enter", "exit"]


@pytest.mark.asyncio
async def test_activate_prompt_postgresql_rolls_back_on_crash_between_updates() -> None:
    events: list[str] = []
    conn = AsyncMock()
    conn.transaction = lambda: _TrackingTransaction(events)
    conn.fetchrow = AsyncMock(return_value={"id": 4, "role_name": "system"})

    async def _execute(query, *_args, **_kwargs):
        if "is_active=TRUE" in query:
            raise RuntimeError("simulated crash before activating the new row")

    conn.execute = _execute
    db = _FakePostgresDb(conn)

    with pytest.raises(RuntimeError):
        await prompt_registry.activate_prompt(db, 4, prompt_record_cls=SimpleNamespace)

    assert events == ["enter", "exit-with-RuntimeError"]
