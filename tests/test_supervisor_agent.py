# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

import asyncio

from agent.core.contracts import DelegationRequest, TaskEnvelope, TaskResult
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


def test_supervisor_routes_review_intent_to_reviewer(monkeypatch):
    s = SupervisorAgent()

    async def fake_review_run_task(prompt: str) -> str:
        return f"REVIEW:{prompt}"

    monkeypatch.setattr(s.reviewer, "run_task", fake_review_run_task)

    out = asyncio.run(s.run_task("GitHub issue ve pull request incele"))
    assert out.startswith("REVIEW:")


def test_supervisor_routes_code_intent_to_coder(monkeypatch):
    s = SupervisorAgent()

    async def fake_coder_run_task(prompt: str) -> str:
        return f"CODER:{prompt}"

    async def fake_reviewer_run_task(prompt: str) -> str:
        return "[REVIEW:PASS] Kod uygun."

    monkeypatch.setattr(s.coder, "run_task", fake_coder_run_task)
    monkeypatch.setattr(s.reviewer, "run_task", fake_reviewer_run_task)

    out = asyncio.run(s.run_task("test.py isimli bir dosyaya 'print(hello)' yaz"))
    assert out.startswith("CODER:")

def test_supervisor_retries_coder_when_review_fails(monkeypatch):
    s = SupervisorAgent()
    calls = {"coder": 0}

    async def fake_coder_run_task(prompt: str) -> str:
        calls["coder"] += 1
        return f"CODER_RUN_{calls['coder']}:{prompt}"

    async def fake_review_run_task(prompt: str) -> str:
        if "CODER_RUN_1" in prompt:
            return "[REVIEW:FAIL] regresyon bulundu"
        return "[REVIEW:PASS] kalite uygun"

    monkeypatch.setattr(s.coder, "run_task", fake_coder_run_task)
    monkeypatch.setattr(s.reviewer, "run_task", fake_review_run_task)

    out = asyncio.run(s.run_task("özellik ekle"))

    assert calls["coder"] == 2
    assert "2. tur" in out

def test_supervisor_routes_p2p_delegation_from_reviewer_to_coder(monkeypatch):
    s = SupervisorAgent()

    async def fake_coder_run_task(prompt: str):
        if prompt.startswith("qa_feedback|"):
            return "[CODER:APPROVED] ack"
        return "CODER:initial"

    async def fake_reviewer_run_task(_prompt: str):
        return DelegationRequest(
            task_id="p2p-1",
            reply_to="reviewer",
            target_agent="coder",
            payload="qa_feedback|decision=APPROVE;risk=düşük",
        )

    monkeypatch.setattr(s.coder, "run_task", fake_coder_run_task)
    monkeypatch.setattr(s.reviewer, "run_task", fake_reviewer_run_task)

    out = asyncio.run(s.run_task("bir kod görevi"))
    assert "CODER:" in out or "ack" in out