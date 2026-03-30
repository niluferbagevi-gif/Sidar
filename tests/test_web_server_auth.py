"""web_server auth/policy yardımcıları için odaklı birim testleri."""

from __future__ import annotations

import types

import pytest

from tests.test_web_server import _get_web_server


class TestWebServerAuthHelpers:
    def test_basic_auth_middleware_skips_auth_for_open_paths(self):
        ws = _get_web_server()

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/health"),
            headers={},
            state=types.SimpleNamespace(),
        )

        async def _call_next(_request):
            return _Response({"ok": True}, status_code=200)

        result = __import__("asyncio").run(ws.basic_auth_middleware(request, _call_next))
        assert result.status_code == 200

    def test_basic_auth_middleware_rejects_missing_bearer_header(self, monkeypatch):
        ws = _get_web_server()

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        monkeypatch.setattr(ws, "JSONResponse", _Response)
        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/api/private"),
            headers={},
            state=types.SimpleNamespace(),
        )

        async def _call_next(_request):
            return _Response({"ok": True}, status_code=200)

        result = __import__("asyncio").run(ws.basic_auth_middleware(request, _call_next))
        assert result.status_code == 401
        assert "Yetkisiz" in str(result.content.get("error", ""))

    def test_basic_auth_middleware_rejects_empty_bearer_token(self, monkeypatch):
        ws = _get_web_server()

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        monkeypatch.setattr(ws, "JSONResponse", _Response)
        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/api/private"),
            headers={"Authorization": "Bearer   "},
            state=types.SimpleNamespace(),
        )

        async def _call_next(_request):
            return _Response({"ok": True}, status_code=200)

        result = __import__("asyncio").run(ws.basic_auth_middleware(request, _call_next))
        assert result.status_code == 401
        assert "Geçersiz token" in str(result.content.get("error", ""))

    def test_basic_auth_middleware_rejects_when_resolved_user_missing(self, monkeypatch):
        ws = _get_web_server()

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        async def _mock_resolve_user(*_args, **_kwargs):
            return None

        monkeypatch.setattr(ws, "JSONResponse", _Response)
        monkeypatch.setattr(ws, "_resolve_user_from_token", _mock_resolve_user)
        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/api/private"),
            headers={"Authorization": "Bearer valid-but-expired"},
            state=types.SimpleNamespace(),
        )

        async def _call_next(_request):
            return _Response({"ok": True}, status_code=200)

        result = __import__("asyncio").run(ws.basic_auth_middleware(request, _call_next))
        assert result.status_code == 401
        assert "süresi dolmuş" in str(result.content.get("error", ""))

    def test_basic_auth_middleware_sets_user_and_calls_next_on_valid_token(self, monkeypatch):
        ws = _get_web_server()

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        user = types.SimpleNamespace(id="u1", username="ali")
        active_user_calls = []
        metrics_calls = []
        reset_calls = []

        async def _resolve_user(_agent, _token):
            return user

        async def _set_active_user(user_id, username):
            active_user_calls.append((user_id, username))

        async def _call_next(_request):
            return _Response({"ok": True}, status_code=200)

        fake_agent = types.SimpleNamespace(memory=types.SimpleNamespace(set_active_user=_set_active_user))

        async def _get_agent():
            return fake_agent

        monkeypatch.setattr(ws, "_resolve_user_from_token", _resolve_user)
        monkeypatch.setattr(ws, "get_agent", _get_agent)
        monkeypatch.setattr(ws, "set_current_metrics_user_id", lambda user_id: metrics_calls.append(user_id) or "tok")
        monkeypatch.setattr(ws, "reset_current_metrics_user_id", lambda token: reset_calls.append(token))
        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/api/private"),
            headers={"Authorization": "Bearer live-token"},
            state=types.SimpleNamespace(),
        )

        result = __import__("asyncio").run(ws.basic_auth_middleware(request, _call_next))

        assert result.status_code == 200
        assert request.state.user is user
        assert active_user_calls == [("u1", "ali")]
        assert metrics_calls == ["u1"]
        assert reset_calls == ["tok"]

    def test_get_request_user_raises_when_missing(self):
        ws = _get_web_server()
        request = types.SimpleNamespace(state=types.SimpleNamespace())

        with pytest.raises(ws.HTTPException) as exc_info:
            ws._get_request_user(request)

        assert exc_info.value.status_code == 401

    def test_require_admin_user_allows_default_admin_username(self):
        ws = _get_web_server()
        user = types.SimpleNamespace(role="user", username="default_admin")

        result = ws._require_admin_user(user)

        assert result is user

    def test_require_admin_user_rejects_non_admin(self):
        ws = _get_web_server()
        user = types.SimpleNamespace(role="user", username="alice")

        with pytest.raises(ws.HTTPException) as exc_info:
            ws._require_admin_user(user)

        assert exc_info.value.status_code == 403

    def test_require_metrics_access_accepts_valid_metrics_token(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.cfg, "METRICS_TOKEN", "secret-token", raising=False)
        request = types.SimpleNamespace(headers={"Authorization": "Bearer secret-token"})
        user = types.SimpleNamespace(role="user", username="alice")

        result = ws._require_metrics_access(request, user)

        assert result is user

    def test_require_metrics_access_rejects_without_token_and_admin(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.cfg, "METRICS_TOKEN", "secret-token", raising=False)
        request = types.SimpleNamespace(headers={"Authorization": "Bearer wrong-token"})
        user = types.SimpleNamespace(role="user", username="alice")

        with pytest.raises(ws.HTTPException) as exc_info:
            ws._require_metrics_access(request, user)

        assert exc_info.value.status_code == 403


class TestWebServerPolicyResolution:
    @pytest.mark.parametrize(
        "path, method, expected",
        [
            ("/rag/search", "GET", ("rag", "read", "*")),
            ("/rag/doc/abc", "DELETE", ("rag", "write", "abc")),
            ("/github-commits", "POST", ("github", "write", "*")),
            ("/set-repo", "GET", ("github", "read", "*")),
            ("/ws/chat", "GET", ("swarm", "execute", "*")),
            ("/unknown", "GET", ("", "", "")),
        ],
    )
    def test_resolve_policy_from_request_branches(self, path, method, expected):
        ws = _get_web_server()
        request = types.SimpleNamespace(url=types.SimpleNamespace(path=path), method=method)

        assert ws._resolve_policy_from_request(request) == expected


class TestAuthPayloadValidation:
    def test_register_user_rejects_invalid_payload(self):
        ws = _get_web_server()
        payload = types.SimpleNamespace(username="  ", password="", tenant_id="default")

        with pytest.raises(ws.HTTPException) as exc_info:
            __import__("asyncio").run(ws.register_user(payload))

        assert exc_info.value.status_code == 400

    def test_register_user_returns_409_when_db_raises(self, monkeypatch):
        ws = _get_web_server()
        payload = types.SimpleNamespace(username="alice", password="secret123", tenant_id="default")

        class _FakeDb:
            async def register_user(self, **_kwargs):
                raise RuntimeError("unique constraint failed: users.username")

        async def _fake_get_agent():
            return types.SimpleNamespace(memory=types.SimpleNamespace(db=_FakeDb()))

        monkeypatch.setattr(ws, "get_agent", _fake_get_agent)

        with pytest.raises(ws.HTTPException) as exc_info:
            __import__("asyncio").run(ws.register_user(payload))

        assert exc_info.value.status_code == 409
        assert "Kullanıcı oluşturulamadı" in str(exc_info.value.detail)

    def test_login_user_rejects_invalid_credentials(self, monkeypatch):
        ws = _get_web_server()
        payload = types.SimpleNamespace(username="alice", password="wrong")

        class _FakeDb:
            async def authenticate_user(self, **_kwargs):
                return None

        async def _fake_get_agent():
            return types.SimpleNamespace(memory=types.SimpleNamespace(db=_FakeDb()))

        monkeypatch.setattr(ws, "get_agent", _fake_get_agent)

        with pytest.raises(ws.HTTPException) as exc_info:
            __import__("asyncio").run(ws.login_user(payload))

        assert exc_info.value.status_code == 401
        assert "hatalı" in str(exc_info.value.detail)

    def test_login_user_success_returns_json_payload(self, monkeypatch):
        ws = _get_web_server()
        payload = types.SimpleNamespace(username="alice", password="secret123")

        class _FakeJSONResponse:
            def __init__(self, content, status_code=200):
                self.content = content
                self.status_code = status_code

        fake_user = types.SimpleNamespace(id="u-1", username="alice", role="admin")

        class _FakeDb:
            async def authenticate_user(self, **_kwargs):
                return fake_user

        async def _fake_get_agent():
            return types.SimpleNamespace(memory=types.SimpleNamespace(db=_FakeDb()))

        async def _fake_issue_auth_token(_agent, _user):
            return "jwt-token"

        monkeypatch.setattr(ws, "JSONResponse", _FakeJSONResponse)
        monkeypatch.setattr(ws, "get_agent", _fake_get_agent)
        monkeypatch.setattr(ws, "_issue_auth_token", _fake_issue_auth_token)

        response = __import__("asyncio").run(ws.login_user(payload))
        assert response.status_code == 200
        assert response.content["access_token"] == "jwt-token"
        assert response.content["user"]["username"] == "alice"
