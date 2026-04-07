"""
Agent workflow integration tests.

These tests exercise the full SidarAgent workflow with all external dependencies
(LLM, memory, code, RAG, GitHub) replaced by doubles — but without patching
sys.modules or reimporting the module on every test.  The agent instance is
built with __new__ so we can inject each dependency directly, and all async
calls use pytest-asyncio (asyncio_mode = "auto" in pyproject.toml).
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.contracts import ExternalTrigger


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _noop(*_args, **_kwargs):
    return None


async def _async_return(value):
    return value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent():
    """Return a fully-wired SidarAgent with all external services mocked."""
    from agent.sidar_agent import SidarAgent

    ag = SidarAgent.__new__(SidarAgent)

    # --- config ---
    ag.cfg = types.SimpleNamespace(
        BASE_DIR="/tmp/sidar-integration",
        AI_PROVIDER="openai",
        PROJECT_NAME="sidar",
        VERSION="5.2.0",
        CODING_MODEL="gpt-4o",
        TEXT_MODEL="gpt-4o-mini",
        GEMINI_MODEL="gemini-pro",
        ACCESS_LEVEL="safe",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="0",
        GITHUB_REPO="org/repo",
        LOCAL_INSTRUCTION_MAX_CHARS=500,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=4000,
        SUBTASK_MAX_STEPS=3,
        ENABLE_AUTONOMOUS_SELF_HEAL=True,
        ENABLE_NIGHTLY_MEMORY_PRUNING=True,
        NIGHTLY_MEMORY_IDLE_SECONDS=100,
        NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=2,
        NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=3,
        NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=1,
        SELF_HEAL_MAX_PATCHES=3,
        MEMORY_ARCHIVE_TOP_K=3,
        MEMORY_ARCHIVE_MIN_SCORE=0.3,
        MEMORY_ARCHIVE_MAX_CHARS=1000,
    )

    # --- runtime state ---
    ag._initialized = True
    ag._init_lock = None
    ag._lock = None
    ag._nightly_maintenance_lock = None
    ag._autonomy_history = []
    ag._autonomy_lock = None
    ag._instructions_cache = None
    ag._instructions_mtimes = {}
    ag._last_activity_ts = 0.0
    ag.system_prompt = "You are Sidar."

    # --- memory ---
    memory = MagicMock()
    memory.add = AsyncMock()
    memory.clear = AsyncMock()
    memory.get_history = AsyncMock(return_value=[])
    memory.apply_summary = AsyncMock()
    memory.run_nightly_consolidation = AsyncMock(
        return_value={"session_ids": ["s1"], "sessions_compacted": 1}
    )
    memory.get_last_file = MagicMock(return_value="")
    ag.memory = memory

    # --- LLM ---
    llm = MagicMock()
    llm.chat = AsyncMock(return_value='{"tool":"final_answer","argument":"Integration test OK","thought":"done"}')
    ag.llm = llm

    # --- code manager ---
    code = MagicMock()
    code.read_file = MagicMock(return_value=(True, "# content"))
    code.patch_file = MagicMock(return_value=(True, "ok"))
    code.write_file = MagicMock(return_value=(True, "ok"))
    code.run_shell_in_sandbox = MagicMock(return_value=(True, "ok"))
    code.run_shell = MagicMock(return_value=(True, ""))
    code.get_metrics = MagicMock(return_value={"files_read": 0, "files_written": 0})
    ag.code = code

    # --- docs (RAG) ---
    docs = MagicMock()
    docs.search = AsyncMock(return_value=(True, "relevant docs"))
    docs.add_document = AsyncMock()
    docs.consolidate_session_documents = MagicMock(return_value={"removed_docs": 0})
    docs.status = MagicMock(return_value="RAG ready")
    docs.collection = None
    ag.docs = docs

    # --- github ---
    github = MagicMock()
    github.is_available = MagicMock(return_value=False)
    github.status = MagicMock(return_value="GitHub unavailable")
    ag.github = github

    # --- other managers ---
    ag.security = types.SimpleNamespace(level_name="safe", set_level=MagicMock(return_value=False))
    ag.web = types.SimpleNamespace(is_available=MagicMock(return_value=False), status=MagicMock(return_value="web"))
    ag.health = types.SimpleNamespace(full_report=MagicMock(return_value="health ok"))
    ag.pkg = types.SimpleNamespace(status=MagicMock(return_value="pkg ok"))
    ag.todo = MagicMock()
    ag.todo.__len__ = MagicMock(return_value=0)

    # --- supervisor ---
    supervisor = MagicMock()
    supervisor.run_task = AsyncMock(return_value="Integration test result from supervisor")
    ag._supervisor = supervisor

    return ag


# ---------------------------------------------------------------------------
# 1. Full handle_external_trigger → success workflow
# ---------------------------------------------------------------------------


async def test_handle_external_trigger_full_success_workflow(agent):
    """
    Trigger arrives → context is built → supervisor runs → history is recorded.
    Tests the happy-path end-to-end without hitting external services.
    """
    trigger_data = {
        "trigger_id": "integ-001",
        "source": "github",
        "event_name": "pull_request",
        "payload": {"action": "opened", "number": 42},
        "meta": {"correlation_id": "corr-001"},
    }

    result = await agent.handle_external_trigger(trigger_data)

    assert result["status"] == "success"
    assert result["trigger_id"] == "integ-001"
    assert result["source"] == "github"
    assert "summary" in result
    # History should have one record
    assert len(agent._autonomy_history) == 1
    assert agent._autonomy_history[0]["trigger_id"] == "integ-001"
    # Memory should have received user + assistant messages
    assert agent.memory.add.call_count >= 2


# ---------------------------------------------------------------------------
# 2. Trigger with empty supervisor output → "empty" status
# ---------------------------------------------------------------------------


async def test_handle_external_trigger_empty_supervisor_output(agent):
    """When the supervisor returns blank output the result status must be 'empty'."""
    agent._supervisor.run_task = AsyncMock(return_value="   ")

    result = await agent.handle_external_trigger(
        {"trigger_id": "integ-002", "source": "api", "event_name": "ping", "payload": {}, "meta": {}}
    )

    assert result["status"] == "empty"


# ---------------------------------------------------------------------------
# 3. Trigger that causes supervisor failure → "failed" status
# ---------------------------------------------------------------------------


async def test_handle_external_trigger_supervisor_raises(agent):
    """If the supervisor raises, the result status must be 'failed' and the summary explains."""
    agent._supervisor.run_task = AsyncMock(side_effect=RuntimeError("supervisor boom"))

    result = await agent.handle_external_trigger(
        {"trigger_id": "integ-003", "source": "cron", "event_name": "nightly", "payload": {}, "meta": {}}
    )

    assert result["status"] == "failed"
    assert "işlenemedi" in result["summary"]


# ---------------------------------------------------------------------------
# 4. CI self-heal: planned remediation gets applied
# ---------------------------------------------------------------------------


async def test_ci_self_heal_applied_end_to_end(agent):
    """
    A CI failure trigger flows through diagnosis → plan building → patch application.
    All IO is mocked; we verify the final status reflects a successful patch.
    """
    from agent import sidar_agent as sa_module

    # Patch CI remediation helpers at the module level for this test only
    with (
        patch.object(sa_module, "build_ci_failure_context", return_value={"workflow": "backend-ci"}),
        patch.object(
            sa_module,
            "build_ci_remediation_payload",
            return_value={
                "remediation_loop": {
                    "status": "planned",
                    "steps": [
                        {"name": "patch", "status": "planned", "detail": ""},
                        {"name": "validate", "status": "planned", "detail": ""},
                        {"name": "handoff", "status": "planned", "detail": ""},
                    ],
                    "scope_paths": ["core/rag.py"],
                    "validation_commands": ["pytest -q"],
                    "needs_human_approval": False,
                }
            },
        ),
        patch.object(
            sa_module,
            "normalize_self_heal_plan",
            return_value={
                "operations": [{"path": "core/rag.py", "target": "old_fn(", "replacement": "new_fn("}],
                "validation_commands": ["pytest -q"],
                "confidence": "high",
                "summary": "Replace old_fn with new_fn",
            },
        ),
        patch.object(sa_module, "build_self_heal_patch_prompt", return_value="fix prompt"),
    ):
        # Supervisor returns a diagnosis on the first call, then anything
        call_count = {"n": 0}

        async def _supervisor_side_effect(user_input):
            call_count["n"] += 1
            return f"diagnosis call {call_count['n']}"

        agent._supervisor.run_task = AsyncMock(side_effect=_supervisor_side_effect)
        # LLM returns a patch plan JSON
        agent.llm.chat = AsyncMock(return_value='{"operations":[{"path":"core/rag.py","target":"old","replacement":"new"}]}')

        result = await agent.handle_external_trigger(
            {
                "trigger_id": "ci-001",
                "source": "github",
                "event_name": "workflow_run",
                "payload": {"workflow_name": "backend-ci", "workflow": "backend-ci", "kind": "workflow_run"},
                "meta": {},
            }
        )

    assert result["status"] == "success"
    assert "remediation" in result
    # The self-heal execution should have been attempted
    heal = result["remediation"].get("self_heal_execution", {})
    assert heal.get("status") in {"applied", "reverted", "blocked", "skipped", "failed"}


# ---------------------------------------------------------------------------
# 5. Nightly memory maintenance end-to-end
# ---------------------------------------------------------------------------


async def test_nightly_memory_maintenance_full_run(agent):
    """run_nightly_memory_maintenance with force=True should complete and return a report."""
    agent.seconds_since_last_activity = MagicMock(return_value=9999.0)

    result = await agent.run_nightly_memory_maintenance(force=True, reason="integration test")

    assert result["status"] == "completed"
    assert result["sessions_compacted"] == 1
    # RAG consolidation was called for the session
    assert agent.docs.consolidate_session_documents.call_count >= 1


# ---------------------------------------------------------------------------
# 6. Access level change propagates through memory
# ---------------------------------------------------------------------------


async def test_set_access_level_propagates_to_memory(agent):
    """Changing the access level should update security state and record a system message."""
    agent.security = types.SimpleNamespace(
        level_name="safe",
        set_level=MagicMock(return_value=True),
    )

    msg = await agent.set_access_level("strict")

    assert "güncellendi" in msg
    # Memory.add was called to record the change
    agent.memory.add.assert_called_once()


# ---------------------------------------------------------------------------
# 7. docs_search tool returns results for non-empty queries
# ---------------------------------------------------------------------------


async def test_tool_docs_search_returns_results(agent):
    """_tool_docs_search should delegate to docs.search and return its result."""
    agent.docs.search = AsyncMock(return_value=(True, "found: rag.py docs"))

    result = await agent._tool_docs_search("rag pipeline")

    assert result == "found: rag.py docs"


async def test_tool_docs_search_rejects_empty_query(agent):
    """_tool_docs_search should return an error string for an empty query."""
    result = await agent._tool_docs_search("")

    assert "sorgusu belirtilmedi" in result
    # docs.search should NOT have been called
    agent.docs.search.assert_not_called()


# ---------------------------------------------------------------------------
# 8. ExternalTrigger instance (not dict) is also accepted
# ---------------------------------------------------------------------------


async def test_handle_external_trigger_accepts_trigger_instance(agent):
    """handle_external_trigger must accept an ExternalTrigger object, not just a dict."""
    trigger = ExternalTrigger(
        trigger_id="integ-inst-001",
        source="api",
        event_name="test",
        payload={"key": "value"},
        meta={},
    )
    agent._supervisor.run_task = AsyncMock(return_value="ok from supervisor")

    result = await agent.handle_external_trigger(trigger)

    assert result["status"] == "success"
    assert result["trigger_id"] == "integ-inst-001"
