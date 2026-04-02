from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import web_server


def test_normalize_room_id_defaults_and_rejects_invalid() -> None:
    assert web_server._normalize_room_id("") == "workspace:default"
    assert web_server._normalize_room_id("project:alpha") == "project:alpha"

    with pytest.raises(web_server.HTTPException) as exc:
        web_server._normalize_room_id("invalid room")
    assert exc.value.status_code == 400


def test_collaboration_write_scopes_change_by_role(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web_server, "cfg", SimpleNamespace(BASE_DIR=tmp_path))

    admin_scopes = web_server._collaboration_write_scopes_for_role("admin", "workspace:main")
    dev_scopes = web_server._collaboration_write_scopes_for_role("developer", "workspace:main")
    user_scopes = web_server._collaboration_write_scopes_for_role("user", "workspace:main")

    assert admin_scopes == [str(tmp_path.resolve())]
    assert dev_scopes == [str((tmp_path / "workspaces/workspace/main").resolve())]
    assert user_scopes == []


def test_plugin_filename_and_capability_sanitization() -> None:
    assert web_server._plugin_source_filename("coverage agent@v1") == "<sidar-plugin:coverage_agent_v1>"
    assert web_server._sanitize_capabilities([" read ", "", "write"]) == ["read", "write"]
    assert web_server._sanitize_capabilities(None) == []


@pytest.mark.asyncio
async def test_resolve_user_from_token_falls_back_to_db(monkeypatch: pytest.MonkeyPatch) -> None:
    class _JwtError(Exception):
        pass

    class _JwtStub:
        PyJWTError = _JwtError

        @staticmethod
        def decode(*_args, **_kwargs):
            raise _JwtError("invalid token")

    class _Db:
        async def get_user_by_token(self, token: str):
            return SimpleNamespace(id="db-1", username="db-user", role="admin", tenant_id="tenant-a") if token == "opaque" else None

    agent = SimpleNamespace(memory=SimpleNamespace(db=_Db()))

    monkeypatch.setattr(web_server, "jwt", _JwtStub)
    monkeypatch.setattr(web_server, "cfg", SimpleNamespace(JWT_SECRET_KEY="secret", JWT_ALGORITHM="HS256"))

    resolved = await web_server._resolve_user_from_token(agent, "opaque")

    assert resolved is not None
    assert resolved.username == "db-user"
    assert resolved.role == "admin"


def test_build_user_from_jwt_payload_requires_subject_and_username() -> None:
    assert web_server._build_user_from_jwt_payload({"sub": "1", "username": "alice", "role": "maintainer"}).username == "alice"
    assert web_server._build_user_from_jwt_payload({"sub": "1"}) is None
    assert web_server._build_user_from_jwt_payload({"username": "alice"}) is None
