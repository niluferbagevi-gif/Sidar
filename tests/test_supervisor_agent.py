import asyncio

from agent.core.contracts import TaskEnvelope, TaskResult
from agent.core.supervisor import SupervisorAgent


def test_contract_models_basic_shape():
    env = TaskEnvelope(task_id="t1", sender="supervisor", receiver="researcher", goal="g")
    res = TaskResult(task_id="t1", status="done", summary="ok")

    assert env.task_id == "t1"
    assert env.intent == "mixed"
    assert res.status == "done"


def test_supervisor_routes_research_to_researcher(monkeypatch):
    s = SupervisorAgent()

    async def fake_run_task(prompt: str) -> str:
        return f"RESEARCH:{prompt}"

    monkeypatch.setattr(s.researcher, "run_task", fake_run_task)

    out = asyncio.run(s.run_task("Python 3.12 yenilikleri neler? web kaynaklarıyla özetle"))
    assert out.startswith("RESEARCH:")


def test_supervisor_returns_legacy_fallback_for_code_intent():
    s = SupervisorAgent()
    out = asyncio.run(s.run_task("Bu dosyayı patch et ve PR hazırla"))
    assert out.startswith("[LEGACY_FALLBACK]")


def test_supervisor_routes_code_intent_to_coder(monkeypatch):
    s = SupervisorAgent()

    async def fake_coder_run_task(prompt: str) -> str:
        return f"CODER:{prompt}"

    monkeypatch.setattr(s.coder, "run_task", fake_coder_run_task)

    out = asyncio.run(s.run_task("test.py isimli bir dosyaya 'print(hello)' yaz"))
    assert out.startswith("CODER:")