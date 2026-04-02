from __future__ import annotations

import asyncio
import importlib.util
import importlib.machinery
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.__spec__ = importlib.machinery.ModuleSpec("httpx", loader=None)

    class AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_httpx.AsyncClient = AsyncClient
    sys.modules["httpx"] = fake_httpx

if importlib.util.find_spec("jwt") is None:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.__spec__ = importlib.machinery.ModuleSpec("jwt", loader=None)
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub"}
    sys.modules["jwt"] = fake_jwt

if importlib.util.find_spec("redis") is None:
    fake_redis = types.ModuleType("redis")
    fake_redis_asyncio = types.ModuleType("redis.asyncio")
    fake_redis_exceptions = types.ModuleType("redis.exceptions")
    fake_redis.__spec__ = importlib.machinery.ModuleSpec("redis", loader=None)
    fake_redis_asyncio.__spec__ = importlib.machinery.ModuleSpec("redis.asyncio", loader=None)
    fake_redis_exceptions.__spec__ = importlib.machinery.ModuleSpec("redis.exceptions", loader=None)

    class Redis:
        pass

    class ResponseError(Exception):
        pass

    fake_redis_asyncio.Redis = Redis
    fake_redis_exceptions.ResponseError = ResponseError
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio
    sys.modules["redis.exceptions"] = fake_redis_exceptions

_REVIEWER_PATH = Path(__file__).resolve().parents[1] / "agent" / "roles" / "reviewer_agent.py"
_REVIEWER_SPEC = importlib.util.spec_from_file_location("reviewer_agent_direct", _REVIEWER_PATH)
assert _REVIEWER_SPEC and _REVIEWER_SPEC.loader
_reviewer_mod = importlib.util.module_from_spec(_REVIEWER_SPEC)
sys.modules[_REVIEWER_SPEC.name] = _reviewer_mod
_REVIEWER_SPEC.loader.exec_module(_reviewer_mod)
ReviewerAgent = _reviewer_mod.ReviewerAgent


def test_reviewer_run_task_rejects_when_browser_signals_fail() -> None:
    reviewer = ReviewerAgent.__new__(ReviewerAgent)
    reviewer.config = SimpleNamespace(REVIEWER_TEST_COMMAND="pytest -q")

    class _Events:
        async def publish(self, *_args, **_kwargs) -> None:
            return None

    reviewer.events = _Events()

    async def _run_dynamic_tests(_context: str) -> str:
        return "[TEST:PASS]"

    async def _call_tool(name: str, _arg: str) -> str:
        if name == "run_tests":
            return "komut başarılı"
        if name == "graph_impact":
            return json.dumps({"status": "ok", "reports": []}, ensure_ascii=False)
        if name == "browser_signals":
            return json.dumps(
                {"status": "failed", "risk": "yüksek", "summary": "browser fail", "failed_actions": ["browser_click"]},
                ensure_ascii=False,
            )
        if name == "lsp_diagnostics":
            return "LSP diagnostics temiz."
        return ""

    reviewer._run_dynamic_tests = _run_dynamic_tests
    reviewer.call_tool = _call_tool
    reviewer.delegate_to = lambda _agent, payload, reason="": payload

    raw = asyncio.run(reviewer.run_task("review_code|{\"review_context\":\"core/db.py\"}"))
    feedback = json.loads(raw.split("qa_feedback|", 1)[1])

    assert feedback["decision"] == "REJECT"
    assert feedback["risk"] == "yüksek"
    assert feedback["browser_signal_summary"]["status"] == "failed"


def test_reviewer_run_task_routes_unknown_prompt_to_open_pr_listing() -> None:
    reviewer = ReviewerAgent.__new__(ReviewerAgent)

    class _Events:
        async def publish(self, *_args, **_kwargs) -> None:
            return None

    reviewer.events = _Events()

    async def _call_tool(name: str, arg: str) -> str:
        return f"{name}:{arg}"

    reviewer.call_tool = _call_tool

    result = asyncio.run(reviewer.run_task("belirsiz görev metni"))

    assert result == "list_prs:open"
