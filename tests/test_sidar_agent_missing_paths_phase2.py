import asyncio
from pathlib import Path
from types import SimpleNamespace
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
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_httpx.AsyncClient = AsyncClient
    fake_httpx.TimeoutException = Exception
    fake_httpx.ConnectError = Exception
    fake_httpx.HTTPStatusError = Exception
    sys.modules["httpx"] = fake_httpx

if importlib.util.find_spec("bs4") is None:
    fake_bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

from agent import sidar_agent


def test_build_trigger_prompt_variants(monkeypatch):
    trigger = sidar_agent.ExternalTrigger(
        trigger_id="t-1",
        source="github",
        event_name="workflow_run",
        payload={},
        meta={},
    )

    # CI context önceliği
    monkeypatch.setattr(sidar_agent, "build_ci_failure_prompt", lambda ctx: f"CI:{ctx['workflow_name']}")
    got = sidar_agent.SidarAgent._build_trigger_prompt(trigger, {}, {"workflow_name": "tests"})
    assert got == "CI:tests"

    # federation_task prompt
    federation_payload = {
        "kind": "federation_task",
        "federation_task": {
            "task_id": "job-1",
            "source_system": "ext",
            "target_agent": "supervisor",
            "goal": "run checks",
        },
    }
    got = sidar_agent.SidarAgent._build_trigger_prompt(trigger, federation_payload, None)
    assert "[FEDERATION TASK]" in got
    assert "task" not in got.lower() or "goal=run checks" in got

    # action_feedback prompt
    feedback_payload = {
        "kind": "action_feedback",
        "feedback_id": "fb-1",
        "action_name": "run_tests",
        "summary": "ok",
    }
    got = sidar_agent.SidarAgent._build_trigger_prompt(trigger, feedback_payload, None)
    assert "[ACTION FEEDBACK]" in got
    assert "action_name=run_tests" in got


def test_build_trigger_correlation_matches_history():
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent._autonomy_history = [
        {
            "trigger_id": "old-1",
            "source": "gitlab",
            "status": "success",
            "payload": {"task_id": "task-1", "correlation_id": "corr-1"},
            "meta": {},
            "correlation": {"correlation_id": "corr-1"},
        },
        {
            "trigger_id": "old-2",
            "source": "github",
            "status": "failed",
            "payload": {"task_id": "task-2"},
            "meta": {},
            "correlation": {"correlation_id": "corr-2"},
        },
    ]

    trigger = sidar_agent.ExternalTrigger(
        trigger_id="new-1",
        source="github",
        event_name="workflow_run",
        payload={},
        meta={"correlation_id": "corr-1"},
    )

    corr = agent._build_trigger_correlation(trigger, {"task_id": "task-1"})
    assert corr["correlation_id"] == "corr-1"
    assert corr["matched_records"] >= 1
    assert "old-1" in corr["related_trigger_ids"]


def test_get_memory_archive_context_sync_filters_and_limits():
    class _Collection:
        def query(self, **_kwargs):
            return {
                "documents": [["ilk not", "x" * 800, "düşük alaka"]],
                "metadatas": [[
                    {"source": "memory_archive", "title": "A"},
                    {"source": "memory_archive", "title": "B"},
                    {"source": "memory_archive", "title": "C"},
                ]],
                "distances": [[0.1, 0.2, 0.95]],
            }

    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.docs = SimpleNamespace(collection=_Collection())

    out = agent._get_memory_archive_context_sync("pytest", top_k=2, min_score=0.2, max_chars=2000)
    assert "Geçmiş Sohbet Arşivinden" in out
    assert "A:" in out
    assert "B:" in out
    assert "düşük alaka" not in out


def test_load_instruction_files_cache_and_reload(tmp_path):
    base = tmp_path / "repo"
    base.mkdir()
    sidar = base / "SIDAR.md"
    claude = base / "CLAUDE.md"
    sidar.write_text("ilk talimat", encoding="utf-8")
    claude.write_text("ikinci talimat", encoding="utf-8")

    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(BASE_DIR=str(base))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    import threading

    agent._instructions_lock = threading.Lock()

    first = agent._load_instruction_files()
    second = agent._load_instruction_files()
    assert first == second
    assert "SIDAR.md" in first and "CLAUDE.md" in first

    import time
    time.sleep(1.1)
    sidar.write_text("guncel talimat", encoding="utf-8")
    third = agent._load_instruction_files()
    assert "guncel talimat" in third


def test_build_context_for_ollama_includes_trim_note(monkeypatch):
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        PROJECT_NAME="Sidar",
        VERSION="5.1",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        GEMINI_MODEL="g",
        ACCESS_LEVEL="normal",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="0",
        LOCAL_INSTRUCTION_MAX_CHARS=20,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=200,
    )
    agent.security = SimpleNamespace(level_name="normal")
    agent.github = SimpleNamespace(is_available=lambda: False)
    agent.web = SimpleNamespace(is_available=lambda: False)
    agent.docs = SimpleNamespace(status=lambda: "ok")
    agent.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 2})
    agent.memory = SimpleNamespace(get_last_file=lambda: None)
    class _Todo:
        def __len__(self):
            return 0
    agent.todo = _Todo()

    monkeypatch.setattr(agent, "_load_instruction_files", lambda: "x" * 2000)

    text = asyncio.run(agent._build_context())
    assert "AI Sağlayıcı : OLLAMA" in text
    assert "kırpıldı" in text


def test_tool_docs_search_handles_empty_and_mode():
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)

    class _Docs:
        def search(self, query, _unused, mode, session_id):
            assert query == "fastapi"
            assert mode == "bm25"
            assert session_id == "global"
            return True, "bulundu"

    agent.docs = _Docs()
    assert asyncio.run(agent._tool_docs_search("")) == "⚠ Arama sorgusu belirtilmedi."
    assert asyncio.run(agent._tool_docs_search("fastapi|bm25")) == "bulundu"


def test_tool_github_smart_pr_paths():
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)

    # github unavailable
    agent.github = SimpleNamespace(is_available=lambda: False)
    assert asyncio.run(agent._tool_github_smart_pr("")) == "⚠ GitHub token bulunamadı."

    class _Code:
        def __init__(self):
            self.calls = []

        def run_shell(self, cmd):
            self.calls.append(cmd)
            mapping = {
                "git branch --show-current": (True, "feature/x"),
                "git status --short": (True, " M agent/sidar_agent.py"),
                "git diff --stat HEAD": (True, "stat"),
                "git diff --no-color HEAD": (True, "diff"),
                "git log --oneline main..HEAD": (True, "abc commit"),
            }
            return mapping.get(cmd, (True, ""))

    class _GitHub:
        default_branch = "main"

        def is_available(self):
            return True

        def create_pull_request(self, title, body, head, base):
            assert title
            assert "Diff Özeti" in body
            assert head == "feature/x"
            assert base == "main"
            return True, "http://pr"

    agent.code = _Code()
    agent.github = _GitHub()

    out = asyncio.run(agent._tool_github_smart_pr("Başlık|||main|||Notlar"))
    assert out == "✓ PR oluşturuldu: http://pr"


def test_set_access_level_changed_and_unchanged():
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)

    class _Security:
        def __init__(self):
            self.level_name = "restricted"

        def set_level(self, lvl):
            if lvl != self.level_name:
                self.level_name = lvl
                return True
            return False

    class _Memory:
        def __init__(self):
            self.items = []

        async def add(self, role, content):
            self.items.append((role, content))

    agent.security = _Security()
    agent.cfg = SimpleNamespace(ACCESS_LEVEL="restricted")
    agent.memory = _Memory()

    changed = asyncio.run(agent.set_access_level("normal"))
    assert "güncellendi" in changed
    assert agent.cfg.ACCESS_LEVEL == "normal"
    assert len(agent.memory.items) == 2

    unchanged = asyncio.run(agent.set_access_level("normal"))
    assert "zaten 'normal'" in unchanged
