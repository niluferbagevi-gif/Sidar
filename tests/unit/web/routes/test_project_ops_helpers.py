from __future__ import annotations

import inspect
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
    is_valid_git_ref_name,
)


def test_is_allowed_git_command_rejects_null_byte_injection() -> None:
    assert (
        _is_allowed_git_command(["git", "remote", "get-url", "origin\x00--upload-pack=evil"])
        is False
    )


@pytest.mark.parametrize(
    "branch_name",
    [
        "-upload-pack=evil",
        "--upload-pack=evil",
        "-rf",
        "-B",
    ],
)
def test_is_valid_git_ref_name_rejects_leading_dash_argument_injection(branch_name: str) -> None:
    """Regression test: a branch name starting with "-" must be rejected — git

    subprocess calls use argv (shell=False) so shell metacharacters are already
    safe, but a leading "-" lets git itself misinterpret the value as a flag
    (e.g. `git checkout -upload-pack=evil`). This is the same validator
    github_upload.py already used (managers.code.git_validation), now shared
    with web/routes/project_ops.py's /set-branch endpoint.
    """
    assert is_valid_git_ref_name(branch_name) is False


def test_is_valid_git_ref_name_accepts_normal_branch_names() -> None:
    for branch_name in ("feature/safe-branch_1", "main", "release-1.0"):
        assert is_valid_git_ref_name(branch_name) is True


def test_git_run_logs_called_process_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from subprocess import CalledProcessError

    from web.routes.project_ops import _git_run

    warnings: list[tuple[Any, ...]] = []
    logger = SimpleNamespace(warning=lambda *args: warnings.append(args))

    def _raise_called_process_error(*_args: Any, **_kwargs: Any) -> bytes:
        raise CalledProcessError(7, "git")

    monkeypatch.setattr("subprocess.check_output", _raise_called_process_error)

    assert _git_run(["git"], ".", logger=logger) == ""
    assert warnings
    assert "Git komutu başarısız oldu" in warnings[0][0]


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


class _JsonRequest:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def json(self) -> dict[str, Any]:
        return self.payload


def _build_project_exports(tmp_path: Path, db: Any) -> dict[str, Any]:
    memory = SimpleNamespace(db=db, _safe_ts=lambda value: f"safe:{value}")
    agent = SimpleNamespace(memory=memory)

    async def _resolve_agent_instance() -> Any:
        return agent

    return build_project_ops_router(
        get_request_user=lambda: SimpleNamespace(id="user-1"),
        resolve_agent_instance=_resolve_agent_instance,
        max_file_content_bytes=4,
        server_root=tmp_path,
        cfg=SimpleNamespace(GITHUB_REPO="sidar-ai/sidar"),
        logger=SimpleNamespace(warning=lambda *_args: None),
    ).legacy_exports


@pytest.mark.asyncio
async def test_project_session_handlers_cover_create_load_list_and_delete(tmp_path: Path) -> None:
    session = SimpleNamespace(id="s1", title="Session", updated_at="now")
    messages = [SimpleNamespace(role="user", content="hello", created_at="then", tokens_used=1)]

    class _DB:
        async def list_sessions(self, _user_id: str) -> list[Any]:
            return [session]

        async def get_session_messages(self, _session_id: str) -> list[Any]:
            return messages

        async def load_session(self, session_id: str, _user_id: str) -> Any:
            return session if session_id == "s1" else None

        async def create_session(self, _user_id: str, _title: str) -> Any:
            return session

        async def delete_session(self, session_id: str, _user_id: str) -> bool:
            return session_id == "s1"

    exports = _build_project_exports(tmp_path, _DB())
    user = SimpleNamespace(id="user-1")
    request = SimpleNamespace()

    assert (
        _json_body(await exports["get_sessions"](request, user))["sessions"][0]["message_count"]
        == 1
    )
    assert (await exports["load_session"]("missing", request, user)).status_code == 404
    assert (
        _json_body(await exports["load_session"]("s1", request, user))["history"][0]["timestamp"]
        == "safe:then"
    )
    assert _json_body(await exports["new_session"](request, user)) == {
        "success": True,
        "session_id": "s1",
    }
    assert _json_body(await exports["delete_session"]("s1", request, user)) == {"success": True}
    assert (await exports["delete_session"]("missing", request, user)).status_code == 500


def test_project_file_handlers_require_authenticated_user_dependency(tmp_path: Path) -> None:
    exports = _build_project_exports(tmp_path, SimpleNamespace())

    list_user_default = inspect.signature(exports["list_project_files"]).parameters["_user"].default
    content_user_default = inspect.signature(exports["file_content"]).parameters["_user"].default

    assert getattr(list_user_default, "dependency", None) is not None
    assert getattr(content_user_default, "dependency", None) is not None


@pytest.mark.asyncio
async def test_project_file_handlers_cover_listing_content_and_security_edges(
    tmp_path: Path,
) -> None:
    (tmp_path / "visible").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "note.txt").write_text("hey", encoding="utf-8")
    (tmp_path / "large.txt").write_text("12345", encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"x")
    exports = _build_project_exports(tmp_path, SimpleNamespace())

    listing = _json_body(await exports["list_project_files"]())
    assert [item["name"] for item in listing["items"]] == [
        "visible",
        "image.bin",
        "large.txt",
        "note.txt",
    ]
    assert (await exports["list_project_files"]("../outside")).status_code == 403
    assert (await exports["list_project_files"]("missing")).status_code == 404
    assert (await exports["list_project_files"]("note.txt")).status_code == 400
    assert _json_body(await exports["file_content"]("note.txt"))["content"] == "hey"
    assert (await exports["file_content"]("../outside.txt")).status_code == 403
    assert (await exports["file_content"]("missing.txt")).status_code == 404
    assert (await exports["file_content"]("visible")).status_code == 400
    assert (await exports["file_content"]("image.bin")).status_code == 415
    assert (await exports["file_content"]("large.txt")).status_code == 413


@pytest.mark.asyncio
async def test_project_git_branch_handlers_validate_and_report_checkout_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    web_server = SimpleNamespace(
        _git_run=lambda cmd, _cwd, _logger: ("feature\nmain" if cmd[1] == "branch" else "feature")
    )
    monkeypatch.setitem(sys.modules, "web_server", web_server)
    exports = _build_project_exports(tmp_path, SimpleNamespace())

    branches = _json_body(await exports["git_branches"]())
    assert branches == {"branches": ["feature", "main"], "current": "feature"}
    assert (await exports["set_branch"](_JsonRequest({"branch": " "}))).status_code == 400
    assert (await exports["set_branch"](_JsonRequest({"branch": "bad branch"}))).status_code == 400
    assert (
        await exports["set_branch"](_JsonRequest({"branch": "-upload-pack=evil"}))
    ).status_code == 400

    monkeypatch.setattr("subprocess.check_output", lambda *_args, **_kwargs: b"")
    assert _json_body(await exports["set_branch"](_JsonRequest({"branch": "feature"}))) == {
        "success": True,
        "branch": "feature",
    }

    def _checkout_error(*_args: Any, **_kwargs: Any) -> Any:
        raise __import__("subprocess").CalledProcessError(1, "git", output=b"missing branch")

    monkeypatch.setattr("subprocess.check_output", _checkout_error)
    failed = await exports["set_branch"](_JsonRequest({"branch": "missing"}))
    assert failed.status_code == 400
    assert _json_body(failed)["error"] == "missing branch"


def _build_github_project_exports(
    tmp_path: Path, github: Any, cfg: Any | None = None
) -> dict[str, Any]:
    agent = SimpleNamespace(github=github)

    async def _resolve_agent_instance() -> Any:
        return agent

    return build_project_ops_router(
        get_request_user=lambda: None,
        resolve_agent_instance=_resolve_agent_instance,
        max_file_content_bytes=4,
        server_root=tmp_path,
        cfg=cfg or SimpleNamespace(GITHUB_REPO="sidar-ai/sidar"),
        logger=SimpleNamespace(warning=lambda *_args: None),
    ).legacy_exports


@pytest.mark.asyncio
async def test_project_github_handlers_cover_errors_filters_and_repo_updates(
    tmp_path: Path,
) -> None:
    cfg = SimpleNamespace(GITHUB_REPO="sidar-ai/sidar")
    github = SimpleNamespace(
        repo_name="sidar-ai/sidar",
        list_repos=lambda **_kwargs: (False, []),
        is_available=lambda: False,
        set_repo=lambda repo: (True, f"selected {repo}"),
    )
    exports = _build_github_project_exports(tmp_path, github, cfg)

    assert (await exports["github_repos"]()).status_code == 400
    assert (await exports["github_prs"]()).status_code == 503
    assert (await exports["github_pr_detail"](1)).status_code == 503
    assert (await exports["set_repo"](_JsonRequest({"repo": " "}))).status_code == 400
    selected = await exports["set_repo"](_JsonRequest({"repo": "sidar-ai/new"}))
    assert _json_body(selected) == {"success": True, "message": "selected sidar-ai/new"}
    assert cfg.GITHUB_REPO == "sidar-ai/new"

    github.list_repos = lambda **_kwargs: (
        True,
        [{"full_name": "sidar-ai/zeta"}, {"full_name": "sidar-ai/alpha"}],
    )
    filtered = _json_body(await exports["github_repos"](q="ALPHA"))
    assert filtered["repos"] == [{"full_name": "sidar-ai/alpha"}]


@pytest.mark.asyncio
async def test_project_github_pr_handlers_cover_upstream_failures_and_success(
    tmp_path: Path,
) -> None:
    github = SimpleNamespace(
        repo_name="sidar-ai/sidar",
        is_available=lambda: True,
        get_pull_requests_detailed=lambda **_kwargs: (False, [], "upstream failed"),
        get_pull_request=lambda _number: (False, "missing"),
    )
    exports = _build_github_project_exports(tmp_path, github)

    assert (await exports["github_prs"]()).status_code == 500
    assert (await exports["github_pr_detail"](404)).status_code == 404

    github.get_pull_requests_detailed = lambda **_kwargs: (True, [{"number": 1}], "")
    github.get_pull_request = lambda number: (True, {"number": number})
    assert _json_body(await exports["github_prs"]())["prs"] == [{"number": 1}]
    assert _json_body(await exports["github_pr_detail"](1))["detail"] == {"number": 1}
