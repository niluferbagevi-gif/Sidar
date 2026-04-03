from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from types import MethodType, SimpleNamespace



def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")

    class _Timeout:
        def __init__(self, *args, **kwargs):
            return None

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.Timeout = _Timeout
    fake_httpx.AsyncClient = _AsyncClient
    fake_httpx.TimeoutException = Exception
    fake_httpx.RequestError = Exception
    fake_httpx.HTTPStatusError = Exception
    sys.modules["httpx"] = fake_httpx

if not _has_module("jwt"):
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.decode = lambda *_a, **_k: {}
    fake_jwt.encode = lambda *_a, **_k: "token"
    sys.modules["jwt"] = fake_jwt

if not _has_module("redis"):
    redis_mod = types.ModuleType("redis")
    redis_async = types.ModuleType("redis.asyncio")
    redis_exc = types.ModuleType("redis.exceptions")
    redis_async.Redis = object
    redis_exc.ResponseError = Exception
    sys.modules["redis"] = redis_mod
    sys.modules["redis.asyncio"] = redis_async
    sys.modules["redis.exceptions"] = redis_exc

if not _has_module("bs4"):
    fake_bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, html, _parser):
            self._html = html

        def __call__(self, *_args, **_kwargs):
            return []

        def get_text(self, **_kwargs):
            return self._html

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

from agent.roles.coder_agent import CoderAgent



def test_run_task_handles_reject_feedback_with_remediation_summary() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    agent.events = SimpleNamespace(publish=_publish)

    payload = (
        'qa_feedback|{"decision":"reject","summary":"tests failed",'
        '"dynamic_test_output":"dyn","regression_test_output":"reg",'
        '"remediation_loop":{"summary":"patch required"}}'
    )
    result = asyncio.run(agent.run_task(payload))

    assert "[CODER:REWORK_REQUIRED]" in result
    assert "[REMEDIATION_LOOP] patch required" in result
    assert "[FAILED_TESTS] dyn\n\nreg" in result


def test_run_task_routes_natural_language_write_file_to_tool() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    async def _call_tool(name: str, arg: str) -> str:
        assert name == "write_file"
        assert arg == "notes.txt|Merhaba Dünya"
        return "ok"

    agent.events = SimpleNamespace(publish=_publish)
    agent.call_tool = MethodType(lambda _self, name, arg: _call_tool(name, arg), agent)

    result = asyncio.run(agent.run_task("notes.txt isimli bir dosyaya 'Merhaba Dünya' yaz"))
    assert result == "ok"


def test_run_task_request_review_delegates_to_reviewer() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    agent.events = SimpleNamespace(publish=_publish)
    agent.delegate_to = MethodType(
        lambda _self, role, payload, reason=None: f"{role}|{payload}|{reason}",
        agent,
    )

    result = asyncio.run(agent.run_task("request_review|src/main.py"))
    assert result == "reviewer|review_code|src/main.py|coder_request_review"


def test_parse_qa_feedback_supports_json_key_value_and_raw() -> None:
    parsed_json = CoderAgent._parse_qa_feedback('{"decision":"approve","summary":"ok"}')
    parsed_kv = CoderAgent._parse_qa_feedback("decision=reject;summary=broken")
    parsed_raw = CoderAgent._parse_qa_feedback("{invalid json")

    assert parsed_json["decision"] == "approve"
    assert parsed_kv["decision"] == "reject"
    assert parsed_kv["summary"] == "broken"
    assert parsed_raw["raw"] == "{invalid json"


def test_run_task_returns_legacy_fallback_for_unhandled_prompt() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    agent.events = SimpleNamespace(publish=_publish)
    agent.call_tool = MethodType(lambda _self, _name, _arg: "should-not-be-called", agent)

    result = asyncio.run(agent.run_task("buna özel bir araç eşlemesi yok"))

    assert result.startswith("[LEGACY_FALLBACK]")
    assert "coder_unhandled" in result
