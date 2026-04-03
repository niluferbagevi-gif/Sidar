from __future__ import annotations

import sys
import types
from datetime import datetime
from types import SimpleNamespace

from managers.github_manager import GitHubManager


class _GHManagerNoInit(GitHubManager):
    def _init_client(self) -> None:
        self._gh = None
        self._repo = None
        self._available = False


class _Status404Error(Exception):
    status = 404


def test_init_client_uses_patched_pygithub_and_loads_repo(monkeypatch) -> None:
    class _FakeAuth:
        class Token:
            def __init__(self, token: str) -> None:
                self.token = token

    class _FakeGithubClient:
        def __init__(self, *, auth) -> None:
            self.auth = auth

        def get_user(self, owner: str | None = None):
            if owner:
                return SimpleNamespace(login=owner)
            return SimpleNamespace(login="octocat")

        def get_repo(self, repo_name: str):
            return SimpleNamespace(full_name=repo_name, default_branch="main")

    fake_module = types.ModuleType("github")
    fake_module.Auth = _FakeAuth
    fake_module.Github = _FakeGithubClient
    monkeypatch.setitem(sys.modules, "github", fake_module)

    manager = GitHubManager(token=" test-token ", repo_name="octo/repo", require_token=True)

    assert manager.is_available() is True
    assert manager.repo_name == "octo/repo"
    assert manager._repo.full_name == "octo/repo"


def test_set_repo_list_repos_and_read_remote_file_guards() -> None:
    class _RepoFile:
        def __init__(self, name: str, decoded_content: bytes = b"ok") -> None:
            self.name = name
            self.type = "file"
            self.decoded_content = decoded_content

    class _RepoStub:
        full_name = "octo/repo"
        default_branch = "main"

        def get_contents(self, file_path: str, **_kwargs):
            if file_path.endswith(".zip"):
                return _RepoFile("archive.zip")
            if file_path == "UNKNOWNFILE":
                return _RepoFile("UNKNOWNFILE")
            if file_path.endswith(".txt"):
                return _RepoFile("bad.txt", decoded_content=b"hello")
            return _RepoFile("README.md", decoded_content="merhaba".encode("utf-8"))

    class _OwnerAccount:
        def __init__(self, repos, account_type: str) -> None:
            self._repos = repos
            self.type = account_type

        def get_repos(self, **_kwargs):
            return self._repos

    class _GHStub:
        def __init__(self) -> None:
            self.self_repos = [SimpleNamespace(full_name="a/r1", default_branch="main", private=False)]
            self.owner_repos = [SimpleNamespace(full_name="org/r2", default_branch="master", private=True)]

        def get_repo(self, repo_name: str):
            if repo_name == "missing/repo":
                raise RuntimeError("not found")
            return _RepoStub()

        def get_user(self, owner: str | None = None):
            if owner:
                return _OwnerAccount(self.owner_repos, "Organization")
            return _OwnerAccount(self.self_repos, "User")

    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._gh = _GHStub()
    manager._available = True

    ok_set, msg_set = manager.set_repo("octo/repo")
    assert ok_set is True
    assert "Depo değiştirildi" in msg_set

    ok_list_self, repos_self = manager.list_repos(limit=5)
    assert ok_list_self is True
    assert repos_self[0]["full_name"] == "a/r1"

    ok_list_owner, repos_owner = manager.list_repos(owner="org", limit=5)
    assert ok_list_owner is True
    assert repos_owner[0]["private"] == "true"

    ok_zip, msg_zip = manager.read_remote_file("dist/archive.zip")
    assert ok_zip is False
    assert "⚠ Güvenlik/Hata Koruması" in msg_zip

    ok_noext, msg_noext = manager.read_remote_file("UNKNOWNFILE")
    assert ok_noext is False
    assert "uzantısız dosya" in msg_noext.lower()


def test_read_remote_file_handles_unicode_decode_error() -> None:
    class _BrokenContent:
        @property
        def decoded_content(self) -> bytes:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")

    class _RepoStub:
        def get_contents(self, *_args, **_kwargs):
            return SimpleNamespace(name="notes.txt", type="file", decoded_content=_BrokenContent().decoded_content)

    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = _RepoStub()

    ok, msg = manager.read_remote_file("notes.txt")

    assert ok is False
    assert "UTF-8" in msg


def test_create_or_update_file_and_pr_listing_paths() -> None:
    class _RepoStub:
        full_name = "octo/repo"
        default_branch = "main"

        def __init__(self) -> None:
            self.updated = []
            self.created = []

        def get_contents(self, file_path: str, **_kwargs):
            if file_path == "exists.txt":
                return SimpleNamespace(sha="sha-1")
            raise _Status404Error("missing")

        def update_file(self, **kwargs):
            self.updated.append(kwargs)

        def create_file(self, **kwargs):
            self.created.append(kwargs)

        def create_pull(self, **kwargs):
            return SimpleNamespace(title=kwargs["title"], html_url="https://example/pr/9", number=9)

        def get_pulls(self, **_kwargs):
            return [
                SimpleNamespace(
                    number=12,
                    updated_at=datetime(2026, 1, 1, 12, 0),
                    user=SimpleNamespace(login="alice"),
                    title="Fix tests",
                )
            ]

    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = _RepoStub()

    ok_update, _ = manager.create_or_update_file("exists.txt", "new", "update message")
    ok_create, _ = manager.create_or_update_file("new.txt", "body", "create message", branch="feat/x")
    ok_pr, msg_pr = manager.create_pull_request("Başlık", "Açıklama", head="feat/x")
    ok_list, msg_list = manager.list_pull_requests(state="invalid", limit=10)

    assert ok_update is True
    assert ok_create is True
    assert manager._repo.updated[0]["sha"] == "sha-1"
    assert manager._repo.created[0]["branch"] == "feat/x"

    assert ok_pr is True
    assert "#9" in msg_pr

    assert ok_list is True
    assert "PR Listesi (OPEN)" in msg_list
    assert "#  12" in msg_list


def test_issue_listing_and_pr_diff_output() -> None:
    class _IssueStub:
        def __init__(self, number: int, is_pr: bool) -> None:
            self.number = number
            self.title = f"Issue {number}"
            self.state = "open"
            self.user = SimpleNamespace(login="bob")
            self.created_at = datetime(2026, 1, number)
            self.pull_request = {} if is_pr else None

    class _RepoStub:
        def get_issues(self, **_kwargs):
            return [_IssueStub(1, False), _IssueStub(2, True)]

        def get_pull(self, number: int):
            assert number == 5
            return SimpleNamespace(
                title="Feature",
                get_files=lambda: [
                    SimpleNamespace(filename="a.py", status="modified", patch="+print('ok')"),
                    SimpleNamespace(filename="bin.dat", status="modified", patch=None),
                ],
            )

    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = _RepoStub()

    ok_issues, issues = manager.list_issues(state="OPEN", limit=5)
    ok_diff, diff_text = manager.get_pull_request_diff(5)

    assert ok_issues is True
    assert len(issues) == 1
    assert issues[0]["number"] == 1

    assert ok_diff is True
    assert "PR #5 DIFF" in diff_text
    assert "a.py" in diff_text
    assert "binary" in diff_text.lower()
