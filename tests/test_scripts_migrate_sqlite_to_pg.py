"""
scripts/migrate_sqlite_to_pg.py için birim testleri.
Gerçek SQLite/PostgreSQL bağlantıları mock/geçici dosyalarla izole edilir.
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sqlite3
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SCRIPT_PATH = pathlib.Path(__file__).parent.parent / "scripts" / "migrate_sqlite_to_pg.py"


def _make_mock_asyncpg():
    """asyncpg modülünü taklit eden mock oluşturur."""
    asyncpg_mod = MagicMock()
    asyncpg_mod.connect = AsyncMock(return_value=_make_mock_asyncpg_conn())
    return asyncpg_mod


def _import_script(stub_asyncpg: bool = True):
    sys.modules.pop("migrate_sqlite_to_pg", None)
    if stub_asyncpg and "asyncpg" not in sys.modules:
        sys.modules["asyncpg"] = _make_mock_asyncpg()
    spec = importlib.util.spec_from_file_location("migrate_sqlite_to_pg", str(_SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_test_sqlite(tables: dict[str, list[dict]]) -> pathlib.Path:
    """tables = {"users": [{"id": 1, "name": "ali"}], ...} şeklinde geçici SQLite db oluşturur."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = pathlib.Path(tmp.name)
    conn = sqlite3.connect(str(path))
    for table, rows in tables.items():
        if not rows:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER)")
        else:
            cols = list(rows[0].keys())
            col_defs = ", ".join(f"{c} TEXT" for c in cols)
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")
            placeholders = ", ".join("?" for _ in cols)
            for row in rows:
                conn.execute(f"INSERT INTO {table} VALUES ({placeholders})", [str(row[c]) for c in cols])
    conn.commit()
    conn.close()
    return path


def _make_mock_asyncpg_conn():
    """asyncpg bağlantısını simüle eden mock döndürür."""
    conn = MagicMock()
    conn.close = AsyncMock()
    conn.execute = AsyncMock()

    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)

    return conn


# ─────────────────────────────────────────────────────────
# TABLES_IN_ORDER sabiti
# ─────────────────────────────────────────────────────────

class TestTablesInOrder:
    def test_tables_list_defined(self):
        mod = _import_script()
        assert hasattr(mod, "TABLES_IN_ORDER")
        assert isinstance(mod.TABLES_IN_ORDER, list)
        assert len(mod.TABLES_IN_ORDER) > 0

    def test_tables_contains_users(self):
        mod = _import_script()
        assert "users" in mod.TABLES_IN_ORDER

    def test_tables_contains_messages(self):
        mod = _import_script()
        assert "messages" in mod.TABLES_IN_ORDER

    def test_tables_contains_sessions(self):
        mod = _import_script()
        assert "sessions" in mod.TABLES_IN_ORDER

    def test_users_before_messages(self):
        """Bağımlılık sırası: users önce, messages sonra."""
        mod = _import_script()
        tables = mod.TABLES_IN_ORDER
        assert tables.index("users") < tables.index("messages")


# ─────────────────────────────────────────────────────────
# _load_rows fonksiyon testleri
# ─────────────────────────────────────────────────────────

class TestLoadRows:
    def test_loads_existing_rows(self):
        mod = _import_script()
        path = _make_test_sqlite({"users": [{"id": "1", "name": "ali"}, {"id": "2", "name": "veli"}]})
        try:
            cols, rows = mod._load_rows(path, "users")
            assert set(cols) == {"id", "name"}
            assert len(rows) == 2
        finally:
            path.unlink(missing_ok=True)

    def test_empty_table_returns_cols_from_pragma(self):
        mod = _import_script()
        path = _make_test_sqlite({"users": []})
        try:
            cols, rows = mod._load_rows(path, "users")
            assert isinstance(cols, list)
            assert rows == []
        finally:
            path.unlink(missing_ok=True)

    def test_rows_are_tuples(self):
        mod = _import_script()
        path = _make_test_sqlite({"sessions": [{"id": "abc", "user_id": "1"}]})
        try:
            cols, rows = mod._load_rows(path, "sessions")
            assert all(isinstance(r, tuple) for r in rows)
        finally:
            path.unlink(missing_ok=True)

    def test_col_order_preserved(self):
        mod = _import_script()
        path = _make_test_sqlite({"messages": [{"id": "1", "body": "merhaba", "ts": "2024-01-01"}]})
        try:
            cols, rows = mod._load_rows(path, "messages")
            assert cols[0] in ("id", "body", "ts")
            assert len(cols) == 3
        finally:
            path.unlink(missing_ok=True)

    def test_multiple_rows_returned(self):
        mod = _import_script()
        data = [{"id": str(i), "val": f"v{i}"} for i in range(5)]
        path = _make_test_sqlite({"schema_versions": data})
        try:
            cols, rows = mod._load_rows(path, "schema_versions")
            assert len(rows) == 5
        finally:
            path.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────
# _copy_table fonksiyon testleri
# ─────────────────────────────────────────────────────────

class TestCopyTable:
    def test_dry_run_returns_row_count_without_writing(self):
        async def _run():
            mod = _import_script()
            path = _make_test_sqlite({"users": [{"id": "1", "name": "ali"}, {"id": "2", "name": "veli"}]})
            conn = _make_mock_asyncpg_conn()
            try:
                count = await mod._copy_table(conn, path, "users", dry_run=True)
                assert count == 2
                conn.execute.assert_not_awaited()
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_dry_run_empty_table_returns_zero(self):
        async def _run():
            mod = _import_script()
            path = _make_test_sqlite({"users": []})
            conn = _make_mock_asyncpg_conn()
            try:
                count = await mod._copy_table(conn, path, "users", dry_run=True)
                assert count == 0
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_live_run_calls_truncate_and_insert(self):
        async def _run():
            mod = _import_script()
            path = _make_test_sqlite({"users": [{"id": "1", "name": "ali"}]})
            conn = _make_mock_asyncpg_conn()
            try:
                count = await mod._copy_table(conn, path, "users", dry_run=False)
                assert count == 1
                # TRUNCATE ve INSERT çağrılmış olmalı
                calls = [str(c) for c in conn.execute.await_args_list]
                assert any("TRUNCATE" in c or "INSERT" in c for c in calls)
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_live_run_uses_transaction(self):
        async def _run():
            mod = _import_script()
            path = _make_test_sqlite({"users": [{"id": "1", "name": "ali"}]})
            conn = _make_mock_asyncpg_conn()
            try:
                await mod._copy_table(conn, path, "users", dry_run=False)
                conn.transaction.assert_called_once()
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_empty_columns_returns_zero(self):
        async def _run():
            """Tabloda hiç kolon yoksa 0 dönmeli."""
            mod = _import_script()
            path = _make_test_sqlite({"users": []})
            conn = _make_mock_asyncpg_conn()
            # Boş tabloda _load_rows (id INTEGER) gibi bir şey döner
            with patch.object(mod, "_load_rows", return_value=([], [])):
                try:
                    count = await mod._copy_table(conn, path, "users", dry_run=False)
                    assert count == 0
                finally:
                    path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

# ─────────────────────────────────────────────────────────
# migrate() fonksiyon testleri
# ─────────────────────────────────────────────────────────

class TestMigrate:
    def test_missing_sqlite_raises_file_not_found(self):
        async def _run():
            mod = _import_script(stub_asyncpg=True)
            # asyncpg stub'ının connect'ini gerçekten çağrılmayacak şekilde ayarla
            mock_asyncpg = _make_mock_asyncpg()
            with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
                with pytest.raises(FileNotFoundError, match="bulunamadı"):
                    await mod.migrate(pathlib.Path("/tmp/nonexistent_sidar.db"), "postgresql://localhost/test", dry_run=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_migrate_dry_run_prints_dry_run_label(self, capsys):
        async def _run():
            conn = _make_mock_asyncpg_conn()
            mock_asyncpg = _make_mock_asyncpg()
            mock_asyncpg.connect = AsyncMock(return_value=conn)
            mod = _import_script(stub_asyncpg=False)
            path = _make_test_sqlite({t: [] for t in mod.TABLES_IN_ORDER})
            try:
                with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
                    await mod.migrate(path, "postgresql://localhost/test", dry_run=True)
                out = capsys.readouterr().out
                assert "DRY-RUN" in out
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_migrate_live_prints_migrated_label(self, capsys):
        async def _run():
            conn = _make_mock_asyncpg_conn()
            mock_asyncpg = _make_mock_asyncpg()
            mock_asyncpg.connect = AsyncMock(return_value=conn)
            mod = _import_script(stub_asyncpg=False)
            path = _make_test_sqlite({t: [] for t in mod.TABLES_IN_ORDER})
            try:
                with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
                    await mod.migrate(path, "postgresql://localhost/test", dry_run=False)
                out = capsys.readouterr().out
                assert "MIGRATED" in out
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_migrate_processes_all_tables(self, capsys):
        async def _run():
            conn = _make_mock_asyncpg_conn()
            mock_asyncpg = _make_mock_asyncpg()
            mock_asyncpg.connect = AsyncMock(return_value=conn)
            mod = _import_script(stub_asyncpg=False)
            path = _make_test_sqlite({t: [] for t in mod.TABLES_IN_ORDER})
            try:
                with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
                    await mod.migrate(path, "postgresql://localhost/test", dry_run=True)
                out = capsys.readouterr().out
                for table in mod.TABLES_IN_ORDER:
                    assert table in out, f"{table} çıktıda bulunamadı"
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_migrate_closes_connection_on_success(self):
        async def _run():
            conn = _make_mock_asyncpg_conn()
            mock_asyncpg = _make_mock_asyncpg()
            mock_asyncpg.connect = AsyncMock(return_value=conn)
            mod = _import_script(stub_asyncpg=False)
            path = _make_test_sqlite({t: [] for t in mod.TABLES_IN_ORDER})
            try:
                with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
                    await mod.migrate(path, "postgresql://localhost/test", dry_run=True)
                conn.close.assert_awaited_once()
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_migrate_closes_connection_on_error(self):
        async def _run():
            """_copy_table hata fırlattığında bile conn.close() çağrılmalı."""
            conn = _make_mock_asyncpg_conn()
            mock_asyncpg = _make_mock_asyncpg()
            mock_asyncpg.connect = AsyncMock(return_value=conn)
            mod = _import_script(stub_asyncpg=False)
            path = _make_test_sqlite({t: [] for t in mod.TABLES_IN_ORDER})
            try:
                with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
                    with patch.object(mod, "_copy_table", AsyncMock(side_effect=RuntimeError("pg hatası"))):
                        with pytest.raises(RuntimeError, match="pg hatası"):
                            await mod.migrate(path, "postgresql://localhost/test", dry_run=True)
                conn.close.assert_awaited_once()
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_migrate_with_data_rows(self, capsys):
        async def _run():
            conn = _make_mock_asyncpg_conn()
            mock_asyncpg = _make_mock_asyncpg()
            mock_asyncpg.connect = AsyncMock(return_value=conn)
            mod = _import_script(stub_asyncpg=False)
            tables_data = {t: [] for t in mod.TABLES_IN_ORDER}
            tables_data["users"] = [{"id": "1", "username": "ali"}, {"id": "2", "username": "veli"}]
            path = _make_test_sqlite(tables_data)
            try:
                with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
                    await mod.migrate(path, "postgresql://localhost/test", dry_run=True)
                out = capsys.readouterr().out
                assert "users: 2 row" in out
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_asyncpg_import_error_raises_runtime_error(self):
        async def _run():
            """asyncpg yoksa RuntimeError fırlatılmalı (pragma: no cover satırının testi)."""
            mod = _import_script(stub_asyncpg=False)
            path = _make_test_sqlite({})
            path.touch()
            try:
                # sys.modules'a None atamak import'u ImportError ile durdurur
                with patch.dict(sys.modules, {"asyncpg": None}):
                    with pytest.raises((RuntimeError, ImportError)):
                        await mod.migrate(path, "postgresql://localhost/test", dry_run=True)
            finally:
                path.unlink(missing_ok=True)
        import asyncio as _asyncio
        _asyncio.run(_run())

# ─────────────────────────────────────────────────────────
# main() / argparse testleri
# ─────────────────────────────────────────────────────────

class TestMain:
    def test_main_calls_migrate(self):
        mod = _import_script()
        test_args = [
            "migrate_sqlite_to_pg.py",
            "--sqlite-path", "/tmp/test.db",
            "--postgres-dsn", "postgresql://localhost/test",
        ]
        with patch("sys.argv", test_args):
            with patch.object(mod.asyncio, "run", side_effect=lambda coro: coro.close()) as mock_run:
                mod.main()
                mock_run.assert_called_once()

    def test_main_missing_sqlite_path_exits(self):
        mod = _import_script()
        with patch("sys.argv", ["migrate_sqlite_to_pg.py", "--postgres-dsn", "postgresql://localhost/test"]):
            with pytest.raises(SystemExit):
                mod.main()

    def test_main_missing_postgres_dsn_exits(self):
        mod = _import_script()
        with patch("sys.argv", ["migrate_sqlite_to_pg.py", "--sqlite-path", "/tmp/test.db"]):
            with pytest.raises(SystemExit):
                mod.main()

    def test_main_dry_run_flag(self):
        mod = _import_script()
        captured: list = []

        async def fake_migrate(sqlite_path, postgres_dsn, dry_run):
            captured.append({"sqlite_path": sqlite_path, "dry_run": dry_run})

        test_args = [
            "migrate_sqlite_to_pg.py",
            "--sqlite-path", "/tmp/test.db",
            "--postgres-dsn", "postgresql://localhost/test",
            "--dry-run",
        ]
        with patch("sys.argv", test_args):
            with patch.object(mod, "migrate", fake_migrate):
                mod.main()

        assert len(captured) == 1
        assert captured[0]["dry_run"] is True

    def test_main_no_dry_run_by_default(self):
        mod = _import_script()
        captured: list = []

        async def fake_migrate(sqlite_path, postgres_dsn, dry_run):
            captured.append({"dry_run": dry_run})

        test_args = [
            "migrate_sqlite_to_pg.py",
            "--sqlite-path", "/tmp/test.db",
            "--postgres-dsn", "postgresql://localhost/test",
        ]
        with patch("sys.argv", test_args):
            with patch.object(mod, "migrate", fake_migrate):
                mod.main()

        assert captured[0]["dry_run"] is False

    def test_main_passes_correct_sqlite_path(self):
        mod = _import_script()
        captured: list = []

        async def fake_migrate(sqlite_path, postgres_dsn, dry_run):
            captured.append({"sqlite_path": str(sqlite_path)})

        test_args = [
            "migrate_sqlite_to_pg.py",
            "--sqlite-path", "/data/sidar.db",
            "--postgres-dsn", "postgresql://localhost/test",
        ]
        with patch("sys.argv", test_args):
            with patch.object(mod, "migrate", fake_migrate):
                mod.main()

        assert captured[0]["sqlite_path"] == "/data/sidar.db"
