from __future__ import annotations

import builtins
from datetime import datetime
from types import SimpleNamespace

import pytest

from managers.github_manager import GitHubManager


class _GHManagerNoInit(GitHubManager):
    def _init_client(self) -> None:
        self._gh = None
        self._repo = None
        self._available = False


class _Boom(Exception):
    pass


def test_init_client_token_validation_and_import_error(monkeypatch) -> None:
    with pytest.raises(ValueError):
        GitHubManager(token="", repo_name="octo/repo", require_token=False)

    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "github":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    manager = GitHubManager(token="tok", repo_name="", require_token=False)
    assert manager.is_available() is False


def test_low_level_repo_helpers_and_status_default_branch() -> None:
    manager = _GHManagerNoInit(token="", repo_name="", require_token=False)

    assert manager._load_repo("x/y") is False
    assert manager.default_branch == "main"
    assert "Bağlı değil" in manager.status()
    assert manager.is_available() is False

    manager.token = "abc"
    assert "Token geçersiz" in manager.status()

    manager._available = True
    manager.repo_name = "octo/repo"
    assert manager.status() == "GitHub: Bağlı | Depo: octo/repo"


def test_list_repos_repo_info_commits_and_branches_negative_paths() -> None:
    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)

    assert manager.list_repos() == (False, [])
    assert manager.get_repo_info() == (False, "Aktif depo yok. Önce bir depo belirtin.")
    assert manager.list_commits() == (False, "Aktif depo yok.")
    assert manager.list_branches() == (False, "Aktif depo yok.")

    class _GH:
        def get_repo(self, _repo_name: str):
            raise RuntimeError("cannot load")

        def get_user(self, *_args, **_kwargs):
            return SimpleNamespace(
                type="User",
                get_repos=lambda **_k: [
                    SimpleNamespace(full_name="a/a", default_branch="main", private=False),
                    SimpleNamespace(full_name="b/b", default_branch="dev", private=True),
                ],
            )

    manager._gh = _GH()
    assert manager._load_repo("a/a") is False

    ok, repos = manager.list_repos(limit=1)
    assert ok is True
    assert len(repos) == 1


def test_content_and_file_listing_paths() -> None:
    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)

    assert manager.read_remote_file("README.md") == (False, "Aktif depo yok.")
    assert manager.list_files() == (False, "Aktif depo yok.")

    class _Repo:
        full_name = "octo/repo"

        def get_contents(self, path: str, **kwargs):
            if kwargs.get("ref") == "bad":
                raise RuntimeError("bad ref")
            if path == "dir":
                return [SimpleNamespace(type="file", name="b.txt"), SimpleNamespace(type="dir", name="a")]
            return SimpleNamespace(name="ok.md", type="file", decoded_content="ok".encode("utf-8"))

    manager._repo = _Repo()

    ok_read, txt = manager.read_remote_file("ok.md", ref="main")
    assert ok_read is True and txt == "ok"

    ok_list, listed = manager.list_files("dir", branch="main")
    assert ok_list is True
    assert "📂 a" in listed and "📄 b.txt" in listed

    ok_fail, msg_fail = manager.list_files("dir", branch="bad")
    assert ok_fail is False and "Dosya listesi alınamadı" in msg_fail


def test_create_update_branch_pr_and_issue_error_paths() -> None:
    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)

    assert manager.create_or_update_file("x", "1", "m") == (False, "Aktif depo yok.")
    assert manager.create_branch("feat/x") == (False, "Aktif depo yok.")
    assert manager.create_pull_request("t", "b", "h") == (False, "Aktif depo yok.")
    assert manager.add_pr_comment(1, "c") == (False, "Aktif depo yok.")
    assert manager.close_pull_request(1) == (False, "Aktif depo yok.")
    assert manager.list_issues() == (False, ["Aktif depo yok."])
    assert manager.create_issue("t", "b") == (False, "Aktif depo yok.")
    assert manager.comment_issue(1, "b") == (False, "Aktif depo yok.")
    assert manager.close_issue(1) == (False, "Aktif depo yok.")

    class _Repo:
        default_branch = "main"

        def get_contents(self, *_a, **_k):
            raise RuntimeError("read failed")

        def get_branch(self, _b: str):
            return SimpleNamespace(commit=SimpleNamespace(sha="abc123"))

        def create_git_ref(self, **kwargs):
            if kwargs["ref"].endswith("boom"):
                raise RuntimeError("create ref failed")

        def create_pull(self, **_k):
            raise RuntimeError("pr failed")

        def get_issue(self, **_k):
            raise RuntimeError("issue failed")

        def create_issue(self, **_k):
            raise RuntimeError("issue create failed")

    manager._repo = _Repo()

    ok_readerr, msg_readerr = manager.create_or_update_file("x", "1", "m")
    assert ok_readerr is False and "GitHub dosya okuma hatası" in msg_readerr

    ok_branch, msg_branch = manager.create_branch("feature/new")
    assert ok_branch is True and "Dal oluşturuldu" in msg_branch

    ok_branch_err, msg_branch_err = manager.create_branch("boom")
    assert ok_branch_err is False and "Dal oluşturma hatası" in msg_branch_err

    assert manager.create_pull_request("t", "b", "h")[0] is False
    assert manager.add_pr_comment(2, "x")[0] is False
    assert manager.close_pull_request(2)[0] is False
    assert manager.create_issue("t", "b")[0] is False
    assert manager.comment_issue(1, "b")[0] is False
    assert manager.close_issue(1)[0] is False


def test_pull_request_rendering_diff_files_and_search() -> None:
    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)

    assert manager.list_pull_requests() == (False, "Aktif depo yok.")
    assert manager.get_pull_request(7) == (False, "Aktif depo yok.")
    assert manager.get_pull_request_diff(3) == (False, "Aktif depo yok.")
    assert manager.get_pr_files(3) == (False, "Aktif depo yok.")
    assert manager.search_code("abc") == (False, "GitHub bağlantısı veya aktif depo yok.")
    assert manager.get_pull_requests_detailed() == (False, [], "Repo ayarlanmamış.")

    files = [
        SimpleNamespace(status="modified", additions=1, deletions=1, filename=f"f{i}.py")
        for i in range(22)
    ]

    class _PR:
        number = 7
        title = "Improve tests"
        state = "open"
        user = SimpleNamespace(login="alice")
        head = SimpleNamespace(ref="feat")
        base = SimpleNamespace(ref="main")
        created_at = datetime(2026, 1, 1, 10, 0)
        updated_at = datetime(2026, 1, 2, 10, 0)
        additions = 5
        deletions = 1
        changed_files = 2
        comments = 0
        html_url = "https://example/pr/7"
        body = "Body"

        def get_files(self):
            return files

        def edit(self, **_kwargs):
            raise RuntimeError("cannot close")

    class _GH:
        def search_code(self, _q: str):
            return [SimpleNamespace(path="a.py")]

    class _Repo:
        full_name = "octo/repo"

        def get_pulls(self, **_kwargs):
            return []

        def get_pull(self, n: int):
            if n == 999:
                raise RuntimeError("missing pr")
            if n == 3:
                return SimpleNamespace(title="No files", get_files=lambda: [])
            return _PR()

    manager._repo = _Repo()
    manager._gh = _GH()

    ok_empty, msg_empty = manager.list_pull_requests(state="OPEN")
    assert ok_empty is True and "Hiç open PR" in msg_empty

    ok_pr, msg_pr = manager.get_pull_request(7)
    assert ok_pr is True and "+2 dosya daha" in msg_pr

    ok_pr_err, msg_pr_err = manager.get_pull_request(999)
    assert ok_pr_err is False and "PR detayı alınamadı" in msg_pr_err

    ok_diff_empty, msg_diff_empty = manager.get_pull_request_diff(3)
    assert ok_diff_empty is True and "değiştirilmiş kod dosyası" in msg_diff_empty

    ok_diff_err, msg_diff_err = manager.get_pull_request_diff(999)
    assert ok_diff_err is False and "Diff alınamadı" in msg_diff_err

    ok_files, msg_files = manager.get_pr_files(7)
    assert ok_files is True and "f0.py" in msg_files

    ok_files_err, msg_files_err = manager.get_pr_files(999)
    assert ok_files_err is False and "PR dosya listesi alınamadı" in msg_files_err

    ok_search, msg_search = manager.search_code("token")
    assert ok_search is True and "📄 a.py" in msg_search
