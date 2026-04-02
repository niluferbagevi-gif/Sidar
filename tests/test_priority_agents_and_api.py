from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx")
from httpx import ASGITransport, AsyncClient

import core.llm_client as llm_client
import web_server
from agent.roles.reviewer_agent import ReviewerAgent
from agent.sidar_agent import SidarAgent


def test_web_register_validation_error_returns_422() -> None:
    import asyncio

    async def _run() -> int:
        transport = ASGITransport(app=web_server.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/auth/register", json={"username": "ab", "password": "123456"})
        return response.status_code

    assert asyncio.run(_run()) == 422


def test_web_metrics_requires_admin_or_metrics_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def _fake_rate(*_args, **_kwargs) -> bool:
        return False

    async def _fake_resolve_user(_agent, _token: str) -> SimpleNamespace:
        return SimpleNamespace(id="u1", username="tester", role="user", tenant_id="default")

    async def _fake_get_agent() -> SimpleNamespace:
        async def _noop(*_args, **_kwargs):
            return None

        return SimpleNamespace(memory=SimpleNamespace(set_active_user=_noop))

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _fake_rate)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve_user)
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    async def _run() -> int:
        transport = ASGITransport(app=web_server.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/metrics", headers={"Authorization": "Bearer token"})
        return response.status_code

    assert asyncio.run(_run()) == 403


def test_llm_retry_with_non_retryable_error_raises_non_retryable_api_error() -> None:
    cfg = SimpleNamespace(LLM_MAX_RETRIES=3, LLM_RETRY_BASE_DELAY=0.01, LLM_RETRY_MAX_DELAY=0.02)

    async def _bad_request():
        req = llm_client.httpx.Request("GET", "https://example.com")
        resp = llm_client.httpx.Response(401, request=req)
        raise llm_client.httpx.HTTPStatusError("unauthorized", request=req, response=resp)

    with pytest.raises(llm_client.LLMAPIError) as err:
        import asyncio

        asyncio.run(llm_client._retry_with_backoff("openai", _bad_request, config=cfg, retry_hint="auth"))

    assert err.value.retryable is False
    assert err.value.status_code == 401


def test_reviewer_run_task_rejects_on_fail_closed_output() -> None:
    import asyncio

    async def _run() -> str:
        reviewer = ReviewerAgent.__new__(ReviewerAgent)
        reviewer.config = SimpleNamespace(REVIEWER_TEST_COMMAND="pytest -q")

        class _Events:
            async def publish(self, *_args, **_kwargs):
                return None

        reviewer.events = _Events()
        reviewer._run_dynamic_tests = AsyncMock(return_value="[TEST:FAIL-CLOSED] dosya bulunamadı")
        reviewer._build_regression_commands = lambda _ctx: ["pytest -q tests/test_missing.py"]

        async def _call_tool(name: str, _arg: str) -> str:
            if name == "run_tests":
                return "komut başarısız: code hatası"
            if name == "graph_impact":
                return json.dumps({"status": "ok", "reports": []}, ensure_ascii=False)
            if name == "browser_signals":
                return json.dumps({"status": "no-signal", "risk": "düşük", "summary": "ok"}, ensure_ascii=False)
            if name == "lsp_diagnostics":
                return ""
            return ""

        reviewer.call_tool = _call_tool
        reviewer.delegate_to = lambda _role, payload, reason="": f"{reason}:{payload}"
        return await reviewer.run_task("review_code|review_context=core/missing.py")

    result = asyncio.run(_run())
    assert "review_decision:qa_feedback|" in result
    feedback_json = result.split("qa_feedback|", 1)[1]
    payload = json.loads(feedback_json)
    assert payload["decision"] == "REJECT"
    assert payload["risk"] == "yüksek"


def test_sidar_subtask_tool_error_branch_then_final_answer() -> None:
    import asyncio

    async def _run() -> str:
        agent = SidarAgent.__new__(SidarAgent)
        agent.cfg = SimpleNamespace(TEXT_MODEL="x", CODING_MODEL="x", SUBTASK_MAX_STEPS=2)

        class _FakeLLM:
            def __init__(self):
                self.calls = 0

            async def chat(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return '{"thought":"t","tool":"read_file","argument":"missing.py"}'
                return '{"thought":"t","tool":"final_answer","argument":"kod hatası işlendi"}'

        agent.llm = _FakeLLM()

        async def _explode(_tool: str, _arg: str) -> str:
            raise RuntimeError("dosya bulunamadı")

        agent._execute_tool = _explode
        return await agent._tool_subtask("kayıp dosyayı incele")

    output = asyncio.run(_run())
    assert output.startswith("✓ Alt Görev Tamamlandı")


def test_auto_handle_regex_edge_case_does_not_match_benign_text() -> None:
    from agent.auto_handle import AutoHandle

    assert AutoHandle._MULTI_STEP_RE.search("öncelikle test sonucu") is None
