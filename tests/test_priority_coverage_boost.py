from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace
import types

import pytest

from core.rag import DocumentStore
from managers import code_manager

if importlib.util.find_spec("jwt") is None:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub"}
    sys.modules["jwt"] = fake_jwt

if importlib.util.find_spec("pydantic") is None:
    fake_pydantic = types.ModuleType("pydantic")
    fake_pydantic.BaseModel = object
    fake_pydantic.Field = lambda *a, **k: None
    fake_pydantic.ValidationError = Exception
    sys.modules["pydantic"] = fake_pydantic


def _install_web_auth_mocks(monkeypatch: pytest.MonkeyPatch, web_server, role: str = "admin") -> None:
    async def _fake_rate(*_args, **_kwargs) -> bool:
        return False

    async def _fake_resolve_user(_agent, _token: str) -> SimpleNamespace:
        return SimpleNamespace(id="u1", username="tester", role=role, tenant_id="default")

    async def _fake_get_agent() -> SimpleNamespace:
        async def _noop(*_args, **_kwargs):
            return None

        return SimpleNamespace(memory=SimpleNamespace(set_active_user=_noop))

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _fake_rate)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve_user)
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)


def test_api_agents_register_swarm_and_hitl_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("httpx")
    from httpx import ASGITransport, AsyncClient
    pytest.importorskip("fastapi")
    import web_server

    _install_web_auth_mocks(monkeypatch, web_server, role="admin")

    import asyncio as _asyncio

    web_server._redis_lock = _asyncio.Lock()
    web_server._local_rate_lock = _asyncio.Lock()

    monkeypatch.setattr(
        web_server,
        "_register_plugin_agent",
        lambda **kwargs: {"role_name": kwargs["role_name"], "version": kwargs["version"]},
    )

    class _FakeSwarmOrchestrator:
        def __init__(self, _cfg):
            pass

        async def run_pipeline(self, tasks, session_id: str):
            return [
                SimpleNamespace(
                    task_id="t1",
                    agent_role=tasks[0].preferred_agent or "planner",
                    status="ok",
                    summary=f"{session_id}:{tasks[0].goal}",
                    elapsed_ms=12,
                    evidence=["e1"],
                    handoffs=[],
                    graph={},
                )
            ]

        async def run_parallel(self, tasks, session_id: str, max_concurrency: int):
            return await self.run_pipeline(tasks, session_id=session_id)

    monkeypatch.setattr(web_server, "SwarmOrchestrator", _FakeSwarmOrchestrator)

    class _PendingReq:
        def to_dict(self) -> dict:
            return {"request_id": "req-1", "action": "deploy"}

    class _FakeStore:
        async def pending(self):
            return [_PendingReq()]

    monkeypatch.setattr(web_server, "get_hitl_store", lambda: _FakeStore())

    async def _run() -> tuple[int, int, int]:
        transport = ASGITransport(app=web_server.app)
        headers = {"Authorization": "Bearer token"}
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            r1 = await client.post(
                "/api/agents/register",
                headers=headers,
                json={
                    "role_name": "custom_agent",
                    "source_code": "class CustomAgent: pass",
                    "class_name": "CustomAgent",
                    "capabilities": ["analyze"],
                    "description": "test",
                    "version": "1.2.3",
                },
            )
            r2 = await client.post(
                "/api/swarm/execute",
                headers=headers,
                json={
                    "mode": "pipeline",
                    "session_id": "s1",
                    "tasks": [{"goal": "coverage artır", "intent": "qa", "preferred_agent": "reviewer"}],
                },
            )
            r3 = await client.get("/api/hitl/pending", headers=headers)
        assert r1.json()["success"] is True
        assert r2.json()["results"][0]["summary"] == "s1:coverage artır"
        assert r3.json()["count"] == 1
        return r1.status_code, r2.status_code, r3.status_code

    assert asyncio.run(_run()) == (200, 200, 200)


def test_ws_chat_rejects_invalid_header_token(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    import web_server
    from fastapi.testclient import TestClient

    class _Mem:
        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 0

    async def _fake_get_agent():
        return SimpleNamespace(memory=_Mem(), respond=lambda _msg: iter(()))

    async def _resolve_none(_agent, _token: str):
        return None

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_none)

    with TestClient(web_server.app) as client:
        with pytest.raises(Exception):
            client.websocket_connect("/ws/chat", subprotocols=["invalid-token"])


def test_document_store_add_document_from_file_and_fetch_chroma(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = DocumentStore.__new__(DocumentStore)
    store._index = {}
    store.store_dir = tmp_path

    captured: dict[str, object] = {}

    def _fake_add(title: str, content: str, source: str = "", tags=None, session_id: str = "global") -> str:
        captured["title"] = title
        captured["content"] = content
        captured["source"] = source
        captured["session_id"] = session_id
        return "doc-123"

    store._add_document_sync = _fake_add
    monkeypatch.setattr("core.rag.Config.BASE_DIR", tmp_path.resolve())

    doc_path = tmp_path / "guide.md"
    doc_path.write_text("Merhaba RAG", encoding="utf-8")
    ok, message = store.add_document_from_file(str(doc_path), session_id="sess-a")
    assert ok is True
    assert "doc-123" in message
    assert captured["title"] == "guide.md"
    assert str(captured["source"]).startswith("file://")

    class _FakeCollection:
        def __init__(self):
            self.kwargs = None

        def count(self):
            return 9

        def query(self, **kwargs):
            self.kwargs = kwargs
            return {
                "ids": [["d1_0", "d1_1", "d2_0"]],
                "documents": [["chunk-a", "chunk-b", "chunk-c"]],
                "metadatas": [[
                    {"parent_id": "d1", "title": "A", "source": "s1"},
                    {"parent_id": "d2", "title": "B", "source": "s2"},
                    {"parent_id": "d2", "title": "B", "source": "s2"},
                ]],
            }

    store.collection = _FakeCollection()
    store.cfg = SimpleNamespace(RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER=1)
    store._is_local_llm_provider = False
    results = store._fetch_chroma("arama", top_k=2, session_id="sess-a")
    assert [item["id"] for item in results] == ["d1", "d2"]
    assert store.collection.kwargs["where"] == {"session_id": "sess-a"}


def test_code_manager_shell_and_sandbox_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = code_manager.CodeManager.__new__(code_manager.CodeManager)
    manager.base_dir = tmp_path
    manager.max_output_chars = 2000
    manager.docker_image = "img"
    manager._resolve_sandbox_limits = lambda: {"memory": "64m", "cpus": "1.0", "pids_limit": 32, "network_mode": "none", "timeout": 5}
    manager._resolve_runtime = lambda: ""

    class _Sec:
        def can_run_shell(self):
            return True

        def can_execute(self):
            return True

        def is_path_under(self, *_args, **_kwargs):
            return True

    manager.security = _Sec()

    def _run_ok(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(code_manager.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(code_manager.subprocess, "run", _run_ok)

    ok_shell, out_shell = manager.run_shell("echo hi")
    ok_sandbox, out_sandbox = manager.run_shell_in_sandbox("pytest -q", cwd=str(tmp_path))
    assert ok_shell is True and out_shell == "ok"
    assert ok_sandbox is True and out_sandbox == "ok"


def test_db_campaign_and_asset_crud_paths(tmp_path: Path) -> None:
    from core.db import Database

    async def _run() -> None:
        cfg = SimpleNamespace(
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'ops.db'}",
            BASE_DIR=tmp_path,
            DB_POOL_SIZE=1,
            DB_SCHEMA_VERSION_TABLE="schema_versions",
            DB_SCHEMA_TARGET_VERSION=1,
        )
        db = Database(cfg)
        await db.connect()
        await db.init_schema()

        campaign = await db.upsert_marketing_campaign(
            tenant_id="default",
            name="Bahar Kampanyası",
            channel="email",
            objective="upsell",
            status="active",
            owner_user_id="u1",
            budget=123.4,
            metadata={"segment": "pro"},
        )
        updated = await db.upsert_marketing_campaign(
            campaign_id=campaign.id,
            tenant_id="default",
            name="Bahar Kampanyası Güncel",
            channel="email",
            objective="upsell",
            status="paused",
            owner_user_id="u2",
            budget=99.0,
            metadata={"segment": "vip"},
        )
        asset = await db.add_content_asset(
            campaign_id=campaign.id,
            tenant_id="default",
            asset_type="banner",
            title="Nisan",
            content="İndirim metni",
            channel="web",
            metadata={"lang": "tr"},
        )
        campaigns = await db.list_marketing_campaigns(tenant_id="default", status="paused")
        assets = await db.list_content_assets(tenant_id="default", campaign_id=campaign.id)
        await db.close()

        assert updated.name.endswith("Güncel")
        assert asset.asset_type == "banner"
        assert len(campaigns) == 1
        assert len(assets) == 1

    asyncio.run(_run())


def test_sidar_handle_external_trigger_and_nightly_success(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("httpx")
    from agent.sidar_agent import SidarAgent

    async def _run() -> None:
        agent = SidarAgent.__new__(SidarAgent)
        agent.cfg = SimpleNamespace(
            ENABLE_NIGHTLY_MEMORY_PRUNING=True,
            NIGHTLY_MEMORY_IDLE_SECONDS=30,
            NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=1,
            NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=2,
            NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=1,
        )
        agent._nightly_maintenance_lock = None
        agent._append_autonomy_history = lambda _record: asyncio.sleep(0)
        agent._memory_add = lambda _role, _content: asyncio.sleep(0)
        agent._ensure_autonomy_runtime_state = lambda: None
        agent.mark_activity = lambda _name: None
        agent._build_trigger_correlation = lambda *_args, **_kwargs: {"correlation_id": "corr-1"}
        agent._build_trigger_prompt = lambda *_args, **_kwargs: "prompt"
        agent._try_multi_agent = lambda _prompt: asyncio.sleep(0, result="özet")
        agent._attempt_autonomous_self_heal = lambda **_kwargs: asyncio.sleep(0, result={"status": "applied"})
        agent.initialize = lambda: asyncio.sleep(0)
        agent.seconds_since_last_activity = MethodType(lambda _self: 999.0, agent)
        agent._autonomy_history = []

        class _Mem:
            async def run_nightly_consolidation(self, **_kwargs):
                return {"session_ids": ["s1"], "sessions_compacted": 1}

        class _Docs:
            def consolidate_session_documents(self, _session_id: str, keep_recent_docs: int):
                assert keep_recent_docs == 1
                return {"removed_docs": 2}

        agent.memory = _Mem()
        agent.docs = _Docs()

        class _EntityMemory:
            async def initialize(self):
                return None

            async def purge_expired(self):
                return 3

        monkeypatch.setattr("agent.sidar_agent.get_entity_memory", lambda _cfg: _EntityMemory())

        record = await agent.handle_external_trigger(
            {"trigger_id": "tr-1", "source": "cron", "event_name": "nightly", "payload": {"kind": "workflow_run", "workflow_name": "ci"}}
        )
        nightly = await agent.run_nightly_memory_maintenance(force=True)
        assert record["status"] == "success"
        assert nightly["status"] == "completed"
        assert nightly["rag_docs_pruned"] == 2

    asyncio.run(_run())
