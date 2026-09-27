"""PyGithub stand-ins shared by GitHub manager tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


class Err404(Exception):
    """Exception carrying a 404 status, like PyGithub's not-found error."""

    status = 404


class FileMock:
    """PyGithub content/file object stand-in."""

    def __init__(self, name, file_type="file", decoded_content=b"hello", sha="sha1", patch="@@"):
        """Store the file metadata and fixed diff statistics."""
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
    """PyGithub issue stand-in that records comments and state edits."""

    def __init__(self, number=1, title="Issue", state="open", user="u", created=None, is_pr=False):
        """Store issue fields; ``is_pr`` marks the issue as a pull request."""
        self.number = number
        self.title = title
        self.state = state
        self.user = SimpleNamespace(login=user)
        self.created_at = created or datetime(2026, 1, 1, 10, 0)
        self.pull_request = object() if is_pr else None
        self.comments = []
        self.edited_state = None

    def create_comment(self, body):
        """Record the comment and return an object with its URL."""
        self.comments.append(body)
        return SimpleNamespace(html_url="https://example/comment/1")

    def edit(self, state):
        """Record the requested state change."""
        self.edited_state = state


class RepoMock:
    """PyGithub repository stand-in with configurable pulls, issues and contents."""

    def __init__(self):
        """Set fixed repository metadata and empty collections and call logs."""
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
        """Return a count object for open-pull queries, otherwise the stored pulls."""
        if kwargs.get("state") == "open" and "sort" not in kwargs:
            return SimpleNamespace(totalCount=7)
        return self._pulls

    def get_issues(self, **kwargs):
        """Return the stored issues."""
        return self._issues

    def get_commits(self, **kwargs):
        """Return fake commits, or raise when ``raise_exc`` is passed."""
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
        """Return stored contents for the path and ref; stored exceptions are raised."""
        key = (path, kwargs.get("ref") or kwargs.get("branch"))
        value = self._contents.get(key, self._contents.get((path, None)))
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise RuntimeError("missing")
        return value

    def update_file(self, **kwargs):
        """Record the ``update_file`` call arguments."""
        self.update_calls.append(kwargs)

    def create_file(self, **kwargs):
        """Record the ``create_file`` call arguments."""
        self.create_calls.append(kwargs)

    def get_branch(self, name):
        """Return a branch whose commit SHA is ``base123``; ``boom`` raises."""
        if name == "boom":
            raise RuntimeError("branch boom")
        return SimpleNamespace(commit=SimpleNamespace(sha="base123"))

    def create_git_ref(self, **kwargs):
        """Record the ``create_git_ref`` call arguments."""
        self.git_ref_call = kwargs

    def create_pull(self, **kwargs):
        """Return a fake created pull request; the title ``boom`` raises."""
        if kwargs.get("title") == "boom":
            raise RuntimeError("pr boom")
        return SimpleNamespace(title=kwargs["title"], html_url="https://example/pr/1", number=1)

    def get_pull(self, number):
        """Return the first stored pull; number 999 raises."""
        if number == 999:
            raise RuntimeError("no pr")
        return self._pulls[0]

    def get_issue(self, number=None):
        """Return the first stored issue; number 999 raises."""
        if number == 999:
            raise RuntimeError("no issue")
        return self._issues[0]

    def create_issue(self, title, body):
        """Return a fake created issue; the title ``boom`` raises."""
        if title == "boom":
            raise RuntimeError("create issue boom")
        return SimpleNamespace(number=9, title=title)

    def get_branches(self):
        """Return the ``dev`` and ``main`` branches."""
        return [SimpleNamespace(name="dev"), SimpleNamespace(name="main")]


class PRMock:
    """PyGithub pull request stand-in with fixed metadata and files."""

    def __init__(self, many_files=False):
        """Set fixed pull request metadata; ``many_files`` creates 25 files instead of 2."""
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
        """Return the pull request files."""
        return self._files

    def edit(self, state):
        """Record the requested state change."""
        self.edits.append(state)
