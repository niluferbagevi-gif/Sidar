from __future__ import annotations
import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("jwt") is None:
    jwt_stub = types.ModuleType("jwt")

    class _JwtError(Exception):
        pass

    jwt_stub.PyJWTError = _JwtError
    jwt_stub.decode = lambda *_args, **_kwargs: {}
    jwt_stub.encode = lambda *_args, **_kwargs: "token"
    sys.modules["jwt"] = jwt_stub

from core.db import Database
from core.rag import DocumentStore
from managers.code_manager import CodeManager


def _build_manager(tmp_path: Path) -> CodeManager:
    manager = CodeManager.__new__(CodeManager)
    manager.base_dir = tmp_path
    manager.max_output_chars = 80
    manager.docker_exec_timeout = 3
    manager.docker_image = "python:3.11"
    manager.security = SimpleNamespace(
        can_execute=lambda: True,
        is_path_under=lambda path, base: str(path).startswith(str(base)),
    )
    manager._resolve_sandbox_limits = lambda: {
        "memory": "128m",
        "cpus": "1.0",
        "pids_limit": 64,
        "timeout": 5,
        "network_mode": "none",
    }
    manager._resolve_runtime = lambda: "runsc"
    return manager


def test_execute_code_local_returns_error_for_nonzero_exit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _Result())

    ok, output = manager.execute_code_local("raise SystemExit(1)")

    assert ok is False
    assert "Docker yok" in output
    assert "boom" in output


def test_run_shell_in_sandbox_reports_nonzero_exit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    class _Result:
        returncode = 7
        stdout = ""
        stderr = "permission denied"

    monkeypatch.setattr("managers.code_manager.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _Result())

    ok, message = manager.run_shell_in_sandbox("pytest -q", cwd=str(tmp_path))

    assert ok is False
    assert "çıkış kodu: 7" in message
    assert "permission denied" in message


def test_document_store_chunking_and_snippet_helpers() -> None:
    store = DocumentStore.__new__(DocumentStore)

    text = "class A:\n" + ("x" * 30) + "\n\n" + "def run():\n" + ("y" * 40)
    chunks = store._recursive_chunk_text(text, size=35, overlap=5)

    assert chunks
    assert len(chunks) >= 2
    assert any("class A" in part or "def run" in part for part in chunks)
    assert DocumentStore._normalize_pg_url("postgresql+asyncpg://u:p@db/sidar") == "postgresql://u:p@db/sidar"
    assert DocumentStore._format_vector_for_sql([1, 0.25]) == "[1.00000000,0.25000000]"

    snippet = DocumentStore._extract_snippet("alpha beta gamma delta", "beta")
    assert "beta" in snippet


def test_database_verify_auth_token_returns_none_for_missing_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET_KEY="secret",
        JWT_ALGORITHM="HS256",
    )
    db = Database(cfg)
    monkeypatch.setattr("core.db.jwt.decode", lambda *_args, **_kwargs: {"sub": "u-1", "username": "alice"})
    assert db.verify_auth_token("opaque-token") is None


def test_grep_files_invalid_regex_and_missing_path(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    ok_regex, msg_regex = manager.grep_files("(", path=str(tmp_path))
    ok_missing, msg_missing = manager.grep_files("hello", path=str(tmp_path / "missing"))

    assert ok_regex is False
    assert "Geçersiz regex" in msg_regex
    assert ok_missing is False
    assert "Yol bulunamadı" in msg_missing


def test_grep_files_context_and_max_results(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    sample = tmp_path / "notes.txt"
    sample.write_text("alpha\nbeta\nalpha\ngamma\n", encoding="utf-8")

    ok, report = manager.grep_files("alpha", path=str(sample), context_lines=1, max_results=1)

    assert ok is True
    assert "Grep sonuçları" in report
    assert "Maksimum eşleşme" in report
    assert "beta" in report


def test_list_directory_handles_non_directory_and_lists_items(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    child_dir = tmp_path / "src"
    child_dir.mkdir()
    child_file = tmp_path / "README.md"
    child_file.write_text("ok", encoding="utf-8")

    ok_file, msg_file = manager.list_directory(str(child_file))
    ok_dir, msg_dir = manager.list_directory(str(tmp_path))

    assert ok_file is False
    assert "dizin değil" in msg_file
    assert ok_dir is True
    assert "📂 src/" in msg_dir
    assert "📄 README.md" in msg_dir


def test_apply_workspace_edit_applies_reverse_order_and_enforces_permissions(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    target = tmp_path / "module.py"
    target.write_text("name = old\n", encoding="utf-8")

    manager.security = SimpleNamespace(can_write=lambda *_args, **_kwargs: True)
    manager.write_file = lambda _path, content, validate=True: (target.write_text(content, encoding="utf-8") or True, "ok")

    uri = target.resolve().as_uri()
    edit = {
        "changes": {
            uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 7},
                        "end": {"line": 0, "character": 10},
                    },
                    "newText": "new",
                }
            ]
        }
    }

    ok, message = manager._apply_workspace_edit(edit)

    assert ok is True
    assert "Değişen dosya sayısı: 1" in message
    assert target.read_text(encoding="utf-8") == "name = new\n"

    manager.security = SimpleNamespace(can_write=lambda *_args, **_kwargs: False)
    denied_ok, denied_msg = manager._apply_workspace_edit(edit)
    assert denied_ok is False
    assert "yazma yetkisi yok" in denied_msg
