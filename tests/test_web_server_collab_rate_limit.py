"""web_server collaboration + rate-limit yardımcıları için ek birim testleri."""

from __future__ import annotations

import asyncio
import types

from tests.test_web_server import _get_web_server


class TestCollaborationHelpers:
    def test_collaboration_role_and_write_scope_resolution(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.cfg, "BASE_DIR", "/tmp/sidar-root", raising=False)

        assert ws._normalize_collaboration_role("  ADMIN  ") == "admin"
        assert ws._normalize_collaboration_role("") == "user"
        assert ws._collaboration_write_scopes_for_role("admin", "workspace:abc") == ["/tmp/sidar-root"]
        assert ws._collaboration_write_scopes_for_role("viewer", "workspace:abc") == []

    def test_collaboration_command_requires_write(self):
        ws = _get_web_server()

        assert ws._collaboration_command_requires_write("please write file app.py") is True
        assert ws._collaboration_command_requires_write("read_file|app.py") is False

    def test_append_room_telemetry_masks_sensitive_fields(self, monkeypatch):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")

        monkeypatch.setattr(ws, "_mask_collaboration_text", lambda text: f"masked:{text}")
        ws._append_room_telemetry(room, {"content": "email@site.com", "error": "token123"}, limit=2)

        assert room.telemetry[-1]["content"] == "masked:email@site.com"
        assert room.telemetry[-1]["error"] == "masked:token123"

    def test_build_room_message_and_stream_chunks(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws, "_mask_collaboration_text", lambda text: f"[safe]{text}")

        payload = ws._build_room_message(
            room_id="workspace:default",
            role="user",
            content="hello",
            author_name="Ali",
            author_id="u1",
            request_id="r1",
        )
        assert payload["content"] == "[safe]hello"
        assert payload["room_id"] == "workspace:default"
        assert payload["request_id"] == "r1"
        assert ws._iter_stream_chunks("abcdef", size=2) == ["ab", "cd", "ef"]


class TestEventDrivenHelpers:
    def test_build_event_driven_federation_spec_for_github(self):
        ws = _get_web_server()
        payload = {
            "action": "opened",
            "repository": {"full_name": "org/repo"},
            "pull_request": {
                "number": 42,
                "title": "Fix auth flow",
                "base": {"ref": "main"},
                "head": {"ref": "feature/auth"},
                "user": {"login": "dev"},
                "node_id": "PR_kw",
            },
        }

        spec = ws._build_event_driven_federation_spec("github", "pull_request", payload)
        assert spec is not None
        assert spec["workflow_type"] == "github_pull_request"
        assert spec["context"]["pr_number"] == "42"
        assert "GitHub PR #42" in spec["goal"]

    def test_build_swarm_goal_and_embed_payload(self):
        ws = _get_web_server()
        spec = {"context": {"repo": "org/repo"}, "inputs": ["x=1"]}
        coder_goal = ws._build_swarm_goal_for_role("base", "coder", spec)
        reviewer_goal = ws._build_swarm_goal_for_role("base", "reviewer", spec)

        assert "[EVENT_DRIVEN_SWARM:CODER]" in coder_goal
        assert "[EVENT_DRIVEN_SWARM:REVIEWER]" in reviewer_goal

        workflow = {
            "federation_task": {
                "task_id": "t1",
                "source_system": "github",
                "source_agent": "pull_request_webhook",
                "target_agent": "coder",
            },
            "federation_prompt": "prompt",
            "correlation_id": "cid-1",
        }
        merged = ws._embed_event_driven_federation_payload({"event": "opened"}, workflow)
        assert merged["kind"] == "federation_task"
        assert merged["task_id"] == "t1"
        assert merged["source_system"] == "github"
        assert merged["correlation_id"] == "cid-1"

    def test_trim_autonomy_text_and_audit_resource(self):
        ws = _get_web_server()
        assert ws._trim_autonomy_text("x" * 10, limit=5).endswith("…[truncated]")
        assert ws._build_audit_resource("github", "repo-1") == "github:repo-1"
        assert ws._build_audit_resource("", "x") == ""


class TestRateLimitHelpers:
    def test_get_client_ip_prefers_forwarded_for_trusted_proxy(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", ["10.0.0.1"], raising=False)
        request = types.SimpleNamespace(
            client=types.SimpleNamespace(host="10.0.0.1"),
            headers={"X-Forwarded-For": "203.0.113.10, 10.0.0.1"},
        )
        assert ws._get_client_ip(request) == "203.0.113.10"

    def test_ddos_rate_limit_middleware_blocks_when_limited(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", [], raising=False)

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        async def _limited(*_args, **_kwargs):
            return True

        async def _call_next(_request):
            return _Response({"ok": True}, status_code=200)

        monkeypatch.setattr(ws, "_redis_is_rate_limited", _limited)
        monkeypatch.setattr(ws, "JSONResponse", _Response)
        request = types.SimpleNamespace(
            url=types.SimpleNamespace(path="/api/private"),
            client=types.SimpleNamespace(host="127.0.0.1"),
            headers={},
        )

        response = asyncio.run(ws.ddos_rate_limit_middleware(request, _call_next))
        assert response.status_code == 429

    def test_rate_limit_middleware_respects_mutation_limit(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", [], raising=False)

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        calls = []

        async def _limited(namespace, *_args, **_kwargs):
            calls.append(namespace)
            return namespace == "mut"

        async def _call_next(_request):
            return _Response({"ok": True}, status_code=200)

        monkeypatch.setattr(ws, "_redis_is_rate_limited", _limited)
        monkeypatch.setattr(ws, "JSONResponse", _Response)
        request = types.SimpleNamespace(
            method="POST",
            url=types.SimpleNamespace(path="/api/resource"),
            client=types.SimpleNamespace(host="127.0.0.1"),
            headers={},
        )

        response = asyncio.run(ws.rate_limit_middleware(request, _call_next))
        assert response.status_code == 429
        assert "mut" in calls
