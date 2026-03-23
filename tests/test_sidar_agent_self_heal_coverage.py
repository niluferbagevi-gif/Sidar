import asyncio
from types import SimpleNamespace

from tests.test_sidar_agent_runtime import (
    ExternalTrigger,
    SA_MOD,
    _make_agent_for_runtime,
)


async def _noop(*_args, **_kwargs):
    return None


def test_collect_self_heal_snapshots_and_build_plan_empty_scope():
    agent = _make_agent_for_runtime()

    class _Code:
        def read_file(self, path, _with_numbers=False):
            if path == "missing.py":
                return False, "permission denied"
            return True, f"content:{path}"

    agent.code = _Code()

    snapshots = asyncio.run(
        agent._collect_self_heal_snapshots(["", "./missing.py", "./good.py"])
    )
    assert snapshots == [{"path": "good.py", "content": "content:good.py"}]

    plan = asyncio.run(
        agent._build_self_heal_plan(
            ci_context={"workflow_name": "ci"},
            diagnosis="diag",
            remediation_loop={"scope_paths": [], "validation_commands": ["pytest -q"]},
        )
    )
    assert plan["operations"] == []
    assert plan["validation_commands"] == ["pytest -q"]
    assert "kapsamı boş" in plan["summary"]


def test_execute_self_heal_plan_handles_empty_ops_backup_failure_and_patch_failure():
    agent = _make_agent_for_runtime()
    agent.cfg = SimpleNamespace(BASE_DIR="/repo")

    empty = asyncio.run(
        agent._execute_self_heal_plan(
            remediation_loop={"validation_commands": ["pytest -q"]},
            plan={"summary": "", "operations": [], "validation_commands": ["pytest -q"]},
        )
    )
    assert empty["status"] == "skipped"
    assert "patch operasyonu içermediği" in empty["summary"]

    writes = []

    class _CodeBackupFail:
        def read_file(self, path, _with_numbers=False):
            return False, PermissionError("permission denied")

        def patch_file(self, path, target, replacement):
            return True, "patched"

        def write_file(self, path, content, _with_numbers=False):
            writes.append((path, content))
            return True, "restored"

        def run_shell_in_sandbox(self, command, base_dir):
            return True, f"ok:{command}:{base_dir}"

    agent.code = _CodeBackupFail()
    backup_fail = asyncio.run(
        agent._execute_self_heal_plan(
            remediation_loop={"validation_commands": ["pytest -q"]},
            plan={
                "summary": "plan",
                "confidence": "medium",
                "operations": [{"path": "a.py", "target": "x", "replacement": "y"}],
                "validation_commands": ["pytest -q"],
            },
        )
    )
    assert backup_fail["status"] == "reverted"
    assert "yedekleme başarısız" in backup_fail["summary"]
    assert writes == []

    writes.clear()

    class _CodePatchFail:
        def read_file(self, path, _with_numbers=False):
            return True, "original-content"

        def patch_file(self, path, target, replacement):
            return False, TimeoutError("sandbox timeout")

        def write_file(self, path, content, _with_numbers=False):
            writes.append((path, content))
            return True, "restored"

        def run_shell_in_sandbox(self, command, base_dir):
            return True, f"ok:{command}:{base_dir}"

    agent.code = _CodePatchFail()
    patch_fail = asyncio.run(
        agent._execute_self_heal_plan(
            remediation_loop={"validation_commands": ["pytest -q"]},
            plan={
                "summary": "plan",
                "confidence": "medium",
                "operations": [{"path": "b.py", "target": "x", "replacement": "y"}],
                "validation_commands": ["pytest -q"],
            },
        )
    )
    assert patch_fail["status"] == "reverted"
    assert "patch edilemedi" in patch_fail["summary"]
    assert writes == [("b.py", "original-content")]


def test_update_remediation_step_and_execute_self_heal_plan_reuse_existing_backup():
    agent = _make_agent_for_runtime()
    agent.cfg = SimpleNamespace(BASE_DIR="/repo")

    remediation_loop = {"steps": [{"name": "analyze", "status": "planned", "detail": ""}]}
    SA_MOD.SidarAgent._update_remediation_step(remediation_loop, "missing", status="done", detail="no-op")
    assert remediation_loop["steps"][0] == {"name": "analyze", "status": "planned", "detail": ""}

    reads = []
    patches = []

    class _Code:
        def read_file(self, path, _with_numbers=False):
            reads.append(path)
            return True, f"original:{path}"

        def patch_file(self, path, target, replacement):
            patches.append((path, target, replacement))
            return True, "patched"

        def write_file(self, path, content, _with_numbers=False):
            raise AssertionError("restore should not run on successful self-heal")

        def run_shell_in_sandbox(self, command, base_dir):
            return True, f"ok:{command}:{base_dir}"

    agent.code = _Code()

    result = asyncio.run(
        agent._execute_self_heal_plan(
            remediation_loop={"validation_commands": ["pytest -q"]},
            plan={
                "summary": "plan",
                "confidence": "medium",
                "operations": [
                    {"path": "same.py", "target": "A", "replacement": "B"},
                    {"path": "same.py", "target": "B", "replacement": "C"},
                ],
                "validation_commands": ["pytest -q"],
            },
        )
    )

    assert result["status"] == "applied"
    assert reads == ["same.py"]
    assert patches == [("same.py", "A", "B"), ("same.py", "B", "C")]


def test_attempt_autonomous_self_heal_guard_paths_and_missing_operations(monkeypatch):
    agent = _make_agent_for_runtime()
    agent.cfg = SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=True)

    remediation = {"remediation_loop": {"status": "draft", "steps": []}}
    skipped = asyncio.run(
        agent._attempt_autonomous_self_heal(
            ci_context={"workflow_name": "ci"},
            diagnosis="diag",
            remediation=remediation,
        )
    )
    assert skipped == {"status": "skipped", "summary": "Remediation loop plan durumunda değil."}

    remediation_hitl = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": True,
            "steps": [{"name": "handoff", "status": "pending", "detail": ""}],
        }
    }
    awaiting = asyncio.run(
        agent._attempt_autonomous_self_heal(
            ci_context={"workflow_name": "ci"},
            diagnosis="diag",
            remediation=remediation_hitl,
        )
    )
    assert awaiting["status"] == "awaiting_hitl"
    assert remediation_hitl["remediation_loop"]["steps"][0]["status"] == "awaiting_hitl"

    remediation_blocked = {"remediation_loop": {"status": "planned", "steps": []}}
    blocked = asyncio.run(
        agent._attempt_autonomous_self_heal(
            ci_context={"workflow_name": "ci"},
            diagnosis="diag",
            remediation=remediation_blocked,
        )
    )
    assert blocked == {"status": "blocked", "summary": "Self-heal için code/llm bağımlılıkları hazır değil."}

    agent.code = object()
    agent.llm = object()

    async def _empty_plan(**_kwargs):
        return {"summary": "none", "operations": [], "validation_commands": [], "confidence": "low"}

    agent._build_self_heal_plan = _empty_plan
    remediation_no_ops = {
        "remediation_loop": {
            "status": "planned",
            "steps": [{"name": "patch", "status": "pending", "detail": ""}],
        }
    }
    no_ops = asyncio.run(
        agent._attempt_autonomous_self_heal(
            ci_context={"workflow_name": "ci"},
            diagnosis="diag",
            remediation=remediation_no_ops,
        )
    )
    assert no_ops == {"status": "blocked", "summary": "LLM patch planı üretilemedi."}
    assert remediation_no_ops["remediation_loop"]["steps"][0]["status"] == "blocked"
    assert "güvenli patch planı üretemedi" in remediation_no_ops["remediation_loop"]["steps"][0]["detail"]


def test_handle_external_trigger_records_self_heal_failure_summary(monkeypatch):
    agent = _make_agent_for_runtime()
    agent.initialize = lambda: asyncio.sleep(0)

    async def _multi(_prompt):
        return "teşhis özeti"

    async def _heal_fail(**_kwargs):
        raise RuntimeError("json parse failed")

    monkeypatch.setattr(
        SA_MOD,
        "build_ci_remediation_payload",
        lambda ctx, summary: {"summary": summary, "remediation_loop": {"status": "planned", "steps": []}},
    )
    agent._try_multi_agent = _multi
    agent._attempt_autonomous_self_heal = _heal_fail

    record = asyncio.run(
        agent.handle_external_trigger(
            ExternalTrigger(
                trigger_id="tr-heal",
                source="webhook:github",
                event_name="workflow_run",
                payload={"kind": "workflow_run", "workflow_name": "CI", "job": "tests"},
            )
        )
    )

    assert record["status"] == "success"
    assert record["remediation"]["self_heal_execution"]["status"] == "failed"
    assert "json parse failed" in record["remediation"]["self_heal_execution"]["summary"]


def test_attempt_autonomous_self_heal_marks_patch_and_validate_failed_when_execution_reverts():
    agent = _make_agent_for_runtime()
    agent.cfg = SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = object()
    agent.llm = object()

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "steps": [
                {"name": "patch", "status": "pending", "detail": ""},
                {"name": "validate", "status": "pending", "detail": ""},
                {"name": "handoff", "status": "pending", "detail": ""},
            ],
        }
    }

    async def _plan(**_kwargs):
        return {
            "summary": "plan",
            "confidence": "medium",
            "operations": [{"path": "app.py", "target": "A", "replacement": "B"}],
            "validation_commands": ["pytest -q"],
        }

    async def _reverted(**_kwargs):
        return {"status": "reverted", "summary": "Sandbox doğrulaması başarısız oldu.", "operations_applied": ["app.py"]}

    agent._build_self_heal_plan = _plan
    agent._execute_self_heal_plan = _reverted

    result = asyncio.run(
        agent._attempt_autonomous_self_heal(
            ci_context={"workflow_name": "ci"},
            diagnosis="diag",
            remediation=remediation,
        )
    )

    assert result["status"] == "reverted"
    assert remediation["remediation_loop"]["status"] == "reverted"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "failed"
    assert remediation["remediation_loop"]["steps"][0]["detail"] == "Sandbox doğrulaması başarısız oldu."
    assert remediation["remediation_loop"]["steps"][1]["status"] == "failed"


def test_run_nightly_memory_maintenance_disabled_and_entity_failure(monkeypatch):
    agent = _make_agent_for_runtime()
    agent.initialize = lambda: asyncio.sleep(0)
    agent._nightly_maintenance_lock = None
    agent._append_autonomy_history = _noop
    agent.docs = SimpleNamespace(consolidate_session_documents=lambda session_id, keep_recent_docs=2: {"session_id": session_id, "removed_docs": 1})
    agent.memory = SimpleNamespace(
        run_nightly_consolidation=lambda **kwargs: asyncio.sleep(0, result={"status": "completed", "session_ids": ["s1"], "sessions_compacted": 1})
    )

    agent.cfg = SimpleNamespace(ENABLE_NIGHTLY_MEMORY_PRUNING=False)
    disabled = asyncio.run(agent.run_nightly_memory_maintenance())
    assert disabled == {"status": "disabled", "reason": "config_disabled"}

    class _EntityMemory:
        async def initialize(self):
            raise RuntimeError("entity store unavailable")

        async def purge_expired(self):
            return 0

    monkeypatch.setattr(SA_MOD, "get_entity_memory", lambda _cfg: _EntityMemory())
    agent.cfg = SimpleNamespace(
        ENABLE_NIGHTLY_MEMORY_PRUNING=True,
        NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=2,
        NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=12,
        NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=2,
    )

    report = asyncio.run(agent.run_nightly_memory_maintenance(force=True, reason="coverage"))
    assert report["status"] == "completed"
    assert report["entity_report"]["status"] == "failed"
    assert "entity store unavailable" in report["entity_report"]["error"]
    assert report["rag_docs_pruned"] == 1
