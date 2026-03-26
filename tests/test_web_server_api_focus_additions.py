import asyncio
import builtins
import json
import sys
import types

import pytest

from tests.test_web_server_runtime import _FakeHTTPException, _load_web_server


class _ApiModulePatch:
    def __init__(self, name: str, module: types.ModuleType):
        self.name = name
        self.module = module
        self.previous = sys.modules.get(name)

    def __enter__(self):
        sys.modules[self.name] = self.module
        return self.module

    def __exit__(self, exc_type, exc, tb):
        if self.previous is None:
            sys.modules.pop(self.name, None)
        else:
            sys.modules[self.name] = self.previous
        return False


def test_hitl_broadcast_prunes_disconnected_websockets():
    mod = _load_web_server()

    class _AliveWebSocket:
        def __init__(self):
            self.payloads = []

        async def send_json(self, payload):
            self.payloads.append(payload)

    class _DeadWebSocket:
        async def send_json(self, _payload):
            raise RuntimeError("socket gone")

    alive = _AliveWebSocket()
    dead = _DeadWebSocket()
    mod._hitl_ws_clients.clear()
    mod._hitl_ws_clients.update({alive, dead})

    asyncio.run(mod._hitl_broadcast({"event": "approval_requested", "id": "req-1"}))

    assert alive.payloads == [{"event": "approval_requested", "id": "req-1"}]
    assert alive in mod._hitl_ws_clients
    assert dead not in mod._hitl_ws_clients


def test_websocket_chat_closes_when_auth_is_missing_or_invalid():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            return None if token == "bad-token" else types.SimpleNamespace(id="u1", username="alice")

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_DB(), set_active_user=lambda *_a, **_k: asyncio.sleep(0), __len__=lambda self: 1))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    class _WebSocket:
        def __init__(self, payloads):
            self.headers = {}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self._payloads = payloads
            self.closed = None

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, _payload):
            return None

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws_no_auth = _WebSocket([json.dumps({"action": "send", "message": "merhaba"})])
    asyncio.run(mod.websocket_chat(ws_no_auth))
    assert ws_no_auth.closed == (1008, "Authentication required")

    ws_missing_token = _WebSocket([json.dumps({"action": "auth", "token": "   "})])
    asyncio.run(mod.websocket_chat(ws_missing_token))
    assert ws_missing_token.closed == (1008, "Authentication token missing")

    ws_invalid_token = _WebSocket([json.dumps({"action": "auth", "token": "bad-token"})])
    asyncio.run(mod.websocket_chat(ws_invalid_token))
    assert ws_invalid_token.closed == (1008, "Invalid or expired token")


def test_entity_memory_api_caches_instance_and_surfaces_init_errors():
    mod = _load_web_server()
    mod._entity_memory_instance = None
    calls = {"initialize": 0, "upsert": [], "delete": []}

    class _EntityMemory:
        async def initialize(self):
            calls["initialize"] += 1

        async def upsert(self, **kwargs):
            calls["upsert"].append(kwargs)

        async def get_profile(self, user_id):
            return {"user_id": user_id, "memory": "ok"}

        async def delete(self, **kwargs):
            calls["delete"].append(kwargs)
            return True

    entity_mod = types.ModuleType("core.entity_memory")
    entity_mod.get_entity_memory = lambda _cfg: _EntityMemory()

    with _ApiModulePatch("core.entity_memory", entity_mod):
        upsert_resp = asyncio.run(
            mod.api_entity_upsert(mod._EntityUpsertRequest(user_id="u1", key="project", value="sidar", ttl_days=7))
        )
        profile_resp = asyncio.run(mod.api_entity_get_profile("u1"))
        delete_resp = asyncio.run(mod.api_entity_delete("u1", "project"))

    assert upsert_resp.content == {"success": True}
    assert profile_resp.content == {"success": True, "user_id": "u1", "profile": {"user_id": "u1", "memory": "ok"}}
    assert delete_resp.content == {"success": True}
    assert calls["initialize"] == 1
    assert calls["upsert"] == [{"user_id": "u1", "key": "project", "value": "sidar", "ttl_days": 7}]
    assert calls["delete"] == [{"user_id": "u1", "key": "project"}]

    mod._entity_memory_instance = None

    class _BrokenEntityMemory:
        async def initialize(self):
            raise RuntimeError("entity init failed")

    entity_mod.get_entity_memory = lambda _cfg: _BrokenEntityMemory()
    with _ApiModulePatch("core.entity_memory", entity_mod):
        with pytest.raises(_FakeHTTPException) as excinfo:
            asyncio.run(mod.api_entity_get_profile("u2"))

    assert excinfo.value.status_code == 501
    assert "EntityMemory başlatılamadı" in str(excinfo.value.detail)


def test_feedback_store_api_caches_instance_and_surfaces_init_errors():
    mod = _load_web_server()
    mod._feedback_store_instance = None
    calls = {"initialize": 0, "record": [], "stats": 0}

    class _FeedbackStore:
        async def initialize(self):
            calls["initialize"] += 1

        async def record(self, **kwargs):
            calls["record"].append(kwargs)

        async def stats(self):
            calls["stats"] += 1
            return {"count": 1, "avg_rating": 5.0}

    feedback_mod = types.ModuleType("core.active_learning")
    feedback_mod.get_feedback_store = lambda _cfg: _FeedbackStore()

    with _ApiModulePatch("core.active_learning", feedback_mod):
        record_resp = asyncio.run(
            mod.api_feedback_record(
                mod._FeedbackRecordRequest(
                    user_id="u1",
                    prompt="Merhaba",
                    response="Selam",
                    rating=5,
                    note=None,
                )
            )
        )
        stats_resp = asyncio.run(mod.api_feedback_stats())

    assert record_resp.content == {"success": True}
    assert stats_resp.content == {"success": True, "stats": {"count": 1, "avg_rating": 5.0}}
    assert calls["initialize"] == 1
    assert calls["record"] == [{"user_id": "u1", "prompt": "Merhaba", "response": "Selam", "rating": 5, "note": ""}]
    assert calls["stats"] == 1

    mod._feedback_store_instance = None

    class _BrokenFeedbackStore:
        async def initialize(self):
            raise RuntimeError("feedback init failed")

    feedback_mod.get_feedback_store = lambda _cfg: _BrokenFeedbackStore()
    with _ApiModulePatch("core.active_learning", feedback_mod):
        with pytest.raises(_FakeHTTPException) as excinfo:
            asyncio.run(mod.api_feedback_stats())

    assert excinfo.value.status_code == 501
    assert "FeedbackStore başlatılamadı" in str(excinfo.value.detail)


def test_feedback_record_api_surfaces_feedback_store_initialization_errors():
    mod = _load_web_server()
    mod._feedback_store_instance = None

    class _BrokenFeedbackStore:
        async def initialize(self):
            raise RuntimeError("feedback db unavailable")

    feedback_mod = types.ModuleType("core.active_learning")
    feedback_mod.get_feedback_store = lambda _cfg: _BrokenFeedbackStore()

    with _ApiModulePatch("core.active_learning", feedback_mod):
        with pytest.raises(_FakeHTTPException) as excinfo:
            asyncio.run(
                mod.api_feedback_record(
                    mod._FeedbackRecordRequest(
                        user_id="u1",
                        prompt="Merhaba",
                        response="Selam",
                        rating=4,
                        note="",
                    )
                )
            )

    assert excinfo.value.status_code == 501
    assert "FeedbackStore başlatılamadı" in str(excinfo.value.detail)


def test_slack_jira_and_teams_api_wrappers_cover_success_unavailable_and_backend_errors():
    mod = _load_web_server()
    mod._slack_mgr_instance = None
    mod._jira_mgr_instance = None
    mod._teams_mgr_instance = None

    class _SlackManager:
        def __init__(self, *_a, **_k):
            self.available = True
            self.fail_send = False
            self.fail_list = False
            self.initialized = 0

        async def initialize(self):
            self.initialized += 1

        def is_available(self):
            return self.available

        async def send_message(self, **_kwargs):
            if self.fail_send:
                return False, "slack down"
            return True, None

        async def list_channels(self):
            if self.fail_list:
                return False, [], "channels unavailable"
            return True, [{"id": "C1", "name": "general"}], None

    class _JiraManager:
        def __init__(self, *_a, **_k):
            self.available = True
            self.fail_create = False
            self.fail_search = False

        def is_available(self):
            return self.available

        async def create_issue(self, **_kwargs):
            if self.fail_create:
                return False, None, "jira create failed"
            return True, {"key": "SID-1"}, None

        async def search_issues(self, **_kwargs):
            if self.fail_search:
                return False, [], "jira search failed"
            return True, [{"key": "SID-1"}], None

    class _TeamsManager:
        def __init__(self, *_a, **_k):
            self.available = True
            self.fail_send = False

        def is_available(self):
            return self.available

        async def send_message(self, **_kwargs):
            if self.fail_send:
                return False, "teams down"
            return True, None

    slack_mod = types.ModuleType("managers.slack_manager")
    slack_mod.SlackManager = _SlackManager
    jira_mod = types.ModuleType("managers.jira_manager")
    jira_mod.JiraManager = _JiraManager
    teams_mod = types.ModuleType("managers.teams_manager")
    teams_mod.TeamsManager = _TeamsManager

    with _ApiModulePatch("managers.slack_manager", slack_mod), _ApiModulePatch("managers.jira_manager", jira_mod), _ApiModulePatch("managers.teams_manager", teams_mod):
        slack_send = asyncio.run(mod.api_slack_send(mod._SlackSendRequest(text="Deploy tamam", channel="#ops", thread_ts=None)))
        slack_channels = asyncio.run(mod.api_slack_channels())
        jira_issue = asyncio.run(
            mod.api_jira_create_issue(
                mod._JiraCreateRequest(project_key="SID", summary="Broken edge case", description=None, issue_type="Task", priority=None)
            )
        )
        jira_search = asyncio.run(mod.api_jira_search_issues(jql="project=SID", max_results=10))
        teams_send = asyncio.run(mod.api_teams_send(mod._TeamsSendRequest(text="Onay bekliyor", title=None)))

        assert slack_send.content == {"success": True}
        assert slack_channels.content == {"success": True, "channels": [{"id": "C1", "name": "general"}]}
        assert jira_issue.content == {"success": True, "issue": {"key": "SID-1"}}
        assert jira_search.content == {"success": True, "issues": [{"key": "SID-1"}], "total": 1}
        assert teams_send.content == {"success": True}
        assert mod._slack_mgr_instance.initialized == 1

        mod._slack_mgr_instance.available = False
        with pytest.raises(_FakeHTTPException) as slack_unavailable:
            asyncio.run(mod.api_slack_send(mod._SlackSendRequest(text="x", channel=None, thread_ts=None)))
        assert slack_unavailable.value.status_code == 503
        with pytest.raises(_FakeHTTPException) as slack_channels_unavailable:
            asyncio.run(mod.api_slack_channels())
        assert slack_channels_unavailable.value.status_code == 503

        mod._slack_mgr_instance.available = True
        mod._slack_mgr_instance.fail_send = True
        with pytest.raises(_FakeHTTPException) as slack_backend_error:
            asyncio.run(mod.api_slack_send(mod._SlackSendRequest(text="x", channel=None, thread_ts=None)))
        assert slack_backend_error.value.status_code == 502

        mod._slack_mgr_instance.fail_send = False
        mod._slack_mgr_instance.fail_list = True
        with pytest.raises(_FakeHTTPException) as slack_list_error:
            asyncio.run(mod.api_slack_channels())
        assert slack_list_error.value.status_code == 502

        mod._jira_mgr_instance.available = False
        with pytest.raises(_FakeHTTPException) as jira_unavailable:
            asyncio.run(
                mod.api_jira_create_issue(
                    mod._JiraCreateRequest(project_key="SID", summary="Broken edge case", description=None, issue_type="Task", priority=None)
                )
            )
        assert jira_unavailable.value.status_code == 503
        with pytest.raises(_FakeHTTPException) as jira_search_unavailable:
            asyncio.run(mod.api_jira_search_issues(jql="project=SID", max_results=10))
        assert jira_search_unavailable.value.status_code == 503

        mod._jira_mgr_instance.available = True
        mod._jira_mgr_instance.fail_create = True
        with pytest.raises(_FakeHTTPException) as jira_create_error:
            asyncio.run(
                mod.api_jira_create_issue(
                    mod._JiraCreateRequest(project_key="SID", summary="Broken edge case", description=None, issue_type="Task", priority=None)
                )
            )
        assert jira_create_error.value.status_code == 502

        mod._jira_mgr_instance.fail_create = False
        mod._jira_mgr_instance.fail_search = True
        with pytest.raises(_FakeHTTPException) as jira_search_error:
            asyncio.run(mod.api_jira_search_issues(jql="project=SID", max_results=10))
        assert jira_search_error.value.status_code == 502

        mod._teams_mgr_instance.available = False
        with pytest.raises(_FakeHTTPException) as teams_unavailable:
            asyncio.run(mod.api_teams_send(mod._TeamsSendRequest(text="x", title=None)))
        assert teams_unavailable.value.status_code == 503

        mod._teams_mgr_instance.available = True
        mod._teams_mgr_instance.fail_send = True
        with pytest.raises(_FakeHTTPException) as teams_backend_error:
            asyncio.run(mod.api_teams_send(mod._TeamsSendRequest(text="x", title="Alert")))
        assert teams_backend_error.value.status_code == 502


def test_access_audit_logging_handles_empty_resource_missing_loop_and_persist_failures(monkeypatch):
    mod = _load_web_server()

    assert mod._build_audit_resource("", "abc") == ""

    debug_logs = []
    monkeypatch.setattr(mod.logger, "debug", lambda msg, *args: debug_logs.append(msg % args if args else msg))

    def _no_loop():
        raise RuntimeError("event loop yok")

    monkeypatch.setattr(mod.asyncio, "get_running_loop", _no_loop)
    mod._schedule_access_audit_log(
        user=types.SimpleNamespace(id="u1", tenant_id="t1"),
        resource_type="github",
        action="read",
        resource_id="repo-1",
        ip_address="127.0.0.1",
        allowed=True,
    )
    assert any("event loop yok" in msg for msg in debug_logs)

    captured = {}

    class _Loop:
        def create_task(self, coro):
            captured["coro"] = coro
            return types.SimpleNamespace()

    async def _bad_record(**_kwargs):
        raise RuntimeError("audit persist boom")

    async def _get_agent():
        return types.SimpleNamespace(memory=types.SimpleNamespace(db=types.SimpleNamespace(record_audit_log=_bad_record)))

    monkeypatch.setattr(mod.asyncio, "get_running_loop", lambda: _Loop())
    monkeypatch.setattr(mod, "get_agent", _get_agent)

    mod._schedule_access_audit_log(
        user=types.SimpleNamespace(id="u1", tenant_id="t1"),
        resource_type="rag",
        action="write",
        resource_id="doc-1",
        ip_address="127.0.0.1",
        allowed=False,
    )
    asyncio.run(captured["coro"])
    assert any("audit persist boom" in msg for msg in debug_logs)


def test_hitl_api_wrappers_cover_pending_create_success_and_missing_request():
    mod = _load_web_server()
    added = []
    notified = []

    class _PendingRequest:
        def __init__(self, request_id):
            self.request_id = request_id

        def to_dict(self):
            return {"request_id": self.request_id}

    class _Store:
        async def pending(self):
            return [_PendingRequest("req-1")]

        async def add(self, req):
            added.append(req)

    store = _Store()

    class _Gate:
        timeout = 30

        async def respond(self, request_id, **_kwargs):
            if request_id == "missing":
                return None
            return types.SimpleNamespace(request_id=request_id, decision=types.SimpleNamespace(value="approved"))

    hitl_mod = types.ModuleType("core.hitl")
    hitl_mod.get_hitl_store = lambda: store
    hitl_mod.get_hitl_gate = lambda: _Gate()
    hitl_mod.HITLRequest = lambda **kwargs: types.SimpleNamespace(**kwargs)

    async def _notify(req):
        notified.append(req.request_id)

    hitl_mod.notify = _notify
    mod.get_hitl_store = hitl_mod.get_hitl_store
    mod.get_hitl_gate = hitl_mod.get_hitl_gate

    with _ApiModulePatch("core.hitl", hitl_mod):
        pending = asyncio.run(mod.hitl_pending(user=types.SimpleNamespace(username="alice")))
        created = asyncio.run(
            mod.hitl_create_request(
                {"action": "approve", "description": "Deploy onayı", "payload": {"id": 7}},
                user=types.SimpleNamespace(username="alice"),
            )
        )
        decided = asyncio.run(
            mod.hitl_respond(
                "req-1",
                mod._HITLRespondRequest(approved=True, decided_by="admin", rejection_reason=""),
                user=types.SimpleNamespace(username="alice"),
            )
        )

        with pytest.raises(_FakeHTTPException) as missing:
            asyncio.run(
                mod.hitl_respond(
                    "missing",
                    mod._HITLRespondRequest(approved=False, decided_by="admin", rejection_reason="hayır"),
                    user=types.SimpleNamespace(username="alice"),
                )
            )

    assert pending.content == {"pending": [{"request_id": "req-1"}], "count": 1}
    assert created.content["request_id"]
    assert "expires_at" in created.content
    assert len(added) == 1
    assert notified == [added[0].request_id]
    assert decided.content == {"request_id": "req-1", "decision": "approved"}
    assert missing.value.status_code == 404


def test_vision_endpoints_raise_501_when_core_vision_import_fails():
    mod = _load_web_server()
    real_import = builtins.__import__

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.vision":
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    try:
        builtins.__import__ = _blocked_import
        with pytest.raises(_FakeHTTPException) as analyze_exc:
            asyncio.run(
                mod.api_vision_analyze(
                    mod._VisionAnalyzeRequest(image_base64="ZmFrZQ==", mime_type="image/png", analysis_type="ui", prompt=None)
                )
            )
        with pytest.raises(_FakeHTTPException) as mockup_exc:
            asyncio.run(
                mod.api_vision_mockup(
                    mod._VisionMockupRequest(image_base64="ZmFrZQ==", mime_type="image/png", framework="html", prompt=None)
                )
            )
    finally:
        builtins.__import__ = real_import

    assert analyze_exc.value.status_code == 501
    assert mockup_exc.value.status_code == 501