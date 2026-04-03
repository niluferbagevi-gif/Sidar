from __future__ import annotations

from types import SimpleNamespace

from managers.github_manager import GitHubManager


class _GHManagerNoInit(GitHubManager):
    def _init_client(self) -> None:
        self._gh = None
        self._repo = None
        self._available = False


class _RepoStub:
    default_branch = "main"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_pull(self, **kwargs):
        self.calls.append(("create_pull", kwargs))
        return SimpleNamespace(title=kwargs["title"], html_url="https://example/pr/1", number=1)

    def get_issue(self, number: int):
        self.calls.append(("get_issue", number))
        return SimpleNamespace(create_comment=lambda text: SimpleNamespace(html_url=f"https://example/comment/{text}"))

    def create_issue(self, title: str, body: str):
        self.calls.append(("create_issue", title, body))
        return SimpleNamespace(number=99, title=title)


def test_create_pull_request_uses_default_branch_when_base_missing() -> None:
    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = _RepoStub()

    ok, message = manager.create_pull_request(title="feat", body="desc", head="feature/x")

    assert ok is True
    assert "Pull Request oluşturuldu" in message
    assert manager._repo.calls[0][1]["base"] == "main"


def test_add_pr_comment_and_create_issue_messages() -> None:
    manager = _GHManagerNoInit(token="t", repo_name="", require_token=False)
    manager._repo = _RepoStub()

    ok_comment, msg_comment = manager.add_pr_comment(7, "LGTM")
    ok_issue, msg_issue = manager.create_issue("Bug", "Fix me")

    assert ok_comment is True
    assert "comment/LGTM" in msg_comment
    assert ok_issue is True
    assert "#99" in msg_issue
