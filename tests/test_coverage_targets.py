from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

if "httpx" not in sys.modules:
    _httpx_stub = types.SimpleNamespace(
        TimeoutException=Exception,
        RequestError=Exception,
        Timeout=lambda *args, **kwargs: None,
    )

    class _AsyncClientStub:
        def __init__(self, *args, **kwargs) -> None:
            raise ModuleNotFoundError("httpx is required for networked managers")

    _httpx_stub.AsyncClient = _AsyncClientStub
    sys.modules["httpx"] = _httpx_stub

if "managers.web_search" not in sys.modules:
    _web_search_stub = types.ModuleType("managers.web_search")

    class _WebSearchManagerStub:
        def __init__(self, *args, **kwargs) -> None:
            pass

    _web_search_stub.WebSearchManager = _WebSearchManagerStub
    sys.modules["managers.web_search"] = _web_search_stub

if "managers.social_media_manager" not in sys.modules:
    _social_stub = types.ModuleType("managers.social_media_manager")

    class _SocialMediaManagerStub:
        def __init__(self, *args, **kwargs) -> None:
            pass

    _social_stub.SocialMediaManager = _SocialMediaManagerStub
    sys.modules["managers.social_media_manager"] = _social_stub

from agent.roles.poyraz_agent import PoyrazAgent
from agent.sidar_agent import (
    SidarAgent,
    _default_derive_correlation_id,
    _FallbackActionFeedback,
    _FallbackFederationTaskEnvelope,
)
from core.rag import GraphIndex


def test_default_derive_correlation_id_uses_first_non_empty_value() -> None:
    assert _default_derive_correlation_id(None, "  ", "task-1", "task-2") == "task-1"
    assert _default_derive_correlation_id(None, "") == ""


def test_fallback_federation_task_envelope_prompt_includes_derived_correlation() -> None:
    envelope = _FallbackFederationTaskEnvelope(
        task_id="t-1",
        source_system="alpha",
        source_agent="planner",
        target_system="beta",
        target_agent="executor",
        goal="deploy",
        context={"priority": "high"},
        inputs=["artifact"],
        meta={"correlation_id": "corr-42"},
    )

    prompt = envelope.to_prompt()
    assert "[FEDERATION TASK]" in prompt
    assert "correlation_id=corr-42" in prompt
    assert 'context={"priority": "high"}' in prompt


def test_fallback_action_feedback_prefers_explicit_correlation_id() -> None:
    feedback = _FallbackActionFeedback(
        feedback_id="f-1",
        action_name="lint",
        status="failed",
        summary="flake8 errors",
        correlation_id="corr-explicit",
        details={"count": 3},
    )

    prompt = feedback.to_prompt()
    assert "[ACTION FEEDBACK]" in prompt
    assert "correlation_id=corr-explicit" in prompt
    assert 'details={"count": 3}' in prompt


def test_parse_tool_call_handles_markdown_json_and_invalid_payloads() -> None:
    agent = SidarAgent.__new__(SidarAgent)

    parsed = agent._parse_tool_call('```json\n{"tool":"web_search","argument":"python"}\n```')
    assert parsed == {"tool": "web_search", "argument": "python"}

    missing_tool = agent._parse_tool_call('{"argument":"done"}')
    assert missing_tool == {"tool": "final_answer", "argument": "done"}

    fallback = agent._parse_tool_call("not-json")
    assert fallback == {"tool": "final_answer", "argument": "not-json"}


@pytest.mark.asyncio
async def test_poyraz_publish_social_supports_delimited_args_and_error_status() -> None:
    class _FakeSocial:
        async def publish_content(self, **kwargs):
            assert kwargs["platform"] == "instagram"
            assert kwargs["text"] == "launch"
            return False, "rate-limit"

    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent.social = _FakeSocial()

    out = await agent._tool_publish_social("instagram|||launch|||feed|||https://img|||https://link")
    assert out == "[SOCIAL:ERROR] platform=instagram reason=rate-limit"


@pytest.mark.asyncio
async def test_poyraz_search_docs_awaits_when_result_is_coroutine() -> None:
    class _FakeDocs:
        async def search(self, *_args, **_kwargs):
            return True, "doc-result"

    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent.docs = _FakeDocs()

    out = await agent._tool_search_docs("vector db")
    assert out == "doc-result"


@pytest.mark.asyncio
async def test_poyraz_persist_content_asset_serializes_created_asset() -> None:
    class _Asset:
        id = 7
        campaign_id = 12
        tenant_id = "tenant-a"
        asset_type = "campaign_copy"
        title = "Copy"
        channel = "multi"

    class _FakeDb:
        async def add_content_asset(self, **kwargs):
            assert kwargs["campaign_id"] == 12
            assert kwargs["metadata"] == {"lang": "tr"}
            return _Asset()

    agent = PoyrazAgent.__new__(PoyrazAgent)

    async def _ensure_db():
        return _FakeDb()

    agent._ensure_db = _ensure_db
    payload = await agent._persist_content_asset(
        campaign_id=12,
        tenant_id="tenant-a",
        asset_type="campaign_copy",
        title="Copy",
        content="Body",
        channel="multi",
        metadata={"lang": "tr"},
    )

    data = json.loads(payload)
    assert data["success"] is True
    assert data["asset"]["id"] == 7


@pytest.mark.asyncio
async def test_poyraz_ensure_db_returns_existing_instance_without_initializing() -> None:
    sentinel_db = object()
    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent._db = sentinel_db
    agent._db_lock = None

    result = await agent._ensure_db()
    assert result is sentinel_db


def test_graph_index_normalize_endpoint_path_filters_external_urls() -> None:
    assert GraphIndex._normalize_endpoint_path("https://example.com/api") is None
    assert GraphIndex._normalize_endpoint_path("https://localhost:8000/api") == "/api"
    assert GraphIndex._normalize_endpoint_path("/v1/health") == "/v1/health"


def test_graph_index_extract_script_endpoint_calls_deduplicates() -> None:
    graph = GraphIndex(Path("."))
    content = """
fetch('/api/tasks', { method: 'POST' });
fetch('/api/tasks', { method: 'POST' });
fetch('/api/tasks');
new WebSocket('ws://localhost:8000/ws/events');
"""
    calls = graph._extract_script_endpoint_calls(content)

    endpoints = {(item["method"], item["path"]) for item in calls}
    assert ("POST", "/api/tasks") in endpoints
    assert ("GET", "/api/tasks") in endpoints
    assert ("WS", "/ws/events") in endpoints


def test_graph_index_parse_python_source_extracts_imports_and_endpoint_links(tmp_path: Path) -> None:
    root = tmp_path
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    service = pkg / "service.py"
    service.write_text("def ping():\n    return 'ok'\n", encoding="utf-8")

    source_file = pkg / "api.py"
    source = """
from pkg import service

@router.get('/v1/health')
def health():
    return {'ok': True}

async def call_client(client):
    return client.post('/v1/tasks')
"""

    graph = GraphIndex(root)
    deps, endpoint_defs, endpoint_calls = graph._parse_python_source(source_file, source)

    assert service.resolve() in deps
    assert endpoint_defs[0]["endpoint_id"] == "endpoint:GET /v1/health"
    assert endpoint_calls[0]["endpoint_id"] == "endpoint:POST /v1/tasks"
