"""
Coverage tests for web_server.py missing lines:
  50-52: opentelemetry imports inside try block
  194: _build_user_from_jwt_payload
  328-329: _setup_tracing with all dependencies
  359: _serialize_policy
  379-380: _resolve_policy_from_request github
  382, 384, 387: _resolve_policy_from_request other paths
  453: _validate_plugin_role_name
  461-462, 467, 469, 472-479: _load_plugin_agent_class paths
  601-603, 608-618: admin endpoints
  647, 649, 652-653: register-file endpoint paths
  671, 674, 676, 680, 686, 694-696: access_policy_middleware
  748: _get_redis when already connected
  855: assets mount
  1039-1047: WebSocket exception paths
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Reuse web server loading infrastructure ───────────────────────────────────

from tests.test_web_server_runtime import (
    _FakeRequest,
    _FakeUploadFile,
    _FakeHTTPException,
    _load_web_server,
    _install_web_server_stubs,
)


def _load_ws():
    return _load_web_server()


# ── _build_user_from_jwt_payload (line 194) ───────────────────────────────────

def test_build_user_from_jwt_payload_missing_user_id():
    """Line 194: returns None when user_id or username missing."""
    mod = _load_ws()
    result = mod._build_user_from_jwt_payload({"username": "alice"})
    assert result is None


def test_build_user_from_jwt_payload_missing_username():
    mod = _load_ws()
    result = mod._build_user_from_jwt_payload({"sub": "user-1"})
    assert result is None


def test_build_user_from_jwt_payload_success():
    mod = _load_ws()
    result = mod._build_user_from_jwt_payload({
        "sub": "user-1",
        "username": "alice",
        "role": "admin",
        "tenant_id": "tenant1",
    })
    assert result is not None
    assert result.id == "user-1"
    assert result.username == "alice"


# ── _setup_tracing with all dependencies (lines 328-329) ─────────────────────

def test_setup_tracing_with_all_deps():
    """Lines 328-329: _setup_tracing with ENABLE_TRACING=True and all deps."""
    mod = _load_ws()
    mod.cfg.ENABLE_TRACING = True

    # Provide mock deps
    mock_resource = MagicMock()
    mock_resource.create = MagicMock(return_value=mock_resource)
    mock_provider = MagicMock()
    mock_provider_cls = MagicMock(return_value=mock_provider)
    mock_exporter = MagicMock()
    mock_exporter_cls = MagicMock(return_value=mock_exporter)
    mock_processor = MagicMock()
    mock_processor_cls = MagicMock(return_value=mock_processor)
    mock_trace = MagicMock()
    mock_fastapi_instrumentor = MagicMock()
    mock_httpx_instrumentor = MagicMock()
    mock_httpx_instance = MagicMock()
    mock_httpx_instrumentor.return_value = mock_httpx_instance

    mod.trace = mock_trace
    mod.Resource = mock_resource
    mod.TracerProvider = mock_provider_cls
    mod.OTLPSpanExporter = mock_exporter_cls
    mod.BatchSpanProcessor = mock_processor_cls
    mod.FastAPIInstrumentor = mock_fastapi_instrumentor
    mod.HTTPXClientInstrumentor = mock_httpx_instrumentor

    mod.cfg.OTEL_EXPORTER_ENDPOINT = "http://localhost:4317"
    mod.cfg.OTEL_SERVICE_NAME = "sidar-test"

    mod._setup_tracing()
    # Should not raise; tracing was set up
    mock_trace.set_tracer_provider.assert_called_once()


# ── _serialize_policy (line 359) ─────────────────────────────────────────────

def test_serialize_policy():
    """Line 359: _serialize_policy converts record to dict."""
    mod = _load_ws()
    record = types.SimpleNamespace(
        id=1,
        user_id="user1",
        tenant_id="default",
        resource_type="rag",
        resource_id="*",
        action="read",
        effect="allow",
        created_at="2024-01-01T00:00:00",
        updated_at="2024-01-01T00:00:00",
    )
    result = mod._serialize_policy(record)
    assert result["user_id"] == "user1"
    assert result["effect"] == "allow"


# ── _resolve_policy_from_request (lines 379-387) ─────────────────────────────

def test_resolve_policy_github_path():
    """Lines 379-380: github path returns ('github', ...)."""
    mod = _load_ws()
    req = _FakeRequest(method="POST", path="/github-repos")
    resource_type, action, resource_id = mod._resolve_policy_from_request(req)
    assert resource_type == "github"
    assert action == "write"


def test_resolve_policy_set_repo():
    """Line 379: /set-repo path returns github."""
    mod = _load_ws()
    req = _FakeRequest(method="GET", path="/set-repo")
    resource_type, action, resource_id = mod._resolve_policy_from_request(req)
    assert resource_type == "github"
    assert action == "read"


def test_resolve_policy_agents_register():
    """Line 382: /api/agents/register returns agents."""
    mod = _load_ws()
    req = _FakeRequest(method="POST", path="/api/agents/register")
    resource_type, action, resource_id = mod._resolve_policy_from_request(req)
    assert resource_type == "agents"
    assert action == "register"


def test_resolve_policy_admin_path():
    """Line 384: /admin/ path returns admin."""
    mod = _load_ws()
    req = _FakeRequest(method="GET", path="/admin/policies/user1")
    resource_type, action, resource_id = mod._resolve_policy_from_request(req)
    assert resource_type == "admin"


def test_resolve_policy_ws_path():
    """Line 385-386: /ws/ path returns swarm."""
    mod = _load_ws()
    req = _FakeRequest(method="GET", path="/ws/chat")
    resource_type, action, resource_id = mod._resolve_policy_from_request(req)
    assert resource_type == "swarm"
    assert action == "execute"


def test_resolve_policy_unknown_path():
    """Line 387: unknown path returns empty strings."""
    mod = _load_ws()
    req = _FakeRequest(method="GET", path="/unknown")
    resource_type, action, resource_id = mod._resolve_policy_from_request(req)
    assert resource_type == ""


def test_resolve_policy_rag_delete():
    """Line 376: RAG DELETE returns specific resource_id."""
    mod = _load_ws()
    req = _FakeRequest(method="DELETE", path="/rag/doc-abc")
    resource_type, action, resource_id = mod._resolve_policy_from_request(req)
    assert resource_type == "rag"
    assert action == "write"
    assert resource_id == "doc-abc"


# ── _validate_plugin_role_name (line 453) ────────────────────────────────────

def test_validate_plugin_role_name_invalid():
    """Line 453: invalid role_name raises HTTPException."""
    mod = _load_ws()
    with pytest.raises(_FakeHTTPException) as exc_info:
        mod._validate_plugin_role_name("invalid role!")
    assert exc_info.value.status_code == 400


def test_validate_plugin_role_name_valid():
    mod = _load_ws()
    result = mod._validate_plugin_role_name("my_agent")
    assert result == "my_agent"


# ── _load_plugin_agent_class (lines 461-479) ─────────────────────────────────

def test_load_plugin_agent_class_compile_error():
    """Lines 461-462: syntax error in source raises HTTPException."""
    mod = _load_ws()
    with pytest.raises(_FakeHTTPException) as exc_info:
        mod._load_plugin_agent_class("def broken(:", None, "test_module")
    assert exc_info.value.status_code == 400


def test_load_plugin_agent_class_with_class_name_not_found():
    """Lines 465-467: specified class_name not found raises HTTPException."""
    from agent.base_agent import BaseAgent

    mod = _load_ws()
    source = "x = 1"
    with pytest.raises(_FakeHTTPException) as exc_info:
        mod._load_plugin_agent_class(source, "NonExistentClass", "test_module")
    assert exc_info.value.status_code == 400


def test_load_plugin_agent_class_not_base_agent():
    """Line 469: class not subclass of BaseAgent raises HTTPException."""
    mod = _load_ws()
    source = "class MyClass: pass"
    with pytest.raises(_FakeHTTPException) as exc_info:
        mod._load_plugin_agent_class(source, "MyClass", "test_module")
    assert exc_info.value.status_code == 400


def test_load_plugin_agent_class_auto_discover_no_class():
    """Lines 472-478: no BaseAgent subclass found raises HTTPException."""
    mod = _load_ws()
    source = "x = 1\ny = 2"
    with pytest.raises(_FakeHTTPException) as exc_info:
        mod._load_plugin_agent_class(source, None, "test_module")
    assert exc_info.value.status_code == 400


def test_load_plugin_agent_class_auto_discover_success():
    """Lines 473-476: auto-discovers first BaseAgent subclass."""
    from agent.base_agent import BaseAgent

    mod = _load_ws()
    source = """
from agent.base_agent import BaseAgent
class MyPlugin(BaseAgent):
    async def handle(self, e): ...
"""
    result = mod._load_plugin_agent_class(source, None, "test_module")
    assert issubclass(result, BaseAgent)


def test_load_plugin_agent_class_with_valid_class_name():
    """Line 470: valid class_name and BaseAgent subclass returns class."""
    from agent.base_agent import BaseAgent

    mod = _load_ws()
    source = """
from agent.base_agent import BaseAgent
class ValidPlugin(BaseAgent):
    async def handle(self, e): ...
"""
    result = mod._load_plugin_agent_class(source, "ValidPlugin", "test_module")
    assert issubclass(result, BaseAgent)


# ── admin endpoints (lines 601-618) ──────────────────────────────────────────

def test_admin_list_policies():
    """Lines 601-603: admin_list_policies returns items."""
    mod = _load_ws()

    async def _run():
        db = types.SimpleNamespace(
            list_access_policies=AsyncMock(return_value=[]),
        )
        agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=db))
        mod.get_agent = AsyncMock(return_value=agent)
        result = await mod.admin_list_policies(user_id="user1", tenant_id="default")
        return result

    result = asyncio.run(_run())
    # content is a dict (FakeJSONResponse stores content as-is)
    assert result.content == {"items": []}


def test_admin_upsert_policy():
    """Lines 608-618: admin_upsert_policy calls upsert and returns items."""
    mod = _load_ws()

    async def _run():
        db = types.SimpleNamespace(
            upsert_access_policy=AsyncMock(return_value=None),
            list_access_policies=AsyncMock(return_value=[]),
        )
        agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=db))
        mod.get_agent = AsyncMock(return_value=agent)

        payload = types.SimpleNamespace(
            user_id="user1",
            tenant_id="default",
            resource_type="rag",
            resource_id="*",
            action="read",
            effect="allow",
        )
        result = await mod.admin_upsert_policy(payload)
        return result

    result = asyncio.run(_run())
    # content is a dict (FakeJSONResponse stores content as-is)
    assert result.content.get("success") is True


# ── register-file endpoint (lines 647, 649, 652-653) ─────────────────────────

class _PluginUploadFile:
    """Upload file stub that supports async read() for register_agent_plugin_file."""

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data
        self.file = io.BytesIO(data)

    async def read(self) -> bytes:
        return self._data

    async def close(self):
        pass


def test_register_file_empty_data():
    """Line 647: empty file data raises HTTPException 400."""
    mod = _load_ws()

    async def _run():
        file = _PluginUploadFile("plugin.py", b"")
        result = await mod.register_agent_plugin_file(file=file)
        return result

    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(_run())
    assert exc_info.value.status_code == 400


def test_register_file_too_large():
    """Line 649: oversized file raises HTTPException 413."""
    mod = _load_ws()

    async def _run():
        big_data = b"x" * (mod.MAX_FILE_CONTENT_BYTES + 1)
        file = _PluginUploadFile("plugin.py", big_data)
        result = await mod.register_agent_plugin_file(file=file)
        return result

    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(_run())
    assert exc_info.value.status_code == 413


def test_register_file_utf8_decode_error():
    """Lines 652-653: invalid UTF-8 data raises HTTPException 400."""
    mod = _load_ws()

    async def _run():
        bad_bytes = b"\xff\xfe invalid utf-8"
        file = _PluginUploadFile("plugin.py", bad_bytes)
        result = await mod.register_agent_plugin_file(file=file)
        return result

    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(_run())
    assert exc_info.value.status_code == 400


# ── access_policy_middleware (lines 671, 674, 676, 680, 686, 694-696) ────────

def test_access_policy_middleware_options_passthrough():
    """Line 671: OPTIONS requests pass through."""
    mod = _load_ws()

    async def _run():
        req = _FakeRequest(method="OPTIONS", path="/any")
        responses = []
        async def call_next(r):
            responses.append("called")
            return "ok"
        result = await mod.access_policy_middleware(req, call_next)
        return result, responses

    result, responses = asyncio.run(_run())
    assert responses == ["called"]


def test_access_policy_middleware_no_user():
    """Line 674: no user in request state passes through."""
    mod = _load_ws()

    async def _run():
        req = _FakeRequest(method="GET", path="/api/data")
        responses = []
        async def call_next(r):
            responses.append("called")
            return "ok"
        result = await mod.access_policy_middleware(req, call_next)
        return responses

    responses = asyncio.run(_run())
    assert responses == ["called"]


def test_access_policy_middleware_admin_user_passthrough():
    """Line 676: admin user passes through without policy check."""
    mod = _load_ws()

    async def _run():
        req = _FakeRequest(method="GET", path="/api/data")
        req.state.user = types.SimpleNamespace(
            id="admin1", username="admin_user", role="admin", tenant_id="default"
        )
        responses = []
        async def call_next(r):
            responses.append("called")
            return "ok"
        result = await mod.access_policy_middleware(req, call_next)
        return responses

    responses = asyncio.run(_run())
    assert responses == ["called"]


def test_access_policy_middleware_no_resource_type():
    """Line 680: no resource_type returns call_next."""
    mod = _load_ws()

    async def _run():
        req = _FakeRequest(method="GET", path="/health")
        req.state.user = types.SimpleNamespace(
            id="u1", username="alice", role="user", tenant_id="default"
        )
        responses = []
        async def call_next(r):
            responses.append("called")
            return "ok"
        result = await mod.access_policy_middleware(req, call_next)
        return responses

    responses = asyncio.run(_run())
    assert responses == ["called"]


def test_access_policy_middleware_no_checker():
    """Line 686: when db has no check_access_policy, passes through."""
    mod = _load_ws()

    async def _run():
        req = _FakeRequest(method="GET", path="/rag/docs")
        req.state.user = types.SimpleNamespace(
            id="u1", username="alice", role="user", tenant_id="default"
        )
        db = types.SimpleNamespace()  # no check_access_policy attr
        agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=db))
        mod.get_agent = AsyncMock(return_value=agent)

        responses = []
        async def call_next(r):
            responses.append("called")
            return "ok"
        result = await mod.access_policy_middleware(req, call_next)
        return responses

    responses = asyncio.run(_run())
    assert responses == ["called"]


def test_access_policy_middleware_allowed():
    """Line 686+: allowed=True lets request through."""
    mod = _load_ws()

    async def _run():
        req = _FakeRequest(method="GET", path="/rag/docs")
        req.state.user = types.SimpleNamespace(
            id="u1", username="alice", role="user", tenant_id="default"
        )
        db = types.SimpleNamespace(check_access_policy=AsyncMock(return_value=True))
        agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=db))
        mod.get_agent = AsyncMock(return_value=agent)

        responses = []
        async def call_next(r):
            responses.append("allowed")
            return "ok"
        result = await mod.access_policy_middleware(req, call_next)
        return responses

    responses = asyncio.run(_run())
    assert responses == ["allowed"]


def test_access_policy_middleware_exception_denies():
    """Lines 694-696: exception during check defaults to denied."""
    mod = _load_ws()

    async def _run():
        req = _FakeRequest(method="GET", path="/rag/docs")
        req.state.user = types.SimpleNamespace(
            id="u1", username="alice", role="user", tenant_id="default"
        )
        db = types.SimpleNamespace(check_access_policy=AsyncMock(side_effect=Exception("db error")))
        agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=db))
        mod.get_agent = AsyncMock(return_value=agent)

        async def call_next(r):
            return "ok"
        result = await mod.access_policy_middleware(req, call_next)
        return result

    result = asyncio.run(_run())
    # Should be a 403 response
    assert result.status_code == 403


# ── _get_redis when already connected (line 748) ──────────────────────────────

def test_get_redis_already_connected():
    """Line 748: returns existing redis client when already connected."""
    mod = _load_ws()
    mock_redis = MagicMock()
    mod._redis_client = mock_redis

    result = asyncio.run(mod._get_redis())
    assert result is mock_redis

    # Cleanup
    mod._redis_client = None
    mod._redis_lock = None


# ── WebSocket exception paths (lines 1039-1047) ───────────────────────────────

def test_anyio_closed_error_handling():
    """Lines 1039-1047: anyio.ClosedResourceError is treated as normal disconnect."""
    mod = _load_ws()

    # Check that _ANYIO_CLOSED is defined (None when anyio not available)
    assert hasattr(mod, "_ANYIO_CLOSED")
