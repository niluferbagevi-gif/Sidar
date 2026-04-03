from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if "httpx" not in sys.modules and importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")
    class _Request:
        def __init__(self, method: str, url: str):
            self.method = method
            self.url = url

    class _Response:
        def __init__(self, status_code: int, request=None):
            self.status_code = status_code
            self.request = request

    class _HTTPStatusError(Exception):
        def __init__(self, message: str, *, request, response):
            super().__init__(message)
            self.request = request
            self.response = response

    class _TimeoutException(Exception):
        pass

    class _RequestError(Exception):
        pass

    fake_httpx.AsyncClient = object
    fake_httpx.Timeout = lambda *args, **kwargs: None
    fake_httpx.Request = _Request
    fake_httpx.Response = _Response
    fake_httpx.HTTPStatusError = _HTTPStatusError
    fake_httpx.TimeoutException = _TimeoutException
    fake_httpx.RequestError = _RequestError
    sys.modules["httpx"] = fake_httpx

if "redis" not in sys.modules and importlib.util.find_spec("redis") is None:
    fake_redis_asyncio = types.ModuleType("redis.asyncio")
    fake_redis_asyncio.Redis = type("Redis", (), {"from_url": classmethod(lambda cls, *_a, **_k: cls())})
    fake_redis_exceptions = types.ModuleType("redis.exceptions")
    fake_redis_exceptions.ResponseError = Exception
    fake_redis = types.ModuleType("redis")
    fake_redis.asyncio = fake_redis_asyncio
    fake_redis.exceptions = fake_redis_exceptions
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio
    sys.modules["redis.exceptions"] = fake_redis_exceptions

def _load_coder_agent():
    role_path = Path(__file__).resolve().parents[1] / "agent" / "roles" / "coder_agent.py"
    spec = importlib.util.spec_from_file_location("tests_coder_agent", role_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CoderAgent


CoderAgent = _load_coder_agent()


class _Events:
    async def publish(self, *_args, **_kwargs):
        return None


def _agent() -> CoderAgent:
    agent = CoderAgent.__new__(CoderAgent)
    agent.events = _Events()
    agent.cfg = SimpleNamespace(BASE_DIR=".")
    return agent


def test_parse_qa_feedback_json_key_value_and_invalid_json() -> None:
    parsed_json = CoderAgent._parse_qa_feedback('{"decision":"reject","summary":"failing"}')
    assert parsed_json["decision"] == "reject"

    parsed_kv = CoderAgent._parse_qa_feedback("decision=approve;summary=ok")
    assert parsed_kv["decision"] == "approve"

    parsed_bad_json = CoderAgent._parse_qa_feedback("{invalid")
    assert parsed_bad_json["raw"].startswith("{invalid")


def test_run_task_handles_empty_feedback_review_and_legacy_fallback() -> None:
    agent = _agent()

    async def _call_tool(name, arg):
        return f"tool:{name}:{arg}"

    agent.call_tool = _call_tool
    agent.delegate_to = lambda role, payload, reason=None: f"delegate:{role}:{payload}:{reason}"

    assert asyncio.run(agent.run_task("")) == "[UYARI] Boş kodlayıcı görevi verildi."

    reject = asyncio.run(
        agent.run_task(
            'qa_feedback|{"decision":"reject","summary":"tests","dynamic_test_output":"dyn","regression_test_output":"reg"}'
        )
    )
    assert "[CODER:REWORK_REQUIRED]" in reject
    assert "[FAILED_TESTS] dyn" in reject

    approve = asyncio.run(agent.run_task("qa_feedback|decision=approve;summary=looks good"))
    assert "[CODER:APPROVED]" in approve

    routed = asyncio.run(agent.run_task("read_file|README.md"))
    assert routed.startswith("tool:read_file")

    review = asyncio.run(agent.run_task("request_review|patch diff"))
    assert review.startswith("delegate:reviewer")

    nl_write = asyncio.run(agent.run_task("notes.txt isimli bir dosyaya 'merhaba' yaz"))
    assert nl_write == "tool:write_file:notes.txt|merhaba"

    legacy = asyncio.run(agent.run_task("bilinmeyen komut"))
    assert legacy.startswith("[LEGACY_FALLBACK]")
