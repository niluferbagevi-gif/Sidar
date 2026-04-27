from __future__ import annotations

import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from tenacity import Future, RetryError

from managers.github_manager import GitHubManager, _is_not_found_error, _is_retryable_github_error
from tests.fixtures.github_mocks import Err404, FileMock, IssueMock, PRMock, RepoMock


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(GitHubManager, "_init_client", lambda self: None)
    m = GitHubManager(token=" token\u00f6 ", repo_name="", require_token=False)
    m._available = True
    m._gh = SimpleNamespace()
    m._repo = RepoMock()
    return m


def test_is_not_found_error_variants():
    assert _is_not_found_error(Err404("x")) is True
    assert _is_not_found_error(RuntimeError("404 gone")) is True
    assert _is_not_found_error(RuntimeError("Not Found")) is True
    assert _is_not_found_error(RuntimeError("boom")) is False


def test_is_retryable_github_error_status_and_message_paths():
    class HttpErr(RuntimeError):
        def __init__(self, msg: str, status: int | None = None):
            super().__init__(msg)
            self.status = status

    assert _is_retryable_github_error(HttpErr("Too many requests", status=429)) is True
    assert _is_retryable_github_error(HttpErr("API rate limit exceeded", status=403)) is True
    assert _is_retryable_github_error(RuntimeError("socket timeout while calling api")) is True
    assert _is_retryable_github_error(RuntimeError("non-retryable validation error")) is False


def test_init_token_cleanup_without_client_init(monkeypatch):
    monkeypatch.setattr(GitHubManager, "_init_client", lambda self: None)
    m = GitHubManager(token=" tok\u00e9n ")
    assert m.token == "tokn"


def test_init_client_no_token_optional(caplog):
    m = GitHubManager(token="", repo_name="", require_token=False)
    assert m.is_available() is False


def test_init_client_requires_token():
    with pytest.raises(ValueError):
        GitHubManager(token="", repo_name="x/y", require_token=True)


def test_load_repo_and_set_repo_paths(manager):
    manager._gh = SimpleNamespace(get_repo=lambda name: SimpleNamespace(name=name))
    assert manager._load_repo("a/b") is True
    assert manager.repo_name == "a/b"
    ok, msg = manager.set_repo("a/b")
    assert ok is True and "Depo değiştirildi" in msg


def test_load_repo_failure_and_set_repo_unavailable(manager):
    manager._gh = SimpleNamespace(get_repo=lambda _: (_ for _ in ()).throw(RuntimeError("x")))
    assert manager._load_repo("x") is False
    manager._available = False
    ok, msg = manager.set_repo("x")
    assert (ok, msg) == (False, "GitHub bağlantısı yok.")


def test_load_repo_retry_error_path(manager):
    future = Future(1)
    future.set_exception(RuntimeError("rate limited"))
    manager._call_with_retry = lambda *a, **k: (_ for _ in ()).throw(RetryError(future))
    manager._gh = SimpleNamespace(get_repo=lambda name: SimpleNamespace(name=name))
    assert manager._load_repo("org/repo") is False


def test_load_repo_without_client_and_set_repo_failed_lookup(manager):
    manager._gh = None
    assert manager._load_repo("x/y") is False

    manager._available = True
    manager._gh = SimpleNamespace(get_repo=lambda _: (_ for _ in ()).throw(RuntimeError("no repo")))
    ok, msg = manager.set_repo("x/y")
    assert (ok, msg) == (False, "Depo bulunamadı veya erişim reddedildi: x/y")


def test_list_repos_self_and_owner_and_error(manager):
    owner_repo = SimpleNamespace(full_name="org/r", default_branch="main", private=False)
    user_repo = SimpleNamespace(full_name="me/r", default_branch="dev", private=True)
    org_account = SimpleNamespace(type="Organization", get_repos=lambda type: [owner_repo])
    self_account = SimpleNamespace(get_repos=lambda visibility: [user_repo])
    manager._gh = SimpleNamespace(
        get_user=lambda owner=None: org_account if owner else self_account
    )
    ok, rows = manager.list_repos(owner="org", limit=1)
    assert ok is True and rows[0]["full_name"] == "org/r"
    ok, rows = manager.list_repos(limit=1)
    assert ok is True and rows[0]["private"] == "true"
    manager._gh = None
    assert manager.list_repos() == (False, [])


def test_list_repos_limit_break_and_exception(manager):
    repos = [
        SimpleNamespace(full_name="me/r1", default_branch="main", private=False),
        SimpleNamespace(full_name="me/r2", default_branch="dev", private=True),
    ]
    self_account = SimpleNamespace(get_repos=lambda visibility: repos)
    manager._gh = SimpleNamespace(get_user=lambda owner=None: self_account)

    ok, rows = manager.list_repos(limit=0)
    assert ok is True and rows == []

    manager._gh = SimpleNamespace(
        get_user=lambda owner=None: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert manager.list_repos() == (False, [])


def test_get_repo_info_success_and_error(manager):
    manager._repo.get_issues = lambda state: SimpleNamespace(totalCount=5)
    ok, text = manager.get_repo_info()
    assert ok is True and "[Depo Bilgisi]" in text and "Açık PR" in text
    manager._repo = SimpleNamespace(
        full_name="x",
        description=None,
        language=None,
        stargazers_count=1,
        forks_count=2,
        get_pulls=lambda state: (_ for _ in ()).throw(RuntimeError("boom")),
        get_issues=lambda state: SimpleNamespace(totalCount=0),
        default_branch="main",
    )
    ok, msg = manager.get_repo_info()
    assert ok is False and "Depo bilgisi alınamadı" in msg
    manager._repo = None
    assert manager.get_repo_info()[0] is False


def test_list_commits_and_read_remote_file(manager):
    ok, text = manager.list_commits(limit=2, branch="main")
    assert ok is True and "Son 2 Commit" in text
    manager._repo.get_commits = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.list_commits()[0] is False
    manager._repo = RepoMock()
    manager._repo._contents[("dir", None)] = [
        SimpleNamespace(type="dir", name="src"),
        SimpleNamespace(type="file", name="a.py"),
    ]
    ok, text = manager.read_remote_file("dir")
    assert ok is True and "📂 src" in text
    manager._repo._contents[("bad.bin", None)] = FileMock("bad.bin")
    assert manager.read_remote_file("bad.bin")[0] is False
    manager._repo._contents[("Makefile", None)] = FileMock("Makefile", decoded_content=b"all:\n")
    assert manager.read_remote_file("Makefile") == (True, "all:\n")
    manager._repo._contents[("NOEXT", None)] = FileMock("NOEXT")
    assert manager.read_remote_file("NOEXT")[0] is False


def test_list_commits_handles_large_volume(manager):
    manager._repo.get_commits = lambda **kwargs: [
        SimpleNamespace(
            sha=str(i),
            commit=SimpleNamespace(
                message="msg",
                author=SimpleNamespace(name="a", date=datetime.now()),
            ),
        )
        for i in range(150)
    ]
    ok, text = manager.list_commits(limit=50, branch="main")
    assert ok is True
    commit_lines = [line for line in text.splitlines() if line.startswith("  ")]
    assert len(commit_lines) == 50


def test_read_remote_file_decode_and_exception_paths(manager):
    class BadDecode:
        name = "ok.txt"

        @property
        def decoded_content(self):
            raise UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")

    manager._repo._contents[("ok.txt", None)] = BadDecode()
    ok, msg = manager.read_remote_file("ok.txt")
    assert ok is False and "UTF-8" in msg
    manager._repo._contents[("missing.txt", None)] = RuntimeError("oops")
    assert "Uzak dosya okunamadı" in manager.read_remote_file("missing.txt")[1]


def test_read_remote_file_with_ref_kwarg(manager):
    manager._repo._contents[("ok.txt", "feat/x")] = FileMock("ok.txt", decoded_content=b"hello ref")
    ok, content = manager.read_remote_file("ok.txt", ref="feat/x")
    assert (ok, content) == (True, "hello ref")


def test_branches_and_files_listing(manager):
    ok, text = manager.list_branches(limit=5)
    assert ok is True and "* main" in text
    manager._repo.get_branches = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.list_branches()[0] is False
    manager._repo = RepoMock()
    manager._repo._contents[("", None)] = [
        SimpleNamespace(type="file", name="z.py"),
        SimpleNamespace(type="dir", name="a"),
    ]
    ok, text = manager.list_files()
    assert ok is True and text.splitlines()[1].endswith("a")
    manager._repo.get_contents = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    assert manager.list_files()[0] is False


def test_list_files_branch_and_single_item(manager):
    manager._repo._contents[("README.md", "dev")] = FileMock("README.md")
    ok, text = manager.list_files(path="README.md", branch="dev")
    assert ok is True and "README.md" in text


def test_create_or_update_file_paths(manager):
    manager._repo._contents[("x.txt", None)] = FileMock("x.txt", sha="s1")
    ok, msg = manager.create_or_update_file("x.txt", "new", "m")
    assert ok is True and "güncellendi" in msg and manager._repo.update_calls
    manager._repo._contents[("y.txt", None)] = Err404("no")
    ok, msg = manager.create_or_update_file("y.txt", "new", "m", branch="dev")
    assert ok is True and "oluşturuldu" in msg and manager._repo.create_calls[-1]["branch"] == "dev"
    manager._repo._contents[("z.txt", None)] = RuntimeError("other")
    assert manager.create_or_update_file("z.txt", "new", "m")[0] is False


def test_create_or_update_file_write_exception(manager):
    manager._repo._contents[("x.txt", None)] = FileMock("x.txt", sha="s1")
    manager._repo.update_file = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("write boom"))
    ok, msg = manager.create_or_update_file("x.txt", "new", "msg")
    assert ok is False and "GitHub dosya yazma hatası" in msg


def test_branch_and_pr_operations(manager):
    assert manager.create_branch("bad name")[0] is False
    ok, _ = manager.create_branch("feat/x", from_branch="main")
    assert ok is True and manager._repo.git_ref_call["ref"].endswith("feat/x")
    assert manager.create_branch("feat/x", from_branch="boom")[0] is False

    ok, text = manager.create_pull_request("Title", "Body", "feat/x")
    assert ok is True and "URL" in text
    assert manager.create_pull_request("boom", "Body", "feat/x")[0] is False


def test_list_and_get_prs_and_comments(manager):
    pr = PRMock(many_files=True)
    manager._repo._pulls = [pr]
    ok, text = manager.list_pull_requests(state="OPEN", limit=1)
    assert ok is True and "PR Listesi (OPEN)" in text
    manager._repo._pulls = []
    ok, text = manager.list_pull_requests(state="unknown")
    assert ok is True and "Hiç open PR" in text
    manager._repo.get_pulls = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.list_pull_requests()[0] is False

    manager._repo = RepoMock()
    manager._repo._pulls = [pr]
    ok, detail = manager.get_pull_request(5)
    assert ok is True and "(+5 dosya daha)" in detail
    assert manager.get_pull_request(999)[0] is False

    manager._repo._issues = [IssueMock(number=5)]
    ok, msg = manager.add_pr_comment(5, "LGTM")
    assert ok is True and "Yorum eklendi" in msg
    assert manager.add_pr_comment(999, "x")[0] is False

    manager._repo._pulls = [pr]
    ok, msg = manager.close_pull_request(5)
    assert ok is True and pr.edits == ["closed"]
    assert manager.close_pull_request(999)[0] is False


def test_issue_related_methods(manager):
    issue = IssueMock(number=1, title="bug")
    manager._repo._issues = [issue, IssueMock(number=2, is_pr=True)]
    ok, items = manager.list_issues(state="OPEN", limit=10)
    assert ok is True and len(items) == 1 and items[0]["number"] == 1
    manager._repo.get_issues = lambda state: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.list_issues()[0] is False

    ok, msg = manager.create_issue("new", "body")
    assert ok is True and "#9" in msg
    assert manager.create_issue("boom", "body")[0] is False

    manager._repo._issues = [issue]
    assert manager.comment_issue(1, "x")[0] is True
    assert manager.comment_issue(999, "x")[0] is False
    assert manager.close_issue(1)[0] is True and issue.edited_state == "closed"
    assert manager.close_issue(999)[0] is False


def test_diff_files_search_status_and_repr(manager, caplog):
    pr = PRMock(many_files=False)
    manager._repo._pulls = [pr]
    ok, diff = manager.get_pull_request_diff(5)
    assert ok is True and "ikili/binary" in diff
    manager._repo._pulls = [SimpleNamespace(title="Empty", get_files=lambda: [])]
    assert manager.get_pull_request_diff(5)[1].startswith("Bu PR")
    manager._repo.get_pull = lambda n: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.get_pull_request_diff(1)[0] is False

    manager._repo = RepoMock()
    manager._repo._pulls = [pr]
    ok, files = manager.get_pr_files(5)
    assert ok is True and "Değişen Dosyalar" in files
    assert manager.get_pr_files(999)[0] is False

    manager._gh = SimpleNamespace(search_code=lambda q: [SimpleNamespace(path="a.py")])
    ok, out = manager.search_code("foo")
    assert ok is True and "a.py" in out
    manager._gh = SimpleNamespace(search_code=lambda q: [])
    assert manager.search_code("foo")[1].endswith("sonuç bulunamadı.")
    manager._gh = SimpleNamespace(search_code=lambda q: (_ for _ in ()).throw(RuntimeError("boom")))
    assert manager.search_code("foo")[0] is False

    manager._available = False
    manager.token = ""
    assert "Token eklemek" in manager.status()
    manager.token = "abc"
    assert "geçersiz" in manager.status()
    manager._available = True
    manager.repo_name = "octo/demo"
    assert manager.status() == "GitHub: Bağlı | Depo: octo/demo"
    assert manager.default_branch == "main"
    assert "GitHubManager" in repr(manager)


def test_get_pull_requests_detailed_and_unavailable(manager):
    pr = PRMock()
    manager._repo._pulls = [pr]
    ok, data, err = manager.get_pull_requests_detailed(state="open", limit=1)
    assert ok is True and err == "" and data[0]["author"] == "alice"
    manager._repo.get_pulls = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.get_pull_requests_detailed()[0] is False
    manager._repo = None
    assert manager.get_pull_requests_detailed()[0] is False


def test_methods_when_repo_or_connection_missing(monkeypatch):
    monkeypatch.setattr(GitHubManager, "_init_client", lambda self: None)
    m = GitHubManager("x")
    m._repo = None
    m._gh = None
    m._available = False
    assert m.list_commits()[0] is False
    assert m.read_remote_file("x")[0] is False
    assert m.list_branches()[0] is False
    assert m.list_files()[0] is False
    assert m.create_or_update_file("a", "b", "c")[0] is False
    assert m.create_branch("a")[0] is False
    assert m.create_pull_request("t", "b", "h")[0] is False
    assert m.list_pull_requests()[0] is False
    assert m.get_pull_request(1)[0] is False
    assert m.add_pr_comment(1, "x")[0] is False
    assert m.close_pull_request(1)[0] is False
    assert m.list_issues()[0] is False
    assert m.create_issue("x", "y")[0] is False
    assert m.comment_issue(1, "x")[0] is False
    assert m.close_issue(1)[0] is False
    assert m.get_pull_request_diff(1)[0] is False
    assert m.get_pr_files(1)[0] is False
    assert m.search_code("q")[0] is False


def test_init_client_import_error_and_generic_error(monkeypatch):
    # ImportError branch: inject a non-module sentinel into sys.modules.
    monkeypatch.setitem(sys.modules, "github", None)
    GitHubManager(token="tok")

    class _FakeAuth:
        @staticmethod
        def Token(token):
            return token

    class _BadGithub:
        def __init__(self, auth):
            raise RuntimeError("connect boom")

    monkeypatch.setitem(sys.modules, "github", SimpleNamespace(Auth=_FakeAuth, Github=_BadGithub))
    GitHubManager(token="tok")


def test_init_client_success_with_repo_load(monkeypatch):
    class _FakeAuth:
        @staticmethod
        def Token(token):
            return f"AUTH:{token}"

    class _FakeGithub:
        def __init__(self, auth):
            self.auth = auth

        def get_user(self, owner=None):
            return SimpleNamespace(login="alice")

        def get_repo(self, name):
            return SimpleNamespace(full_name=name, default_branch="main")

    monkeypatch.setitem(sys.modules, "github", SimpleNamespace(Auth=_FakeAuth, Github=_FakeGithub))
    m = GitHubManager(token=" tok ", repo_name="octo/demo")
    assert m.is_available() is True
    assert m.repo_name == "octo/demo"


def test_repo_mock_error_branches_for_coverage():
    repo = RepoMock()

    with pytest.raises(RuntimeError, match="commit boom"):
        repo.get_commits(raise_exc=True)

    with pytest.raises(RuntimeError, match="missing"):
        repo.get_contents("does-not-exist")
