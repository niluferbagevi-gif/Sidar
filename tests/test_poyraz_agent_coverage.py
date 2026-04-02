from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

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
    fake_redis_exceptions = types.ModuleType("redis.exceptions")

    class ResponseError(Exception):
        pass

    fake_redis_exceptions.ResponseError = ResponseError
    fake_redis.asyncio = fake_redis_asyncio
    fake_redis.exceptions = fake_redis_exceptions
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio
    sys.modules["redis.exceptions"] = fake_redis_exceptions

for _mod_name, _class_name in [
    ("managers.web_search", "WebSearchManager"),
    ("managers.social_media_manager", "SocialMediaManager"),
    ("core.rag", "DocumentStore"),
]:
    if _mod_name not in sys.modules:
        _mod = types.ModuleType(_mod_name)
        _mod.__dict__[_class_name] = type(_class_name, (), {})
        sys.modules[_mod_name] = _mod

_poyraz_spec = importlib.util.spec_from_file_location(
    "poyraz_agent_direct",
    Path(__file__).resolve().parents[1] / "agent/roles/poyraz_agent.py",
)
_poyraz_mod = importlib.util.module_from_spec(_poyraz_spec)
assert _poyraz_spec and _poyraz_spec.loader
_poyraz_spec.loader.exec_module(_poyraz_mod)
PoyrazAgent = _poyraz_mod.PoyrazAgent


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


def test_generate_campaign_copy_persists_asset_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    persisted: dict[str, object] = {}

    class _Payload:
        channels = ["instagram", "facebook"]
        campaign_name = "Yaz Kampanyası"
        objective = "Lead"
        audience = "SMB"
        offer = "%20 indirim"
        tone = "samimi"
        call_to_action = "Hemen dene"
        store_asset = True
        campaign_id = 42
        tenant_id = "tenant-1"
        asset_title = "Q2 Kampanya"

    async def _fake_generate(prompt: str, mode: str) -> str:
        assert "Yaz Kampanyası" in prompt
        assert mode == "campaign_copy_tool"
        return "üretilen içerik"

    async def _fake_persist_content_asset(**kwargs):
        persisted.update(kwargs)
        return "ok"

    monkeypatch.setattr(_poyraz_mod, "parse_tool_argument", lambda *_args, **_kwargs: _Payload())
    agent._generate_marketing_output = _fake_generate
    agent._persist_content_asset = _fake_persist_content_asset

    result = asyncio.run(agent._tool_generate_campaign_copy("{}"))

    assert result == "üretilen içerik"
    assert persisted["campaign_id"] == 42
    assert persisted["asset_type"] == "campaign_copy"
    assert persisted["title"] == "Q2 Kampanya"
    assert persisted["metadata"]["channels"] == ["instagram", "facebook"]
