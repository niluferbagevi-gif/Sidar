import asyncio
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