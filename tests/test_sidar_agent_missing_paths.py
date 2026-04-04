import asyncio
from pathlib import Path
from types import MethodType, SimpleNamespace

import importlib.util
import sys
import types

if importlib.util.find_spec("pydantic") is None:
    fake_pydantic = types.ModuleType("pydantic")
    fake_pydantic.BaseModel = object
    fake_pydantic.Field = lambda *a, **k: None
    fake_pydantic.ValidationError = Exception
    sys.modules["pydantic"] = fake_pydantic

if importlib.util.find_spec("jwt") is None:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub"}
    sys.modules["jwt"] = fake_jwt


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.AsyncClient = AsyncClient
    fake_httpx.TimeoutException = Exception
    fake_httpx.ConnectError = Exception
    fake_httpx.HTTPStatusError = Exception
    sys.modules["httpx"] = fake_httpx

if importlib.util.find_spec("bs4") is None:
    fake_bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, *args, **kwargs):
            return None

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

from agent import sidar_agent


def _run(coro):
    return asyncio.run(coro)


def _build_agent():
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(
        ENABLE_NIGHTLY_MEMORY_PRUNING=True,
        NIGHTLY_MEMORY_IDLE_SECONDS=5,
        NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=2,
        NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=3,
        NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=1,
        SUBTASK_MAX_STEPS=2,
        AI_PROVIDER="openai",
        PROJECT_NAME="Sidar",
        VERSION="5.1.0",
        ACCESS_LEVEL="limited",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="0",
        GITHUB_REPO="org/repo",
        BASE_DIR=".",
        GEMINI_MODEL="gemini-test",
        CODING_MODEL="code-model",
        TEXT_MODEL="text-model",
        LOCAL_INSTRUCTION_MAX_CHARS=1000,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=5000,
    )
    agent._autonomy_history = []
    agent._autonomy_lock = None
    agent._nightly_maintenance_lock = None
    agent._last_activity_ts = 0.0
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    import threading

    agent._instructions_lock = threading.Lock()
    return agent


def test_build_trigger_prompt_for_federation_task_and_action_feedback():
    trigger = sidar_agent.ExternalTrigger(trigger_id="t1", source="ext", event_name="event")

    federation_prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        trigger,
        {"kind": "federation_task", "federation_task": {"task_id": "task-1", "goal": "fix", "context": {"a": "b"}}},
        None,
    )
    assert "[FEDERATION TASK]" in federation_prompt
    assert "goal=fix" in federation_prompt

    feedback_prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        trigger,
        {"kind": "action_feedback", "action_name": "run_tests", "summary": "done"},
        None,
    )
    assert "[ACTION FEEDBACK]" in feedback_prompt
    assert "action_name=run_tests" in feedback_prompt


def test_build_trigger_correlation_matches_previous_records():
    agent = _build_agent()
    agent._autonomy_history = [
        {
            "trigger_id": "old-1",
            "source": "github",
            "status": "success",
            "payload": {"task_id": "task-7", "correlation_id": "corr-7"},
            "meta": {},
        }
    ]
    trigger = sidar_agent.ExternalTrigger(trigger_id="new", source="cron", event_name="tick", payload={"task_id": "task-7"})

    correlation = agent._build_trigger_correlation(trigger, {"task_id": "task-7"})

    assert correlation["related_task_id"] == "task-7"
    assert correlation["matched_records"] == 1
    assert correlation["latest_related_status"] == "success"


def test_get_memory_archive_context_sync_filters_and_truncates():
    agent = _build_agent()

    class _Collection:
        def query(self, **_kwargs):
            return {
                "documents": [["x" * 700, "kisa not"]],
                "metadatas": [[{"source": "memory_archive", "title": "Arsiv"}, {"source": "other"}]],
                "distances": [[0.1, 0.1]],
            }

    agent.docs = SimpleNamespace(collection=_Collection())

    text = agent._get_memory_archive_context_sync("sorgu", top_k=3, min_score=0.2, max_chars=800)

    assert "[Geçmiş Sohbet Arşivinden İlgili Notlar]" in text
    assert "Arsiv" in text
    assert "..." in text


def test_tool_github_smart_pr_handles_missing_branch_and_no_changes():
    agent = _build_agent()

    class _Code:
        def __init__(self):
            self.calls = []

        def run_shell(self, cmd):
            self.calls.append(cmd)
            if cmd == "git branch --show-current":
                return True, ""
            return True, ""

    agent.code = _Code()
    agent.github = SimpleNamespace(is_available=lambda: True, default_branch="main", create_pull_request=lambda *args: (True, "url"))
    assert _run(agent._tool_github_smart_pr("title")) == "✗ Aktif branch bulunamadı."

    agent.code = SimpleNamespace(
        run_shell=lambda cmd: (True, "feat/test") if cmd == "git branch --show-current" else ((True, "") if cmd == "git status --short" else (True, ""))
    )
    assert _run(agent._tool_github_smart_pr("title")) == "ℹ Değişiklik bulunamadı; PR oluşturulmadı."


def test_set_access_level_changed_and_unchanged_paths():
    agent = _build_agent()

    memory_entries = []

    class _Security:
        level_name = "limited"
        _already_changed = False

        def set_level(self, new_level):
            if new_level == "admin" and not self._already_changed:
                self.level_name = "admin"
                self._already_changed = True
                return True
            return False

    class _Memory:
        async def add(self, role, content):
            memory_entries.append((role, content))

    agent.security = _Security()
    agent.memory = _Memory()

    msg = _run(agent.set_access_level("admin"))
    assert "güncellendi" in msg
    assert len(memory_entries) == 2

    msg2 = _run(agent.set_access_level("admin"))
    assert "zaten 'admin'" in msg2


def test_status_and_autonomy_activity_summary():
    agent = _build_agent()
    agent.github = SimpleNamespace(status=lambda: "gh")
    agent.web = SimpleNamespace(status=lambda: "web")
    agent.pkg = SimpleNamespace(status=lambda: "pkg")
    agent.docs = SimpleNamespace(status=lambda: "rag")
    agent.health = SimpleNamespace(full_report=lambda: "health")
    agent.memory = [1, 2, 3]
    agent._autonomy_history = [
        {"trigger_id": "1", "status": "success", "source": "cron"},
        {"trigger_id": "2", "status": "failed", "source": "cron"},
    ]

    status_text = agent.status()
    assert "Otonomi      : 2 kayıt" in status_text

    activity = agent.get_autonomy_activity(limit=1)
    assert activity["returned"] == 1
    assert activity["latest_trigger_id"] == "2"


def test_load_instruction_files_uses_cache(tmp_path: Path):
    root = tmp_path
    (root / "SIDAR.md").write_text("root talimat", encoding="utf-8")

    agent = _build_agent()
    agent.cfg.BASE_DIR = str(root)

    first = agent._load_instruction_files()
    assert "root talimat" in first

    # cache hit path
    second = agent._load_instruction_files()
    assert second == first


def test_run_nightly_memory_maintenance_already_running_and_completed(monkeypatch):
    agent = _build_agent()

    async def _fake_initialize():
        return None

    agent.initialize = _fake_initialize
    agent.seconds_since_last_activity = MethodType(lambda _self: 999.0, agent)

    # already-running branch
    agent._nightly_maintenance_lock = asyncio.Lock()
    _run(agent._nightly_maintenance_lock.acquire())
    skipped = _run(agent.run_nightly_memory_maintenance())
    assert skipped["reason"] == "already_running"
    agent._nightly_maintenance_lock.release()

    # completed branch
    class _Memory:
        async def run_nightly_consolidation(self, **_kwargs):
            return {"session_ids": ["s1"], "sessions_compacted": 1}

    class _Docs:
        def consolidate_session_documents(self, *_args, **_kwargs):
            return {"removed_docs": 2}

    agent.memory = _Memory()
    agent.docs = _Docs()

    async def _append(_record):
        return None

    agent._append_autonomy_history = _append

    class _EntityMemory:
        async def initialize(self):
            return None

        async def purge_expired(self):
            return 4

    monkeypatch.setattr(sidar_agent, "get_entity_memory", lambda _cfg: _EntityMemory())

    result = _run(agent.run_nightly_memory_maintenance(force=True, reason="manual"))
    assert result["status"] == "completed"
    assert result["rag_docs_pruned"] == 2
    assert result["entity_report"]["purged"] == 4


def test_build_context_includes_runtime_and_instruction_block(monkeypatch):
    agent = _build_agent()
    agent.security = SimpleNamespace(level_name="limited")
    agent.github = SimpleNamespace(is_available=lambda: True)
    agent.web = SimpleNamespace(is_available=lambda: True)
    agent.docs = SimpleNamespace(status=lambda: "rag")
    agent.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 2})
    agent.memory = SimpleNamespace(get_last_file=lambda: "/tmp/a.py")
    class _Todo:
        def __len__(self):
            return 1

        def list_tasks(self):
            return "- task"

    agent.todo = _Todo()

    monkeypatch.setattr(agent, "_load_instruction_files", lambda: "[Proje Talimat Dosyaları]")

    context = _run(agent._build_context())
    assert "[Proje Ayarları — GERÇEK RUNTIME DEĞERLERİ]" in context
    assert "GitHub     : Bağlı" in context
    assert "[Proje Talimat Dosyaları]" in context
