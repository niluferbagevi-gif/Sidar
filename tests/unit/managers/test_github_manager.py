from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from managers.github_manager import GitHubManager, _is_not_found_error


class _Err404(Exception):
    status = 404


class _File:
    def __init__(self, name, file_type="file", decoded_content=b"hello", sha="sha1", patch="@@"):
        self.name = name
        self.type = file_type
        self.decoded_content = decoded_content
        self.sha = sha
        self.patch = patch
        self.filename = name
        self.status = "modified"
        self.additions = 3
        self.deletions = 1


class _Issue:
    def __init__(self, number=1, title="Issue", state="open", user="u", created=None, is_pr=False):
        self.number = number
        self.title = title
        self.state = state
        self.user = SimpleNamespace(login=user)
        self.created_at = created or datetime(2026, 1, 1, 10, 0)
        self.pull_request = object() if is_pr else None
        self.comments = []
        self.edited_state = None

    def create_comment(self, body):
        self.comments.append(body)
        return SimpleNamespace(html_url="https://example/comment/1")

    def edit(self, state):
        self.edited_state = state


class _Repo:
    def __init__(self):
        self.full_name = "octo/demo"
        self.description = "Demo"
        self.language = "Python"
        self.stargazers_count = 10
        self.forks_count = 2
        self.default_branch = "main"
        self._pulls = []
        self._issues = []
        self._contents = {}
        self.update_calls = []
        self.create_calls = []

    def get_pulls(self, **kwargs):
        if kwargs.get("state") == "open" and "sort" not in kwargs:
            return SimpleNamespace(totalCount=7)
        return self._pulls

    def get_issues(self, **kwargs):
        return self._issues

    def get_commits(self, **kwargs):
        if kwargs.get("raise_exc"):
            raise RuntimeError("commit boom")
        mk = lambda i: SimpleNamespace(
            sha=f"abcdef{i}",
            commit=SimpleNamespace(
                message=f"msg-{i}\nbody",
                author=SimpleNamespace(name=f"a{i}", date=datetime(2026, 1, i, 9, 0)),
            ),
        )
        return [mk(i) for i in range(1, 6)]

    def get_contents(self, path, **kwargs):
        key = (path, kwargs.get("ref") or kwargs.get("branch"))
        value = self._contents.get(key, self._contents.get((path, None)))
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise RuntimeError("missing")
        return value

    def update_file(self, **kwargs):
        self.update_calls.append(kwargs)

    def create_file(self, **kwargs):
        self.create_calls.append(kwargs)

    def get_branch(self, name):
        if name == "boom":
            raise RuntimeError("branch boom")
        return SimpleNamespace(commit=SimpleNamespace(sha="base123"))

    def create_git_ref(self, **kwargs):
        self.git_ref_call = kwargs

    def create_pull(self, **kwargs):
        if kwargs.get("title") == "boom":
            raise RuntimeError("pr boom")
        return SimpleNamespace(title=kwargs["title"], html_url="https://example/pr/1", number=1)

    def get_pull(self, number):
        if number == 999:
            raise RuntimeError("no pr")
        return self._pulls[0]

    def get_issue(self, number=None):
        if number == 999:
            raise RuntimeError("no issue")
        return self._issues[0]

    def create_issue(self, title, body):
        if title == "boom":
            raise RuntimeError("create issue boom")
        return SimpleNamespace(number=9, title=title)

    def get_branches(self):
        return [SimpleNamespace(name="dev"), SimpleNamespace(name="main")]


class _PR:
    def __init__(self, many_files=False):
        self.number = 5
        self.title = "Fix bug"
        self.state = "open"
        self.user = SimpleNamespace(login="alice")
        self.head = SimpleNamespace(ref="feature")
        self.base = SimpleNamespace(ref="main")
        self.created_at = datetime(2026, 1, 2, 10, 0)
        self.updated_at = datetime(2026, 1, 3, 11, 0)
        self.additions = 12
        self.deletions = 3
        self.changed_files = 2
        self.comments = 1
        self.html_url = "https://example/pr/5"
        self.body = "details"
        if many_files:
            self._files = [_File(f"f{i}.py") for i in range(25)]
        else:
            self._files = [_File("a.py", patch="@@ -1 +1 @@"), _File("b.bin", patch=None)]
        self.edits = []

    def get_files(self):
        return self._files

    def edit(self, state):
        self.edits.append(state)


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(GitHubManager, "_init_client", lambda self: None)
    m = GitHubManager(token=" token\u00f6 ", repo_name="", require_token=False)
    m._available = True
    m._gh = SimpleNamespace()
    m._repo = _Repo()
    return m


def test_is_not_found_error_variants():
    assert _is_not_found_error(_Err404("x")) is True
    assert _is_not_found_error(RuntimeError("404 gone")) is True
    assert _is_not_found_error(RuntimeError("Not Found")) is True
    assert _is_not_found_error(RuntimeError("boom")) is False


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
    manager._gh = SimpleNamespace(get_user=lambda owner=None: org_account if owner else self_account)
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

    manager._gh = SimpleNamespace(get_user=lambda owner=None: (_ for _ in ()).throw(RuntimeError("boom")))
    assert manager.list_repos() == (False, [])


def test_get_repo_info_success_and_error(manager):
    manager._repo.get_issues = lambda state: SimpleNamespace(totalCount=5)
    ok, text = manager.get_repo_info()
    assert ok is True and "[Depo Bilgisi]" in text and "Açık PR" in text
    manager._repo = SimpleNamespace(full_name="x", description=None, language=None, stargazers_count=1, forks_count=2,
                                    get_pulls=lambda state: (_ for _ in ()).throw(RuntimeError("boom")),
                                    get_issues=lambda state: SimpleNamespace(totalCount=0), default_branch="main")
    ok, msg = manager.get_repo_info()
    assert ok is False and "Depo bilgisi alınamadı" in msg
    manager._repo = None
    assert manager.get_repo_info()[0] is False


def test_list_commits_and_read_remote_file(manager):
    ok, text = manager.list_commits(limit=2, branch="main")
    assert ok is True and "Son 2 Commit" in text
    manager._repo.get_commits = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.list_commits()[0] is False
    manager._repo = _Repo()
    manager._repo._contents[("dir", None)] = [SimpleNamespace(type="dir", name="src"), SimpleNamespace(type="file", name="a.py")]
    ok, text = manager.read_remote_file("dir")
    assert ok is True and "📂 src" in text
    manager._repo._contents[("bad.bin", None)] = _File("bad.bin")
    assert manager.read_remote_file("bad.bin")[0] is False
    manager._repo._contents[("Makefile", None)] = _File("Makefile", decoded_content=b"all:\n")
    assert manager.read_remote_file("Makefile") == (True, "all:\n")
    manager._repo._contents[("NOEXT", None)] = _File("NOEXT")
    assert manager.read_remote_file("NOEXT")[0] is False


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
    manager._repo._contents[("ok.txt", "feat/x")] = _File("ok.txt", decoded_content=b"hello ref")
    ok, content = manager.read_remote_file("ok.txt", ref="feat/x")
    assert (ok, content) == (True, "hello ref")


def test_branches_and_files_listing(manager):
    ok, text = manager.list_branches(limit=5)
    assert ok is True and "* main" in text
    manager._repo.get_branches = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.list_branches()[0] is False
    manager._repo = _Repo()
    manager._repo._contents[("", None)] = [SimpleNamespace(type="file", name="z.py"), SimpleNamespace(type="dir", name="a")]
    ok, text = manager.list_files()
    assert ok is True and text.splitlines()[1].endswith("a")
    manager._repo.get_contents = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    assert manager.list_files()[0] is False


def test_list_files_branch_and_single_item(manager):
    manager._repo._contents[("README.md", "dev")] = _File("README.md")
    ok, text = manager.list_files(path="README.md", branch="dev")
    assert ok is True and "README.md" in text


def test_create_or_update_file_paths(manager):
    manager._repo._contents[("x.txt", None)] = _File("x.txt", sha="s1")
    ok, msg = manager.create_or_update_file("x.txt", "new", "m")
    assert ok is True and "güncellendi" in msg and manager._repo.update_calls
    manager._repo._contents[("y.txt", None)] = _Err404("no")
    ok, msg = manager.create_or_update_file("y.txt", "new", "m", branch="dev")
    assert ok is True and "oluşturuldu" in msg and manager._repo.create_calls[-1]["branch"] == "dev"
    manager._repo._contents[("z.txt", None)] = RuntimeError("other")
    assert manager.create_or_update_file("z.txt", "new", "m")[0] is False


def test_create_or_update_file_write_exception(manager):
    manager._repo._contents[("x.txt", None)] = _File("x.txt", sha="s1")
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
    pr = _PR(many_files=True)
    manager._repo._pulls = [pr]
    ok, text = manager.list_pull_requests(state="OPEN", limit=1)
    assert ok is True and "PR Listesi (OPEN)" in text
    manager._repo._pulls = []
    ok, text = manager.list_pull_requests(state="unknown")
    assert ok is True and "Hiç open PR" in text
    manager._repo.get_pulls = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.list_pull_requests()[0] is False

    manager._repo = _Repo()
    manager._repo._pulls = [pr]
    ok, detail = manager.get_pull_request(5)
    assert ok is True and "(+5 dosya daha)" in detail
    assert manager.get_pull_request(999)[0] is False

    manager._repo._issues = [_Issue(number=5)]
    ok, msg = manager.add_pr_comment(5, "LGTM")
    assert ok is True and "Yorum eklendi" in msg
    assert manager.add_pr_comment(999, "x")[0] is False

    manager._repo._pulls = [pr]
    ok, msg = manager.close_pull_request(5)
    assert ok is True and pr.edits == ["closed"]
    assert manager.close_pull_request(999)[0] is False


def test_issue_related_methods(manager):
    issue = _Issue(number=1, title="bug")
    manager._repo._issues = [issue, _Issue(number=2, is_pr=True)]
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
    pr = _PR(many_files=False)
    manager._repo._pulls = [pr]
    ok, diff = manager.get_pull_request_diff(5)
    assert ok is True and "ikili/binary" in diff
    manager._repo._pulls = [SimpleNamespace(title="Empty", get_files=lambda: [])]
    assert manager.get_pull_request_diff(5)[1].startswith("Bu PR")
    manager._repo.get_pull = lambda n: (_ for _ in ()).throw(RuntimeError("boom"))
    assert manager.get_pull_request_diff(1)[0] is False

    manager._repo = _Repo()
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
    pr = _PR()
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
    def bad_import(*args, **kwargs):
        raise ImportError("no github")

    monkeypatch.setitem(__import__("sys").modules, "github", None)
    real_import = __import__("builtins").__import__

    def fake_import(name, *args, **kwargs):
        if name == "github":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(__import__("builtins"), "__import__", fake_import)
    GitHubManager(token="tok")

    class _FakeAuth:
        @staticmethod
        def Token(token):
            return token

    class _BadGithub:
        def __init__(self, auth):
            raise RuntimeError("connect boom")

    monkeypatch.setattr(__import__("builtins"), "__import__", real_import)
    monkeypatch.setitem(__import__("sys").modules, "github", SimpleNamespace(Auth=_FakeAuth, Github=_BadGithub))
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

    monkeypatch.setitem(__import__("sys").modules, "github", SimpleNamespace(Auth=_FakeAuth, Github=_FakeGithub))
    m = GitHubManager(token=" tok ", repo_name="octo/demo")
    assert m.is_available() is True
    assert m.repo_name == "octo/demo"
