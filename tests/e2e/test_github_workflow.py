"""E2E-style GitHub workflow coverage with an in-memory repository double."""

from __future__ import annotations

from types import SimpleNamespace

from managers.github_manager import GitHubManager


class _ProtectedBranchError(Exception):
    status = 405


class _FakeComment:
    html_url = "https://github.example/acme/repo/pull/7#issuecomment-1"


class _FakeIssue:
    def __init__(self) -> None:
        self.comments: list[str] = []

    def create_comment(self, body: str) -> _FakeComment:
        self.comments.append(body)
        return _FakeComment()


class _FakePullRequest:
    def __init__(self, *, protected: bool = False) -> None:
        self.title = "Improve workflow"
        self.html_url = "https://github.example/acme/repo/pull/7"
        self.number = 7
        self.protected = protected
        self.merged = False
        self.merge_calls: list[dict[str, str]] = []

    def merge(self, commit_message: str = "", merge_method: str = "merge"):
        self.merge_calls.append({"commit_message": commit_message, "merge_method": merge_method})
        if self.protected:
            raise _ProtectedBranchError("Protected branch update failed: required checks pending")
        self.merged = True
        return SimpleNamespace(merged=True, message="Pull Request successfully merged")


class _FakeRepo:
    default_branch = "main"

    def __init__(self) -> None:
        self.created_refs: list[tuple[str, str]] = []
        self.created_pulls: list[dict[str, str]] = []
        self.issue = _FakeIssue()
        self.protected_pr = _FakePullRequest(protected=True)
        self.mergeable_pr = _FakePullRequest(protected=False)

    def get_branch(self, name: str):
        assert name == "main"
        return SimpleNamespace(commit=SimpleNamespace(sha="abc123"))

    def create_git_ref(self, ref: str, sha: str) -> None:
        self.created_refs.append((ref, sha))

    def create_pull(self, title: str, body: str, head: str, base: str):
        self.created_pulls.append({"title": title, "body": body, "head": head, "base": base})
        return self.mergeable_pr

    def get_issue(self, number: int) -> _FakeIssue:
        assert number == 7
        return self.issue

    def get_pull(self, number: int) -> _FakePullRequest:
        assert number in {7, 8}
        return self.protected_pr if number == 7 else self.mergeable_pr


def test_github_pr_create_comment_merge_and_branch_protection_flow() -> None:
    repo = _FakeRepo()
    manager = GitHubManager(token="", repo_name="")
    manager._repo = repo

    branch_ok, branch_msg = manager.create_branch("feature/e2e-flow")
    pr_ok, pr_msg = manager.create_pull_request(
        title="Improve workflow",
        body="Adds an e2e workflow test",
        head="feature/e2e-flow",
        base="main",
    )
    comment_ok, comment_msg = manager.add_pr_comment(7, "Looks good after e2e checks")
    protected_ok, protected_msg = manager.merge_pull_request(
        7,
        commit_message="Try protected merge",
        merge_method="squash",
    )
    merge_ok, merge_msg = manager.merge_pull_request(
        8,
        commit_message="Merge validated workflow",
        merge_method="squash",
    )

    assert branch_ok is True
    assert repo.created_refs == [("refs/heads/feature/e2e-flow", "abc123")]
    assert "Dal oluşturuldu" in branch_msg
    assert pr_ok is True
    assert repo.created_pulls == [
        {
            "title": "Improve workflow",
            "body": "Adds an e2e workflow test",
            "head": "feature/e2e-flow",
            "base": "main",
        }
    ]
    assert "#7" in pr_msg
    assert comment_ok is True
    assert repo.issue.comments == ["Looks good after e2e checks"]
    assert "Yorum eklendi" in comment_msg
    assert protected_ok is False
    assert "branch protection" in protected_msg.lower()
    assert merge_ok is True
    assert repo.mergeable_pr.merged is True
    assert repo.mergeable_pr.merge_calls[-1] == {
        "commit_message": "Merge validated workflow",
        "merge_method": "squash",
    }
    assert "merge edildi" in merge_msg
