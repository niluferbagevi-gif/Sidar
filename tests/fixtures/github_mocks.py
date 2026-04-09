from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


class Err404(Exception):
    status = 404


class FileMock:
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


class IssueMock:
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


class RepoMock:
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

        def mk(i):
            return SimpleNamespace(
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


class PRMock:
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
            self._files = [FileMock(f"f{i}.py") for i in range(25)]
        else:
            self._files = [FileMock("a.py", patch="@@ -1 +1 @@"), FileMock("b.bin", patch=None)]
        self.edits = []

    def get_files(self):
        return self._files

    def edit(self, state):
        self.edits.append(state)
