"""Unit tests for collaboration helper functions in web_server."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException
pytest.importorskip("httpx")

from web_server import (
    _collaboration_command_requires_write,
    _collaboration_write_scopes_for_role,
    _normalize_collaboration_role,
    _normalize_room_id,
)


def test_normalize_room_id_defaults_and_validation() -> None:
    assert _normalize_room_id("") == "workspace:default"
    assert _normalize_room_id("workspace:team-1") == "workspace:team-1"

    with pytest.raises(HTTPException):
        _normalize_room_id("bad room id !")


def test_normalize_collaboration_role_and_write_intent() -> None:
    assert _normalize_collaboration_role("ADMIN") == "admin"
    assert _normalize_collaboration_role("unknown-role") == "user"

    assert _collaboration_command_requires_write("write file src/app.py") is True
    assert _collaboration_command_requires_write("dosya düzenle") is True
    assert _collaboration_command_requires_write("sadece oku") is False


def test_collaboration_write_scopes_for_roles() -> None:
    room_id = "workspace:alpha"
    admin_scopes = _collaboration_write_scopes_for_role("admin", room_id)
    editor_scopes = _collaboration_write_scopes_for_role("editor", room_id)
    user_scopes = _collaboration_write_scopes_for_role("user", room_id)

    assert admin_scopes
    assert any("workspaces/workspace/alpha" in scope for scope in editor_scopes)
    assert user_scopes == []
