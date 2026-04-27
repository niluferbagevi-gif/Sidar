import asyncio
import importlib
import sys
import types

import pytest


def _import_module_with_stubs():
    fake_config = types.ModuleType("config")

    class _Config:  # pragma: no cover - simple stub
        pass

    fake_config.Config = _Config
    sys.modules["config"] = fake_config

    fake_core_db = types.ModuleType("core.db")

    class _Database:  # pragma: no cover - replaced in tests
        pass

    fake_core_db.Database = _Database
    sys.modules["core.db"] = fake_core_db

    return importlib.import_module("scripts.load_test_db_pool")


class _FakeConn:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    async def execute(self, query: str):
        if self.should_fail:
            raise RuntimeError("boom")
        return query


class _AcquireCtx:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    async def __aenter__(self):
        return _FakeConn(should_fail=self.should_fail)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    def acquire(self, timeout: float):
        assert timeout > 0
        return _AcquireCtx(should_fail=self.should_fail)


class _FakeDb:
    def __init__(self, backend: str = "postgresql"):
        self._backend = backend
        self.pool_size = 7
        self._pg_pool = _FakePool()
        self.connected = False
        self.closed = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.closed = True


def test_run_once_returns_latency_ms_for_successful_query():
    module = _import_module_with_stubs()
    db = _FakeDb()
    latency = asyncio.run(module._run_once(db, acquire_timeout_s=0.5))
    assert latency is not None
    assert latency >= 0


def test_run_once_returns_none_on_query_failure():
    module = _import_module_with_stubs()
    db = _FakeDb()
    db._pg_pool = _FakePool(should_fail=True)
    latency = asyncio.run(module._run_once(db, acquire_timeout_s=0.5))
    assert latency is None


def test_run_load_test_rejects_non_postgres_and_closes_db(monkeypatch):
    module = _import_module_with_stubs()
    fake_db = _FakeDb(backend="sqlite")

    monkeypatch.setattr(module, "Database", lambda _cfg: fake_db)

    with pytest.raises(RuntimeError, match="yalnızca PostgreSQL"):
        asyncio.run(
            module.run_load_test(
                database_url="postgresql://user:pass@localhost:5432/sidar",
                concurrency=1,
                requests=1,
                warmup_requests=0,
                acquire_timeout_s=0.1,
            )
        )

    assert fake_db.connected is True
    assert fake_db.closed is True


def test_run_load_test_prints_fail_when_all_requests_fail(monkeypatch, capsys):
    module = _import_module_with_stubs()
    fake_db = _FakeDb(backend="postgresql")
    fake_db._pg_pool = _FakePool(should_fail=True)
    monkeypatch.setattr(module, "Database", lambda _cfg: fake_db)

    asyncio.run(
        module.run_load_test(
            database_url="postgresql://user:pass@localhost:5432/sidar",
            concurrency=2,
            requests=3,
            warmup_requests=0,
            acquire_timeout_s=0.1,
        )
    )

    out = capsys.readouterr().out
    assert "POOL_LOAD_TEST_START" in out
    assert "POOL_LOAD_TEST_FAIL" in out
    assert "success=0" in out
    assert fake_db.closed is True


def test_run_load_test_prints_ok_metrics(monkeypatch, capsys):
    module = _import_module_with_stubs()
    fake_db = _FakeDb(backend="postgresql")
    monkeypatch.setattr(module, "Database", lambda _cfg: fake_db)

    asyncio.run(
        module.run_load_test(
            database_url="postgresql://user:pass@localhost:5432/sidar",
            concurrency=2,
            requests=4,
            warmup_requests=1,
            acquire_timeout_s=0.1,
        )
    )

    out = capsys.readouterr().out
    assert "POOL_LOAD_TEST_START" in out
    assert "POOL_LOAD_TEST_OK" in out
    assert "success=4" in out
    assert fake_db.closed is True


@pytest.mark.parametrize(
    ("argv", "expected_msg"),
    [
        (
            ["prog", "--database-url", "postgresql://x", "--concurrency", "0"],
            "--concurrency en az 1 olmalıdır.",
        ),
        (
            ["prog", "--database-url", "postgresql://x", "--requests", "0"],
            "--requests en az 1 olmalıdır.",
        ),
        (
            ["prog", "--database-url", "postgresql://x", "--warmup-requests", "-1"],
            "--warmup-requests negatif olamaz.",
        ),
        (
            ["prog", "--database-url", "postgresql://x", "--acquire-timeout", "0"],
            "--acquire-timeout 0'dan büyük olmalıdır.",
        ),
    ],
)
def test_main_rejects_invalid_arguments(monkeypatch, argv, expected_msg):
    module = _import_module_with_stubs()
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit, match=expected_msg):
        module.main()


def test_main_runs_load_test_with_parsed_args(monkeypatch):
    module = _import_module_with_stubs()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--database-url",
            "postgresql://user:pass@localhost:5432/sidar",
            "--concurrency",
            "3",
            "--requests",
            "9",
            "--warmup-requests",
            "2",
            "--acquire-timeout",
            "1.5",
        ],
    )

    captured = {}

    async def fake_run_load_test(
        database_url, concurrency, requests, warmup_requests, acquire_timeout_s
    ):
        captured["args"] = (database_url, concurrency, requests, warmup_requests, acquire_timeout_s)

    original_asyncio_run = asyncio.run

    def fake_asyncio_run(coro):
        captured["asyncio_run_called"] = True
        return original_asyncio_run(coro)

    monkeypatch.setattr(module, "run_load_test", fake_run_load_test)
    monkeypatch.setattr(module.asyncio, "run", fake_asyncio_run)

    module.main()

    assert captured["asyncio_run_called"] is True
    assert captured["args"] == (
        "postgresql://user:pass@localhost:5432/sidar",
        3,
        9,
        2,
        1.5,
    )
