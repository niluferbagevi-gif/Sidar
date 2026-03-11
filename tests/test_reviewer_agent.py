import asyncio

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