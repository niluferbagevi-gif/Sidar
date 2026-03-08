import importlib.util
import types
from datetime import datetime
from pathlib import Path


def _load_module():
    spec = importlib.util.spec_from_file_location("github_manager_under_test", Path("managers/github_manager.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


GM = _load_module()


class FakeRepo:
    def __init__(self):
        self.full_name = "org/repo"
        self.default_branch = "main"
        self.description = "desc"
        self.language = "Python"
        self.stargazers_count = 10
        self.forks_count = 2

    def get_pulls(self, state="open", sort=None):
        if sort == "updated":
            return [
                types.SimpleNamespace(
                    number=1,
                    updated_at=datetime(2024, 1, 2),
                    user=types.SimpleNamespace(login="alice"),
                    title="Fix bug",
                    state="open",
                    head=types.SimpleNamespace(ref="feature"),
                    base=types.SimpleNamespace(ref="main"),
                    created_at=datetime(2024, 1, 1, 10, 0),
                    additions=10,
                    deletions=2,
                    changed_files=1,
                    comments=0,
                    html_url="https://example/pr/1",
                    body="body",
                    get_files=lambda: [
                        types.SimpleNamespace(status="modified", additions=10, deletions=2, filename="a.py", patch="@@")
                    ],
                    edit=lambda state: None,
                )
            ]
        return types.SimpleNamespace(totalCount=3)

    def get_issues(self, state="open"):
        if state == "open":
            return types.SimpleNamespace(totalCount=5)
        return [
            types.SimpleNamespace(
                number=2,
                title="Issue",
                state="open",
                user=types.SimpleNamespace(login="bob"),
                created_at=datetime(2024, 1, 3),
                pull_request=None,
                create_comment=lambda body: None,
                edit=lambda state: None,
            ),
            types.SimpleNamespace(pull_request=object()),
        ]

    def get_commits(self, **kwargs):
        return [
            types.SimpleNamespace(
                sha="abcdef123456",
                commit=types.SimpleNamespace(
                    message="first line\nnext",
                    author=types.SimpleNamespace(name="dev", date=datetime(2024, 1, 1, 9, 0)),
                ),
            )
        ]

    def get_contents(self, file_path, **kwargs):
        if file_path == "docs":
            return [
                types.SimpleNamespace(type="dir", name="subdir"),
                types.SimpleNamespace(type="file", name="README.md"),
            ]
        if file_path == "README.md":
            return types.SimpleNamespace(name="README.md", decoded_content=b"hello")
        if file_path == "Makefile":
            return types.SimpleNamespace(name="Makefile", decoded_content=b"all:\n\techo ok")
        if file_path == "binary.png":
            return types.SimpleNamespace(name="binary.png", decoded_content=b"\x89PNG")
        raise Exception("404 not found")

    def get_branches(self):
        return [types.SimpleNamespace(name="main"), types.SimpleNamespace(name="feature")]

    def create_file(self, **kwargs):
        self.created = kwargs

    def update_file(self, **kwargs):
        self.updated = kwargs

    def get_branch(self, branch):
        return types.SimpleNamespace(commit=types.SimpleNamespace(sha="abc123"))

    def create_git_ref(self, ref, sha):
        self.ref_created = (ref, sha)

    def create_pull(self, title, body, head, base):
        return types.SimpleNamespace(title=title, html_url="https://example/pr/99", number=99)

    def get_pull(self, number):
        pr = self.get_pulls(sort="updated")[0]
        pr.number = number
        return pr

    def get_issue(self, number=None):
        return types.SimpleNamespace(
            create_comment=lambda body: types.SimpleNamespace(html_url="https://example/comment/1"),
            edit=lambda state: None,
        )

    def create_issue(self, title, body):
        return types.SimpleNamespace(number=7, title=title)


def _manager(repo=None, gh=None, available=True, token="t"):
    m = GM.GitHubManager.__new__(GM.GitHubManager)
    m.token = token
    m.repo_name = "org/repo"
    m.require_token = False
    m._repo = repo
    m._gh = gh
    m._available = available
    return m


def test_not_found_helper_variants():
    assert GM._is_not_found_error(Exception("404 not found")) is True
    e = Exception("x")
    e.status = 404
    assert GM._is_not_found_error(e) is True
    assert GM._is_not_found_error(Exception("boom")) is False


def test_set_repo_and_repo_info_and_commits():
    repo = FakeRepo()
    m = _manager(repo=repo)
    m._load_repo = lambda name: name == "org/repo"

    ok, msg = m.set_repo("org/repo")
    assert ok is True and "Depo değiştirildi" in msg

    ok, info = m.get_repo_info()
    assert ok is True and "[Depo Bilgisi] org/repo" in info

    ok, commits = m.list_commits(limit=200, branch="main")
    assert ok is True
    assert "Uyarı" in commits
    assert "abcdef1" in commits


def test_read_remote_file_safety_rules():
    repo = FakeRepo()
    m = _manager(repo=repo)

    ok, listing = m.read_remote_file("docs")
    assert ok is True and "[Dizin: docs]" in listing

    ok, content = m.read_remote_file("README.md")
    assert ok is True and content == "hello"

    ok, mf = m.read_remote_file("Makefile")
    assert ok is True and "echo ok" in mf

    ok, err = m.read_remote_file("binary.png")
    assert ok is False and "binary" in err.lower()


def test_list_files_branches_and_create_update_file_paths():
    repo = FakeRepo()
    m = _manager(repo=repo)

    ok, branches = m.list_branches(limit=5)
    assert ok is True and "* main" in branches

    ok, files = m.list_files(path="docs", branch="main")
    assert ok is True and "README.md" in files

    ok, msg = m.create_or_update_file("new.txt", "a", "add", branch="main")
    assert ok is True and "oluşturuldu" in msg
    assert repo.created["branch"] == "main"

    # update path
    repo.get_contents = lambda file_path, **kwargs: types.SimpleNamespace(sha="sha1")
    ok, msg = m.create_or_update_file("new.txt", "b", "upd")
    assert ok is True and "güncellendi" in msg
    assert repo.updated["sha"] == "sha1"


def test_branch_pr_and_issue_operations():
    repo = FakeRepo()
    m = _manager(repo=repo)

    ok, msg = m.create_branch("feature/test", from_branch="main")
    assert ok is True and "Dal oluşturuldu" in msg
    assert repo.ref_created[0] == "refs/heads/feature/test"

    ok, msg = m.create_branch("bad branch")
    assert ok is False and "Geçersiz dal adı" in msg

    ok, pr_msg = m.create_pull_request("T", "B", "feature/test")
    assert ok is True and "#99" in pr_msg

    ok, pr_list = m.list_pull_requests(state="weird", limit=2)
    assert ok is True and "(OPEN)" in pr_list

    ok, pr_detail = m.get_pull_request(12)
    assert ok is True and "[PR #12" in pr_detail

    ok, cmt = m.add_pr_comment(12, "LGTM")
    assert ok is True and "Yorum eklendi" in cmt

    ok, close = m.close_pull_request(12)
    assert ok is True and "kapatıldı" in close

    ok, issues = m.list_issues(state="all", limit=10)
    assert ok is True and len(issues) == 1

    ok, created = m.create_issue("Bug", "desc")
    assert ok is True and "Issue oluşturuldu" in created

    ok, commented = m.comment_issue(2, "note")
    assert ok is True and "yorum eklendi" in commented

    ok, closed = m.close_issue(2)
    assert ok is True and "kapatıldı" in closed


def test_diff_search_status_defaults_and_detailed_prs():
    repo = FakeRepo()
    gh = types.SimpleNamespace(search_code=lambda q: [types.SimpleNamespace(path="a.py")])
    m = _manager(repo=repo, gh=gh, available=True, token="token")

    ok, diff = m.get_pull_request_diff(1)
    assert ok is True and "DIFF" in diff and "@@" in diff

    ok, files = m.get_pr_files(1)
    assert ok is True and "a.py" in files

    ok, search = m.search_code("needle")
    assert ok is True and "Kod Arama" in search

    assert m.default_branch == "main"
    assert "GitHub: Bağlı" in m.status()

    ok, prs, err = m.get_pull_requests_detailed(state="open", limit=10)
    assert ok is True and err == "" and prs[0]["number"] == 1
    assert "GitHubManager" in repr(m)


def test_status_without_token_or_repo():
    m = _manager(repo=None, gh=None, available=False, token="")
    assert m.is_available() is False
    s = m.status()
    assert "Bağlı değil" in s

    m2 = _manager(repo=None, gh=None, available=False, token="x")
    assert "Token geçersiz" in m2.status()

    m3 = _manager(repo=None, gh=None, available=True, token="x")
    assert m3.default_branch == "main"