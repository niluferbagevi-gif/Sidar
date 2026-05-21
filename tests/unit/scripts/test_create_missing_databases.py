from __future__ import annotations

from pathlib import Path

from scripts import create_missing_databases as cmd


class _FakeCursor:
    def __init__(self) -> None:
        self._last_db = ""
        self.created: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if query.startswith("SELECT 1"):
            self._last_db = params[0]
        elif query.startswith("CREATE DATABASE"):
            self.created.append(self._last_db)

    def fetchone(self):
        return (1,) if self._last_db == "sidar" else None


class _FakeConn:
    def __init__(self) -> None:
        self.autocommit = False
        self.closed = False
        self.cursor_obj = _FakeCursor()

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_main_uses_psycopg2_and_creates_missing_databases(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_PASSWORD=testpw\nPOSTGRES_DB=sidar\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    fake_conn = _FakeConn()

    def _fake_connect(**kwargs):
        assert kwargs["dbname"] == "postgres"
        assert kwargs["password"] == "testpw"
        return fake_conn

    monkeypatch.setattr(cmd.psycopg2, "connect", _fake_connect)

    assert cmd.main() == 0
    assert fake_conn.autocommit is True
    assert fake_conn.closed is True
    assert fake_conn.cursor_obj.created == ["sidar_development", "sidar_test"]
