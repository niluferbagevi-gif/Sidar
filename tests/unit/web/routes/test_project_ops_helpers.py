from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from web.routes.project_ops import (
    _extract_repo_from_remote,
    _is_allowed_git_command,
    _resolve_web_server_helper,
    build_project_ops_router,
)


def test_is_allowed_git_command_rejects_null_byte_injection() -> None:
    assert _is_allowed_git_command(["git", "remote", "get-url", "origin\x00--upload-pack=evil"]) is False


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/sidar-ai/sidar.git", "sidar-ai/sidar"),
        ("git@github.com:sidar-ai/sidar.git", "sidar-ai/sidar"),
        ("https://gitlab.example.com/sidar-ai/sidar.git", "sidar"),
        ("git@gitlab.example.com:sidar-ai/sidar.git", "sidar-ai/sidar"),
        ("/workspace/Sidar.git", "Sidar"),
        ("", ""),
    ],
)
def test_extract_repo_from_remote_supports_common_url_formats(remote: str, expected: str) -> None:
    assert _extract_repo_from_remote(remote) == expected


def test_resolve_web_server_helper_returns_default_without_legacy_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = object()
    monkeypatch.delitem(sys.modules, "web_server", raising=False)

    assert _resolve_web_server_helper("_git_run", default) is default


def _build_github_repos_handler(github: Any, tmp_path: Path) -> Any:
    agent = SimpleNamespace(github=github)

    async def _resolve_agent_instance() -> Any:
        return agent

    router = build_project_ops_router(
        get_request_user=lambda: None,
        resolve_agent_instance=_resolve_agent_instance,
        max_file_content_bytes=1024,
        server_root=tmp_path,
        cfg=SimpleNamespace(GITHUB_REPO="sidar-ai/sidar"),
        logger=SimpleNamespace(warning=lambda *_args: None),
    )
    return router.legacy_exports["github_repos"]


def _json_body(response: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(response.body))


@pytest.mark.asyncio
async def test_github_repos_accepts_sync_list_repos_result(tmp_path: Path) -> None:
    github = SimpleNamespace(
        repo_name="sidar-ai/sidar",
        list_repos=lambda **_kwargs: (True, [{"full_name": "sidar-ai/sidar"}]),
    )

    response = await _build_github_repos_handler(github, tmp_path)()

    assert _json_body(response) == {
        "success": True,
        "repos": [{"full_name": "sidar-ai/sidar"}],
        "active_repo": "sidar-ai/sidar",
        "owner": "sidar-ai",
    }


@pytest.mark.asyncio
async def test_github_repos_awaits_async_list_repos_result(tmp_path: Path) -> None:
    async def _list_repos(**_kwargs: Any) -> tuple[bool, list[dict[str, str]]]:
        return True, [{"full_name": "sidar-ai/sidar"}]

    github = SimpleNamespace(repo_name="sidar-ai/sidar", list_repos=_list_repos)

    response = await _build_github_repos_handler(github, tmp_path)()

    assert _json_body(response) == {
        "success": True,
        "repos": [{"full_name": "sidar-ai/sidar"}],
        "active_repo": "sidar-ai/sidar",
        "owner": "sidar-ai",
    }
