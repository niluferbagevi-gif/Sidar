from __future__ import annotations

import importlib.util
import sys
import types


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("jwt"):
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.decode = lambda *args, **kwargs: {}
    fake_jwt.encode = lambda *args, **kwargs: "token"
    sys.modules["jwt"] = fake_jwt

if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")
    class Timeout:
        def __init__(self, *args, **kwargs):
            return None
    fake_httpx.Timeout = Timeout
    fake_httpx.TimeoutException = Exception
    fake_httpx.RequestError = Exception
    fake_httpx.HTTPStatusError = Exception
    fake_httpx.AsyncClient = object
    sys.modules["httpx"] = fake_httpx

if not _has_module("pydantic"):
    fake_pydantic = types.ModuleType("pydantic")
    class BaseModel:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    def Field(default=None, **_kwargs):
        return default
    class ValidationError(Exception):
        pass
    fake_pydantic.BaseModel = BaseModel
    fake_pydantic.Field = Field
    fake_pydantic.ValidationError = ValidationError
    sys.modules["pydantic"] = fake_pydantic

if not _has_module("bs4"):
    fake_bs4 = types.ModuleType("bs4")
    class BeautifulSoup:
        def __init__(self, html, _parser):
            self._html = html
        def __call__(self, *_args, **_kwargs):
            return []
        def get_text(self, **_kwargs):
            return self._html
    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.db import Database, _quote_sql_identifier
from core.rag import DocumentStore
from managers.code_manager import CodeManager
from agent import sidar_agent
from agent.swarm import SwarmOrchestrator, SwarmTask, TaskRouter


def test_core_db_quote_identifier_and_sqlite_rollback(tmp_path: Path) -> None:
    assert _quote_sql_identifier("schema_versions") == '"schema_versions"'
    with pytest.raises(ValueError):
        _quote_sql_identifier("bad-name")

    db = Database(SimpleNamespace(DATABASE_URL=f"sqlite:///{tmp_path / 'x.db'}", BASE_DIR=tmp_path))

    class _Conn:
        def __init__(self):
            self.rollback_calls = 0

        def rollback(self):
            self.rollback_calls += 1

    db._sqlite_conn = _Conn()
    db._sqlite_lock = asyncio.Lock()

    async def _run():
        with pytest.raises(RuntimeError):
            await db._run_sqlite_op(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    asyncio.run(_run())
    assert db._sqlite_conn.rollback_calls == 1


def test_core_rag_chunking_and_input_guards(tmp_path: Path) -> None:
    store = DocumentStore.__new__(DocumentStore)
    store.cfg = SimpleNamespace(RAG_CHUNK_SIZE=12, RAG_CHUNK_OVERLAP=20)
    store._chunk_size = 12
    store._chunk_overlap = 4

    chunks = DocumentStore._chunk_text(store, "abcdef" * 10)
    assert chunks
    assert all(chunk for chunk in chunks)

    with pytest.raises(ValueError):
        DocumentStore._validate_url_safe("file:///etc/passwd")
    with pytest.raises(ValueError):
        DocumentStore._validate_url_safe("http://localhost/secret")

    ok_missing, msg_missing = DocumentStore.add_document_from_file(store, str(tmp_path / "missing.py"))
    assert ok_missing is False and "bulunamadı" in msg_missing

    binary = tmp_path / "data.bin"
    binary.write_bytes(b"\x00\x01")
    ok_bin, msg_bin = DocumentStore.add_document_from_file(store, str(binary))
    assert ok_bin is False and "Desteklenmeyen dosya türü" in msg_bin


def test_code_manager_file_io_exceptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = CodeManager.__new__(CodeManager)
    manager.security = SimpleNamespace(
        can_read=lambda _path: True,
        can_write=lambda _path: True,
        get_safe_write_path=lambda name: tmp_path / name,
    )
    manager._lock = threading.RLock()
    manager._files_read = 0
    manager._files_written = 0
    manager.base_dir = tmp_path
    manager._post_process_written_file = lambda _target: None
    manager.validate_python_syntax = lambda _content: (True, "")

    ok_read, msg_read = manager.read_file(str(tmp_path / "nope.py"))
    assert ok_read is False and "Dosya bulunamadı" in msg_read

    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")))
    ok_write, msg_write = manager.write_file(str(tmp_path / "a.py"), "print('x')", validate=False)
    assert ok_write is False and "Yazma erişimi reddedildi" in msg_write


def test_sidar_agent_and_swarm_yellow_zone_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)

    parsed = agent._parse_tool_call("```json\n{\"tool\":\"web_search\",\"argument\":\"x\"}\n```")
    assert parsed and parsed["tool"] == "web_search"

    fallback = agent._parse_tool_call("not-json")
    assert fallback == {"tool": "final_answer", "argument": "not-json"}

    router = TaskRouter()

    class _Spec:
        def __init__(self, role_name: str):
            self.role_name = role_name

    monkeypatch.setattr("agent.swarm.AgentCatalog.find_by_capability", lambda _cap: [])
    monkeypatch.setattr("agent.swarm.AgentCatalog.list_all", lambda: [_Spec("researcher")])
    assert router.route("unknown").role_name == "researcher"

    orch = SwarmOrchestrator(SimpleNamespace(AI_PROVIDER="openai"))
    text = orch._compose_goal_with_context(
        "Görev",
        {
            "browser_session_id": "s-1",
            "browser_signal_summary": "alert",
            "browser_signal_status": "warn",
            "browser_signal_risk": "high",
        },
    )
    assert "[BROWSER_SIGNALS]" in text

    assert orch._should_fallback_to_supervisor(ValueError("json malformed")) is True
    assert orch._should_fallback_to_supervisor(RuntimeError("other")) is False

    task = SwarmTask(goal="test", intent="qa")
    assert task.intent == "qa"
