import asyncio
from pathlib import Path

from agent.roles.coder_agent import CoderAgent


def test_coder_agent_has_only_expected_tools():
    a = CoderAgent()
    assert set(a.tools.keys()) == {
        "read_file",
        "write_file",
        "patch_file",
        "execute_code",
        "list_directory",
        "glob_search",
        "grep_search",
        "audit_project",
        "get_package_info",
        "scan_project_todos",
    }


def test_coder_agent_can_handle_natural_language_write_request(tmp_path: Path, monkeypatch):
    a = CoderAgent()

    target = tmp_path / "test.py"

    async def fake_write(arg: str) -> str:
        path, content = arg.split("|", 1)
        Path(path).write_text(content, encoding="utf-8")
        return "ok"

    a.tools["write_file"] = fake_write

    task = f"{target} isimli bir dosyaya 'print(hello)' yaz"
    out = asyncio.run(a.run_task(task))

    assert out == "ok"
    assert target.read_text(encoding="utf-8") == "print(hello)"


def test_coder_agent_run_task_execute_code_and_qa_feedback_reject():
    a = CoderAgent()

    async def fake_execute(arg: str) -> str:
        assert arg == "print('hello')"
        return "executed"

    a.tools["execute_code"] = fake_execute

    execute_out = asyncio.run(a.run_task("execute_code|print('hello')"))
    reject_out = asyncio.run(a.run_task("qa_feedback|decision=reject"))

    assert execute_out == "executed"
    assert reject_out.startswith("[CODER:REWORK_REQUIRED]")


def test_coder_agent_request_review_delegates_to_reviewer(monkeypatch):
    a = CoderAgent()

    captured = {}

    def fake_delegate(target, payload, reason=None):
        captured["target"] = target
        captured["payload"] = payload
        captured["reason"] = reason
        return "delegated"

    monkeypatch.setattr(a, "delegate_to", fake_delegate)
    out = asyncio.run(a.run_task("request_review|please review this patch"))

    assert out == "delegated"
    assert captured == {
        "target": "reviewer",
        "payload": "review_code|please review this patch",
        "reason": "coder_request_review",
    }


def test_coder_agent_run_task_qa_feedback_approved_and_direct_tool_routes():
    a = CoderAgent()

    async def fake_read(arg: str) -> str:
        assert arg == "README.md"
        return "read-ok"

    async def fake_patch(arg: str) -> str:
        assert arg == "a.py|old|new"
        return "patch-ok"

    a.tools["read_file"] = fake_read
    a.tools["patch_file"] = fake_patch

    approved_out = asyncio.run(a.run_task("qa_feedback|Her şey harika görünüyor"))
    read_out = asyncio.run(a.run_task("read_file|README.md"))
    patch_out = asyncio.run(a.run_task("patch_file|a.py|old|new"))

    assert approved_out.startswith("[CODER:APPROVED]")
    assert "Her şey harika" in approved_out
    assert read_out == "read-ok"
    assert patch_out == "patch-ok"


def test_coder_agent_qa_feedback_reject_surfaces_remediation_loop():
    a = CoderAgent()
    payload = {
        "decision": "reject",
        "summary": "Reviewer semantic failure detected.",
        "remediation_loop": {"summary": "Remediation loop hazır: mod=self_heal_with_hitl"},
    }

    out = asyncio.run(a.run_task(f"qa_feedback|{__import__('json').dumps(payload, ensure_ascii=False)}"))

    assert "[REMEDIATION_LOOP] Remediation loop hazır" in out