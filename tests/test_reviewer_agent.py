import asyncio

from agent.core.contracts import DelegationRequest
from agent.roles.reviewer_agent import ReviewerAgent


def test_reviewer_agent_initializes_expected_tools():
    a = ReviewerAgent()
    assert set(a.tools.keys()) == {"repo_info", "list_prs", "pr_diff", "list_issues", "run_tests"}


def test_reviewer_agent_run_tests_tool_rejects_unsafe_command():
    a = ReviewerAgent()
    out = asyncio.run(a.call_tool("run_tests", "rm -rf /"))
    assert "Kullanım" in out


def test_reviewer_agent_dispatches_run_tests_command(monkeypatch):
    a = ReviewerAgent()

    async def fake_run_tests(arg: str) -> str:
        return f"ran:{arg}"

    a.tools["run_tests"] = fake_run_tests
    out = asyncio.run(a.run_task("run_tests|pytest -q tests/test_reviewer_agent.py"))
    assert out == "ran:pytest -q tests/test_reviewer_agent.py"

def test_reviewer_review_code_returns_p2p_feedback(monkeypatch):
    a = ReviewerAgent()

    async def fake_dynamic(_ctx: str) -> str:
        return "[TEST:OK] dynamic"

    async def fake_run_tests(arg: str) -> str:
        return "[TEST:OK] regresyon"

    monkeypatch.setattr(a, "_run_dynamic_tests", fake_dynamic)
    a.tools["run_tests"] = fake_run_tests

    out = asyncio.run(a.run_task("review_code|print('x')"))
    assert isinstance(out, DelegationRequest)
    assert out.target_agent == "coder"
    assert out.payload.startswith("qa_feedback|")
