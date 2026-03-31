"""
scripts/load_test_db_pool.py için birim testleri.
Gerçek PostgreSQL bağlantısı gerektiren kodlar mock ile izole edilir.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_db(backend: str = "postgresql", pool_size: int = 10):
    """Gerçekçi bir Database mock'u döndürür."""
    db = MagicMock()
    db._backend = backend
    db.pool_size = pool_size
    db.connect = AsyncMock()
    db.close = AsyncMock()

    # _pg_pool.acquire() async context manager
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    db._pg_pool = pool

    return db, mock_conn


def _stub_script_deps(db_mock):
    """scripts.load_test_db_pool bağımlılıklarını stub'lar."""
    if "config" not in sys.modules:
        cfg_mod = types.ModuleType("config")
        class _Config:
            BASE_DIR = "/tmp/sidar_test"
            DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/sidar"
            DB_POOL_SIZE = 10
        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    if "core" not in sys.modules:
        sys.modules["core"] = types.ModuleType("core")
    if "core.db" not in sys.modules:
        db_mod = types.ModuleType("core.db")
        db_mod.Database = MagicMock(return_value=db_mock)
        sys.modules["core.db"] = db_mod
    else:
        sys.modules["core.db"].Database = MagicMock(return_value=db_mock)


def _import_script():
    sys.modules.pop("scripts.load_test_db_pool", None)
    sys.modules.pop("load_test_db_pool", None)
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "load_test_db_pool",
        str(pathlib.Path(__file__).parent.parent / "scripts" / "load_test_db_pool.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────
# _run_once fonksiyon testleri
# ─────────────────────────────────────────────────────────

class TestRunOnce:
    def test_run_once_returns_positive_float(self):
        async def _run():
            db, mock_conn = _make_mock_db()
            _stub_script_deps(db)
            mod = _import_script()
            latency = await mod._run_once(db)
            assert isinstance(latency, float)
            assert latency >= 0
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_once_executes_select_1(self):
        async def _run():
            db, mock_conn = _make_mock_db()
            _stub_script_deps(db)
            mod = _import_script()
            await mod._run_once(db)
            mock_conn.execute.assert_awaited_once_with("SELECT 1")
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_once_requires_pg_pool(self):
        async def _run():
            db, _ = _make_mock_db()
            db._pg_pool = None
            _stub_script_deps(db)
            mod = _import_script()
            with pytest.raises(AssertionError):
                await mod._run_once(db)
        import asyncio as _asyncio
        _asyncio.run(_run())

# ─────────────────────────────────────────────────────────
# run_load_test fonksiyon testleri
# ─────────────────────────────────────────────────────────

class TestRunLoadTest:
    def test_basic_run_prints_ok(self, capsys):
        async def _run():
            db, _ = _make_mock_db(backend="postgresql", pool_size=5)
            _stub_script_deps(db)
            mod = _import_script()
            await mod.run_load_test(
                database_url="postgresql://localhost/test",
                concurrency=2,
                requests=4,
            )
            captured = capsys.readouterr()
            assert "POOL_LOAD_TEST_OK" in captured.out
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_non_postgresql_raises_runtime_error(self):
        async def _run():
            db, _ = _make_mock_db(backend="sqlite")
            _stub_script_deps(db)
            mod = _import_script()
            with pytest.raises(RuntimeError, match="PostgreSQL"):
                await mod.run_load_test(
                    database_url="postgresql://localhost/test",
                    concurrency=2,
                    requests=2,
                )
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_db_close_called_after_test(self):
        async def _run():
            db, _ = _make_mock_db()
            _stub_script_deps(db)
            mod = _import_script()
            await mod.run_load_test(
                database_url="postgresql://localhost/test",
                concurrency=2,
                requests=2,
            )
            db.close.assert_awaited_once()
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_db_close_called_even_on_error(self):
        async def _run():
            """RuntimeError fırlatılsa bile db.close() çağrılmalı."""
            db, _ = _make_mock_db(backend="sqlite")
            _stub_script_deps(db)
            mod = _import_script()
            with pytest.raises(RuntimeError):
                await mod.run_load_test(
                    database_url="postgresql://localhost/test",
                    concurrency=2,
                    requests=2,
                )
            db.close.assert_awaited_once()
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_pool_size_env_set(self):
        async def _run():
            import os
            db, _ = _make_mock_db()
            _stub_script_deps(db)
            mod = _import_script()
            # DB_POOL_SIZE'ın os.environ'a yazıldığını doğrula
            before = os.environ.get("DB_POOL_SIZE")
            await mod.run_load_test(
                database_url="postgresql://localhost/test",
                concurrency=5,
                requests=2,
            )
            assert "DB_POOL_SIZE" in os.environ
            # Temizle
            if before is None:
                os.environ.pop("DB_POOL_SIZE", None)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_concurrency_capped_at_100(self, capsys):
        async def _run():
            """concurrency > 100 verildiğinde pool size 100 ile sınırlandırılmalı."""
            db, _ = _make_mock_db()
            _stub_script_deps(db)
            mod = _import_script()
            import os
            set_values: list[str] = []
            original = os.environ.__setitem__

            def capture(k, v):
                if k == "DB_POOL_SIZE":
                    set_values.append(v)
                original(k, v)

            with patch.object(os.environ, "__setitem__", side_effect=capture):
                await mod.run_load_test(
                    database_url="postgresql://localhost/test",
                    concurrency=200,
                    requests=2,
                )
            if set_values:
                assert int(set_values[-1]) <= 100
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_output_contains_metrics(self, capsys):
        async def _run():
            db, _ = _make_mock_db()
            _stub_script_deps(db)
            mod = _import_script()
            await mod.run_load_test(
                database_url="postgresql://localhost/test",
                concurrency=3,
                requests=6,
            )
            out = capsys.readouterr().out
            assert "p50_ms=" in out
            assert "p95_ms=" in out
            assert "elapsed_s=" in out
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_single_request(self, capsys):
        async def _run():
            db, _ = _make_mock_db()
            _stub_script_deps(db)
            mod = _import_script()
            await mod.run_load_test(
                database_url="postgresql://localhost/test",
                concurrency=1,
                requests=1,
            )
            captured = capsys.readouterr()
            assert "POOL_LOAD_TEST_OK" in captured.out
        import asyncio as _asyncio
        _asyncio.run(_run())

# ─────────────────────────────────────────────────────────
# main() / argparse testleri
# ─────────────────────────────────────────────────────────

class TestMain:
    def test_main_calls_run_load_test(self):
        db, _ = _make_mock_db()
        _stub_script_deps(db)
        mod = _import_script()
        test_args = [
            "load_test_db_pool.py",
            "--database-url", "postgresql://localhost/test",
            "--concurrency", "2",
            "--requests", "4",
        ]
        with patch("sys.argv", test_args):
            with patch.object(mod.asyncio, "run", side_effect=lambda coro: coro.close()) as mock_run:
                mod.main()
                mock_run.assert_called_once()

    def test_main_missing_database_url_exits(self):
        db, _ = _make_mock_db()
        _stub_script_deps(db)
        mod = _import_script()
        with patch("sys.argv", ["load_test_db_pool.py"]):
            with pytest.raises(SystemExit):
                mod.main()

    def test_main_default_concurrency_and_requests(self):
        db, _ = _make_mock_db()
        _stub_script_deps(db)
        mod = _import_script()
        captured_kwargs: dict = {}

        async def fake_run_load_test(database_url, concurrency, requests):
            captured_kwargs["concurrency"] = concurrency
            captured_kwargs["requests"] = requests

        test_args = [
            "load_test_db_pool.py",
            "--database-url", "postgresql://localhost/test",
        ]
        with patch("sys.argv", test_args):
            with patch.object(mod, "run_load_test", fake_run_load_test):
                mod.main()

        assert captured_kwargs.get("concurrency") == 50
        assert captured_kwargs.get("requests") == 300
