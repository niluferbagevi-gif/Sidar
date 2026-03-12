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