"""web_server auth/policy yardımcıları için odaklı birim testleri."""

from __future__ import annotations

import types

import pytest

from tests.test_web_server import _get_web_server


class TestWebServerAuthHelpers:
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
