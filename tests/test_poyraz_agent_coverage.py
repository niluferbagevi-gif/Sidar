from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types

_httpx_spec = None
if "httpx" not in sys.modules:
    _httpx_spec = importlib.util.find_spec("httpx")
if _httpx_spec is None and "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_httpx.AsyncClient = AsyncClient
    sys.modules["httpx"] = fake_httpx

if "redis.asyncio" not in sys.modules:
    fake_redis_asyncio = types.ModuleType("redis.asyncio")

    class Redis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

    fake_redis_asyncio.Redis = Redis
    fake_redis = types.ModuleType("redis")
    fake_redis.asyncio = fake_redis_asyncio
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio

from agent.roles.poyraz_agent import PoyrazAgent


class _SocialStub:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict[str, object]] = []

    async def publish_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.ok, "sent"


def test_tool_publish_social_parses_pipe_payload() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent.social = _SocialStub(ok=True)

    result = asyncio.run(
        agent._tool_publish_social("instagram|||Yeni ürün|||@sidar|||https://img|||https://link")
    )

    assert result.startswith("[SOCIAL:PUBLISHED]")
    assert agent.social.calls[0]["platform"] == "instagram"
    assert agent.social.calls[0]["destination"] == "@sidar"


def test_tool_publish_social_handles_json_payload_and_error() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent.social = _SocialStub(ok=False)

    payload = json.dumps(
        {
            "platform": "facebook",
            "text": "Merhaba",
            "destination": "page-id",
            "media_url": "",
            "link_url": "https://example.com",
        }
    )
    result = asyncio.run(agent._tool_publish_social(payload))

    assert result.startswith("[SOCIAL:ERROR]")
    assert agent.social.calls[0]["platform"] == "facebook"


def test_run_task_routes_publish_social_and_blank_prompt_warning() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    async def _fake_call_tool(name: str, arg: str) -> str:
        return f"{name}:{arg}"

    async def _fake_generate(prompt: str, mode: str) -> str:
        return f"{mode}:{prompt}"

    agent.call_tool = _fake_call_tool
    agent._generate_marketing_output = _fake_generate

    assert asyncio.run(agent.run_task("")) == "[UYARI] Boş pazarlama görevi verildi."
    assert asyncio.run(agent.run_task("publish_social|instagram|||metin")) == "publish_social:instagram|||metin"
    assert asyncio.run(agent.run_task("seo_audit|teknik seo")) == "seo_audit:teknik seo"
