"""Smart pull-request tool implementation for SidarAgent."""

from __future__ import annotations

from typing import Protocol

GITHUB_SMART_PR_NO_TOKEN_MESSAGE = "⚠ GitHub token bulunamadı."  # nosec B105
GITHUB_SMART_PR_NO_BRANCH_MESSAGE = "✗ Aktif branch bulunamadı."
GITHUB_SMART_PR_NO_CHANGES_MESSAGE = "ℹ Değişiklik bulunamadı; PR oluşturulmadı."
GITHUB_SMART_PR_CREATE_FAILED_PREFIX = "✗ PR oluşturulamadı:"
GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX = "✓ PR oluşturuldu:"


class _CodeManagerLike(Protocol):
    def run_shell(self, command: str) -> tuple[bool, str]: ...


class _GitHubManagerLike(Protocol):
    @property
    def default_branch(self) -> str: ...

    def is_available(self) -> bool: ...

    def create_pull_request(
        self, title: str, body: str, head: str, base: str
    ) -> tuple[bool, str]: ...


async def create_smart_pr(
    *,
    arg: str,
    code: _CodeManagerLike,
    github: _GitHubManagerLike,
    max_diff_chars: int = 10000,
) -> str:
    """Create a GitHub PR from the current working tree diff."""
    if not github.is_available():
        return GITHUB_SMART_PR_NO_TOKEN_MESSAGE

    parts = [p.strip() for p in (arg or "").split("|||")]
    title = parts[0] if len(parts) > 0 and parts[0] else "Otomatik PR"
    base = parts[1] if len(parts) > 1 and parts[1] else ""
    notes = parts[2] if len(parts) > 2 else ""

    ok, branch = code.run_shell("git branch --show-current")
    head = (branch or "").strip() if ok else ""
    if not head:
        return GITHUB_SMART_PR_NO_BRANCH_MESSAGE

    if not base:
        try:
            base = github.default_branch
        except Exception:
            base = "main"

    ok_status, status_out = code.run_shell("git status --short")
    if not ok_status or not str(status_out).strip():
        return GITHUB_SMART_PR_NO_CHANGES_MESSAGE

    code.run_shell("git diff --stat HEAD")
    ok_diff, diff_out = code.run_shell("git diff --no-color HEAD")
    diff_text = str(diff_out or "") if ok_diff else ""
    if len(diff_text) > max_diff_chars:
        diff_text = (
            diff_text[:max_diff_chars]
            + "\n\n[Not] Diff çok büyük olduğu için geri kalanı kırpıldı."
        )

    _ok_log, commits = code.run_shell(f"git log --oneline {base}..HEAD")
    body = f"{notes}\n\n### Commitler\n{commits}\n\n### Diff Özeti\n```diff\n{diff_text}\n```"
    try:
        ok_pr, pr_out = github.create_pull_request(title, body, head, base)
    except TimeoutError:
        return f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} zaman aşımı"
    except Exception as exc:
        return f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} {exc}"

    if not ok_pr:
        reason = str(pr_out or "bilinmeyen hata")
        return f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} {reason}"
    return f"{GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX} {pr_out}"
