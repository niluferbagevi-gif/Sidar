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


class TestJwtTokenResolution:
    def test_resolve_user_from_token_prefers_valid_jwt_payload(self, monkeypatch):
        ws = _get_web_server()
        expected_payload = {"sub": "u-1", "username": "alice", "role": "admin", "tenant_id": "acme"}

        class _JwtError(Exception):
            pass

        fake_jwt = types.SimpleNamespace(
            decode=lambda token, secret, algorithms: expected_payload,
            PyJWTError=_JwtError,
        )

        monkeypatch.setattr(ws, "jwt", fake_jwt)
        monkeypatch.setattr(ws, "_get_jwt_secret", lambda: "secret")
        monkeypatch.setattr(ws.cfg, "JWT_ALGORITHM", "HS256", raising=False)

        resolved = __import__("asyncio").run(ws._resolve_user_from_token(None, "jwt-token"))
        assert resolved is not None
        assert resolved.id == "u-1"
        assert resolved.username == "alice"
        assert resolved.role == "admin"
        assert resolved.tenant_id == "acme"

    def test_resolve_user_from_token_falls_back_to_db_for_non_jwt_tokens(self, monkeypatch):
        ws = _get_web_server()

        class _JwtError(Exception):
            pass

        def _decode(*_args, **_kwargs):
            raise _JwtError("invalid signature")

        fake_jwt = types.SimpleNamespace(decode=_decode, PyJWTError=_JwtError)
        monkeypatch.setattr(ws, "jwt", fake_jwt)
        monkeypatch.setattr(ws, "_get_jwt_secret", lambda: "secret")
        monkeypatch.setattr(ws.cfg, "JWT_ALGORITHM", "HS256", raising=False)

        fallback_user = types.SimpleNamespace(id="db-user", username="legacy")

        class _FakeDb:
            async def get_user_by_token(self, token):
                assert token == "opaque-token"
                return fallback_user

        agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_FakeDb()))

        resolved = __import__("asyncio").run(ws._resolve_user_from_token(agent, "opaque-token"))
        assert resolved is fallback_user

    def test_resolve_user_from_token_returns_none_when_jwt_and_db_lookup_fail(self, monkeypatch):
        ws = _get_web_server()

        class _JwtError(Exception):
            pass

        def _decode(*_args, **_kwargs):
            raise _JwtError("expired")

        fake_jwt = types.SimpleNamespace(decode=_decode, PyJWTError=_JwtError)
        monkeypatch.setattr(ws, "jwt", fake_jwt)
        monkeypatch.setattr(ws, "_get_jwt_secret", lambda: "secret")
        monkeypatch.setattr(ws.cfg, "JWT_ALGORITHM", "HS256", raising=False)

        class _FakeDb:
            async def get_user_by_token(self, _token):
                return None

        agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_FakeDb()))
        resolved = __import__("asyncio").run(ws._resolve_user_from_token(agent, "invalid-token"))
        assert resolved is None


class TestJwtTokenIssue:
    def test_issue_auth_token_uses_minimum_one_day_ttl_and_defaults(self, monkeypatch):
        ws = _get_web_server()
        encoded = {}

        def _encode(payload, secret, algorithm):
            encoded["payload"] = payload
            encoded["secret"] = secret
            encoded["algorithm"] = algorithm
            return "signed-token"

        monkeypatch.setattr(ws.jwt, "encode", _encode, raising=False)
        monkeypatch.setattr(ws, "_get_jwt_secret", lambda: "secret-key")
        monkeypatch.setattr(ws.cfg, "JWT_ALGORITHM", "HS384", raising=False)
        monkeypatch.setattr(ws.cfg, "JWT_TTL_DAYS", 0, raising=False)
        user = types.SimpleNamespace(id="u1", username="alice")

        token = __import__("asyncio").run(ws._issue_auth_token(types.SimpleNamespace(), user))
        assert token == "signed-token"
        assert encoded["secret"] == "secret-key"
        assert encoded["algorithm"] == "HS384"
        assert encoded["payload"]["sub"] == "u1"
        assert encoded["payload"]["username"] == "alice"
        assert encoded["payload"]["role"] == "user"
        assert encoded["payload"]["tenant_id"] == "default"
        assert encoded["payload"]["exp"] > encoded["payload"]["iat"]
