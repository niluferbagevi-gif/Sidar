from __future__ import annotations

import asyncio

from agent.github.smart_pr import (
    GITHUB_SMART_PR_CREATE_FAILED_PREFIX,
    GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX,
    GITHUB_SMART_PR_NO_BRANCH_MESSAGE,
    GITHUB_SMART_PR_NO_CHANGES_MESSAGE,
    GITHUB_SMART_PR_NO_TOKEN_MESSAGE,
    _CodeManagerLike,
    _GitHubManagerLike,
    create_smart_pr,
)


class FakeCodeManager:
    def __init__(self, outputs: dict[str, tuple[bool, str]]) -> None:
        self.outputs = outputs
        self.commands: list[str] = []

    def run_shell(self, command: str) -> tuple[bool, str]:
        self.commands.append(command)
        for key, output in self.outputs.items():
            if key in command:
                return output
        return True, ""


class FakeGitHubManager:
    def __init__(
        self,
        *,
        available: bool = True,
        default_branch: str = "main",
        default_branch_exc: Exception | None = None,
        create_result: tuple[bool, str] = (True, "https://github.test/pr/1"),
        create_exc: Exception | None = None,
    ) -> None:
        self.available = available
        self._default_branch = default_branch
        self.default_branch_exc = default_branch_exc
        self.create_result = create_result
        self.create_exc = create_exc
        self.created: list[tuple[str, str, str, str]] = []

    @property
    def default_branch(self) -> str:
        if self.default_branch_exc is not None:
            raise self.default_branch_exc
        return self._default_branch

    def is_available(self) -> bool:
        return self.available

    def create_pull_request(self, title: str, body: str, head: str, base: str) -> tuple[bool, str]:
        self.created.append((title, body, head, base))
        if self.create_exc is not None:
            raise self.create_exc
        return self.create_result


def _changed_code(diff: str = "diff --git a/a.py b/a.py") -> FakeCodeManager:
    return FakeCodeManager(
        {
            "branch --show-current": (True, "feature/smart-pr\n"),
            "status --short": (True, " M a.py\n"),
            "diff --stat": (True, " a.py | 1 +"),
            "diff --no-color": (True, diff),
            "log --oneline": (True, "abc123 change"),
        }
    )


def test_create_smart_pr_requires_available_github_token() -> None:
    result = asyncio.run(
        create_smart_pr(
            arg="title", code=_changed_code(), github=FakeGitHubManager(available=False)
        )
    )

    assert result == GITHUB_SMART_PR_NO_TOKEN_MESSAGE


def test_create_smart_pr_requires_current_branch() -> None:
    code = FakeCodeManager({"branch --show-current": (True, "\n")})

    result = asyncio.run(create_smart_pr(arg="title", code=code, github=FakeGitHubManager()))

    assert result == GITHUB_SMART_PR_NO_BRANCH_MESSAGE


def test_create_smart_pr_skips_when_worktree_has_no_changes() -> None:
    code = FakeCodeManager(
        {
            "branch --show-current": (True, "feature/no-changes"),
            "status --short": (True, ""),
        }
    )

    result = asyncio.run(create_smart_pr(arg="title", code=code, github=FakeGitHubManager()))

    assert result == GITHUB_SMART_PR_NO_CHANGES_MESSAGE


def test_create_smart_pr_defaults_base_to_main_when_default_branch_property_fails() -> None:
    github = FakeGitHubManager(default_branch_exc=RuntimeError("default branch unavailable"))

    result = asyncio.run(create_smart_pr(arg="title", code=_changed_code(), github=github))

    assert result == f"{GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX} https://github.test/pr/1"
    assert github.created[0][3] == "main"


def test_create_smart_pr_truncates_large_diff_in_pr_body() -> None:
    github = FakeGitHubManager()
    large_diff = "x" * 20

    result = asyncio.run(
        create_smart_pr(
            arg="title|||main|||notes",
            code=_changed_code(diff=large_diff),
            github=github,
            max_diff_chars=5,
        )
    )

    assert result.startswith(GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX)
    body = github.created[0][1]
    assert "notes" in body
    assert "xxxxx\n\n[Not] Diff çok büyük olduğu için geri kalanı kırpıldı." in body
    assert large_diff not in body


def test_create_smart_pr_reports_create_timeout() -> None:
    result = asyncio.run(
        create_smart_pr(
            arg="title|||main|||notes",
            code=_changed_code(),
            github=FakeGitHubManager(create_exc=TimeoutError("slow")),
        )
    )

    assert result == f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} zaman aşımı"


def test_create_smart_pr_reports_generic_create_exception() -> None:
    result = asyncio.run(
        create_smart_pr(
            arg="title|||main|||notes",
            code=_changed_code(),
            github=FakeGitHubManager(create_exc=RuntimeError("api exploded")),
        )
    )

    assert result == f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} api exploded"


def test_create_smart_pr_reports_false_create_result_reason() -> None:
    result = asyncio.run(
        create_smart_pr(
            arg="title|||main|||notes",
            code=_changed_code(),
            github=FakeGitHubManager(create_result=(False, "validation failed")),
        )
    )

    assert result == f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} validation failed"


def test_protocol_method_stubs_are_import_coverage_only() -> None:
    assert _CodeManagerLike.run_shell(object(), "git status") is None  # type: ignore[arg-type]
    assert _GitHubManagerLike.default_branch.fget(object()) is None  # type: ignore[union-attr,arg-type]
    assert _GitHubManagerLike.is_available(object()) is None  # type: ignore[arg-type]
    assert _GitHubManagerLike.create_pull_request(object(), "title", "body", "head", "base") is None
