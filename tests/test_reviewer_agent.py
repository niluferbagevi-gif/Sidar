import asyncio
import json

from agent.core.contracts import is_delegation_request
from agent.roles.reviewer_agent import ReviewerAgent


def test_reviewer_agent_initializes_expected_tools():
    a = ReviewerAgent()
    assert set(a.tools.keys()) == {"repo_info", "list_prs", "pr_diff", "list_issues", "run_tests"}
    assert hasattr(a, "code")


def test_reviewer_extracts_changed_paths_safely():
    a = ReviewerAgent()
    paths = a._extract_changed_paths("diff: tests/test_a.py core/db.py ../etc/passwd /tmp/x.py")
    assert "tests/test_a.py" in paths
    assert "core/db.py" in paths
    assert all(".." not in p for p in paths)
    assert all(not p.startswith("/") for p in paths)


def test_reviewer_builds_targeted_plus_regression_commands():
    a = ReviewerAgent()
    cmds = a._build_regression_commands("changed tests/test_reviewer_agent.py and core/db.py")
    assert cmds[0].startswith("pytest -q tests/test_reviewer_agent.py")
    assert any(c == a.cfg.REVIEWER_TEST_COMMAND for c in cmds)


def test_reviewer_build_dynamic_test_content_uses_llm(monkeypatch):
    a = ReviewerAgent()

    async def fake_call_llm(messages, **kwargs):
        assert "add_two" in messages[0]["content"]
        assert kwargs["system_prompt"] == a.TEST_GENERATION_PROMPT
        return "```python\ndef test_generated():\n    assert 2 + 2 == 4\n```"

    monkeypatch.setattr(a, "call_llm", fake_call_llm)
    out = asyncio.run(a._build_dynamic_test_content("function add_two(x): return x + 2"))
    assert "def test_generated" in out


def test_reviewer_agent_run_tests_tool_rejects_unsafe_command():
    a = ReviewerAgent()
    out = asyncio.run(a.call_tool("run_tests", "rm -rf /"))
    assert "Kullanım" in out


def test_reviewer_agent_run_tests_uses_code_manager_sandbox_runner(monkeypatch):
    a = ReviewerAgent()

    def fake_run_shell_in_sandbox(command: str, cwd=None):
        assert command == "pytest -q tests/test_reviewer_agent.py"
        assert cwd == str(a.cfg.BASE_DIR)
        return True, "ok"

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("run_shell should not be used for reviewer sandbox tests")

    monkeypatch.setattr(a.code, "run_shell_in_sandbox", fake_run_shell_in_sandbox)
    monkeypatch.setattr(a.code, "run_shell", fail_if_called)
    out = asyncio.run(a.call_tool("run_tests", "pytest -q tests/test_reviewer_agent.py"))
    assert "[TEST:OK]" in out
    assert "Docker CLI sandbox" in out


def test_reviewer_agent_run_tests_fail_closed_when_sandbox_runner_fails(monkeypatch):
    a = ReviewerAgent()

    def fake_run_shell_in_sandbox(command: str, cwd=None):
        assert command == "pytest -q tests/test_reviewer_agent.py"
        return False, "Docker CLI bulunamadı"

    monkeypatch.setattr(a.code, "run_shell_in_sandbox", fake_run_shell_in_sandbox)
    out = asyncio.run(a.call_tool("run_tests", "pytest -q tests/test_reviewer_agent.py"))
    assert "FAIL-CLOSED" in out
    assert "Docker CLI bulunamadı" in out


def test_reviewer_review_code_returns_p2p_feedback(monkeypatch):
    a = ReviewerAgent()

    async def fake_dynamic(_ctx: str) -> str:
        return "[TEST:OK] dynamic"

    calls = []

    async def fake_run_tests(arg: str) -> str:
        calls.append(arg)
        return f"[TEST:OK] {arg}"

    monkeypatch.setattr(a, "_run_dynamic_tests", fake_dynamic)
    a.tools["run_tests"] = fake_run_tests

    out = asyncio.run(a.run_task("review_code|tests/test_reviewer_agent.py"))
    assert is_delegation_request(out)
    assert out.target_agent == "coder"
    assert out.payload.startswith("qa_feedback|")
    payload = json.loads(out.payload.split("|", 1)[1])
    assert payload["decision"] == "APPROVE"
    assert any(c.startswith("pytest -q tests/test_reviewer_agent.py") for c in calls)
    assert any(c == a.cfg.REVIEWER_TEST_COMMAND for c in calls)


def test_reviewer_review_code_rejects_on_fail_closed(monkeypatch):
    a = ReviewerAgent()

    async def fake_dynamic(_ctx: str) -> str:
        return "[TEST:FAIL-CLOSED] komut=dynamic"

    async def fake_run_tests(arg: str) -> str:
        return f"[TEST:OK] {arg}"

    monkeypatch.setattr(a, "_run_dynamic_tests", fake_dynamic)
    a.tools["run_tests"] = fake_run_tests

    out = asyncio.run(a.run_task("review_code|core/db.py"))
    payload = json.loads(out.payload.split("|", 1)[1])
    assert payload["decision"] == "REJECT"
    assert payload["risk"] == "yüksek"
