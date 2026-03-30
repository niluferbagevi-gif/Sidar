"""
managers/github_manager.py için birim testleri.
_is_not_found_error, GitHubManager.SAFE_TEXT_EXTENSIONS,
GitHubManager.SAFE_EXTENSIONLESS, constructor (no token).
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


def _get_gh():
    if "managers.github_manager" in sys.modules:
        del sys.modules["managers.github_manager"]
    import managers.github_manager as gh
    return gh


# ══════════════════════════════════════════════════════════════
# _is_not_found_error
# ══════════════════════════════════════════════════════════════

class TestIsNotFoundError:
    def test_status_404(self):
        gh = _get_gh()
        exc = Exception("Not found")
        exc.status = 404
        assert gh._is_not_found_error(exc) is True

    def test_message_contains_404(self):
        gh = _get_gh()
        exc = Exception("HTTP 404: not found")
        assert gh._is_not_found_error(exc) is True

    def test_message_contains_not_found(self):
        gh = _get_gh()
        exc = Exception("Not Found")
        assert gh._is_not_found_error(exc) is True

    def test_other_exception_false(self):
        gh = _get_gh()
        exc = Exception("Connection reset")
        assert gh._is_not_found_error(exc) is False

    def test_status_500_false(self):
        gh = _get_gh()
        exc = Exception("Internal error")
        exc.status = 500
        assert gh._is_not_found_error(exc) is False


# ══════════════════════════════════════════════════════════════
# SAFE_TEXT_EXTENSIONS / SAFE_EXTENSIONLESS
# ══════════════════════════════════════════════════════════════

class TestSafeExtensions:
    def test_py_in_safe(self):
        gh = _get_gh()
        assert ".py" in gh.GitHubManager.SAFE_TEXT_EXTENSIONS

    def test_md_in_safe(self):
        gh = _get_gh()
        assert ".md" in gh.GitHubManager.SAFE_TEXT_EXTENSIONS

    def test_json_in_safe(self):
        gh = _get_gh()
        assert ".json" in gh.GitHubManager.SAFE_TEXT_EXTENSIONS

    def test_exe_not_in_safe(self):
        gh = _get_gh()
        assert ".exe" not in gh.GitHubManager.SAFE_TEXT_EXTENSIONS

    def test_makefile_in_extensionless(self):
        gh = _get_gh()
        assert "makefile" in gh.GitHubManager.SAFE_EXTENSIONLESS

    def test_dockerfile_in_extensionless(self):
        gh = _get_gh()
        assert "dockerfile" in gh.GitHubManager.SAFE_EXTENSIONLESS


# ══════════════════════════════════════════════════════════════
# GitHubManager constructor — no token
# ══════════════════════════════════════════════════════════════

class TestGitHubManagerInit:
    def test_no_token_not_available(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        assert mgr._available is False

    def test_no_token_no_raise_when_require_false(self):
        gh = _get_gh()
        # Should not raise with require_token=False (default)
        mgr = gh.GitHubManager(token="", require_token=False)
        assert mgr._available is False

    def test_no_token_raises_when_require_true(self):
        gh = _get_gh()
        import pytest
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            gh.GitHubManager(token="", require_token=True)

    def test_no_token_raises_when_repo_provided(self):
        gh = _get_gh()
        import pytest
        with pytest.raises(ValueError):
            gh.GitHubManager(token="", repo_name="owner/repo")

    def test_token_stored(self):
        gh = _get_gh()
        # With a fake token, it will try to import github and fail gracefully
        mgr = gh.GitHubManager(token="fake_token_xyz")
        assert mgr.token == "fake_token_xyz"


class _GitHubHttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class TestGitHubPatchedServiceResponses:
    def test_set_repo_success_when_loader_returns_true(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._available = True
        mgr._load_repo = MagicMock(return_value=True)

        ok, msg = mgr.set_repo("owner/repo")

        assert ok is True
        assert "Depo değiştirildi" in msg

    def test_set_repo_failure_when_loader_returns_false(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._available = True
        mgr._load_repo = MagicMock(return_value=False)

        ok, msg = mgr.set_repo("owner/missing")

        assert ok is False
        assert "bulunamadı" in msg

    def test_list_repos_handles_404_from_service(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._gh = MagicMock()
        mgr._gh.get_user.side_effect = _GitHubHttpError(404, "Not Found")

        ok, repos = mgr.list_repos(owner="missing-owner")

        assert ok is False
        assert repos == []

    def test_list_repos_handles_500_from_service(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._gh = MagicMock()
        mgr._gh.get_user.side_effect = _GitHubHttpError(500, "Internal Server Error")

        ok, repos = mgr.list_repos(owner="owner")

        assert ok is False
        assert repos == []

    def test_list_repos_handles_403_from_service(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._gh = MagicMock()
        mgr._gh.get_user.side_effect = _GitHubHttpError(403, "Forbidden")

        ok, repos = mgr.list_repos(owner="private-org")

        assert ok is False
        assert repos == []

    def test_read_remote_file_handles_forbidden_403(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._repo = MagicMock()
        mgr._repo.get_contents.side_effect = _GitHubHttpError(403, "Forbidden")

        ok, message = mgr.read_remote_file("secret.txt")
        assert ok is False
        assert "Forbidden" in message

    def test_read_remote_file_rejects_unsafe_extensionless_file(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        content = MagicMock()
        content.name = "credentials"
        content.decoded_content = b"token=abc"
        mgr._repo = MagicMock()
        mgr._repo.get_contents.return_value = content

        ok, message = mgr.read_remote_file("credentials")
        assert ok is False
        assert "güvenli listede değil" in message


class TestGitHubManagerInitWithPatchedGithubModule:
    def test_init_uses_patched_github_module_without_real_request(self):
        gh = _get_gh()

        fake_user = MagicMock()
        fake_user.login = "sidar-bot"
        fake_client = MagicMock()
        fake_client.get_user.return_value = fake_user

        fake_auth = MagicMock()
        fake_auth.Token.return_value = "token-object"
        fake_github_ctor = MagicMock(return_value=fake_client)

        with patch.dict(sys.modules, {"github": MagicMock(Auth=fake_auth, Github=fake_github_ctor)}):
            mgr = gh.GitHubManager(token="ghp_test_token")

        assert mgr._available is True
        fake_auth.Token.assert_called_once_with("ghp_test_token")
        fake_github_ctor.assert_called_once_with(auth="token-object")

    def test_init_handles_unauthorized_from_patched_github_module(self):
        gh = _get_gh()

        fake_client = MagicMock()
        fake_client.get_user.side_effect = _GitHubHttpError(401, "Unauthorized")
        fake_auth = MagicMock()
        fake_auth.Token.return_value = "token-object"
        fake_github_ctor = MagicMock(return_value=fake_client)

        with patch.dict(sys.modules, {"github": MagicMock(Auth=fake_auth, Github=fake_github_ctor)}):
            mgr = gh.GitHubManager(token="ghp_invalid")

        assert mgr._available is False


class TestGitHubManagerServiceOutcomes:
    def test_create_pull_request_success_with_mock_repo(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        pr = MagicMock(title="My PR", html_url="https://example/pr/1", number=1)
        repo = MagicMock(default_branch="main")
        repo.create_pull.return_value = pr
        mgr._repo = repo

        ok, message = mgr.create_pull_request("My PR", "desc", "feat/test", "main")
        assert ok is True
        assert "#1" in message
        repo.create_pull.assert_called_once()

    def test_create_pull_request_failure_with_mock_repo(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock(default_branch="main")
        repo.create_pull.side_effect = RuntimeError("api down")
        mgr._repo = repo

        ok, message = mgr.create_pull_request("My PR", "desc", "feat/test", "main")
        assert ok is False


class TestGitHubIssueListingAndCreation:
    def test_list_issues_filters_pull_requests(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")

        issue_item = MagicMock()
        issue_item.pull_request = None
        issue_item.number = 7
        issue_item.title = "Bug"
        issue_item.state = "open"
        issue_item.user.login = "alice"
        issue_item.created_at.isoformat.return_value = "2026-03-30T00:00:00"

        pr_like_item = MagicMock()
        pr_like_item.pull_request = {"url": "https://api.github.com/pr/1"}

        repo = MagicMock()
        repo.get_issues.return_value = [issue_item, pr_like_item]
        mgr._repo = repo

        ok, payload = mgr.list_issues(state="open", limit=10)
        assert ok is True
        assert len(payload) == 1
        assert payload[0]["number"] == 7

    def test_create_issue_returns_error_message_on_exception(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock()
        repo.create_issue.side_effect = RuntimeError("github unavailable")
        mgr._repo = repo

        ok, message = mgr.create_issue("title", "body")
        assert ok is False
        assert "oluşturulamadı" in message
        assert "github unavailable" in message

    def test_create_pull_request_uses_default_base_when_none(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        pr = MagicMock(title="My PR", html_url="https://example/pr/2", number=2)
        repo = MagicMock(default_branch="develop")
        repo.create_pull.return_value = pr
        mgr._repo = repo

        ok, _message = mgr.create_pull_request("My PR", "desc", "feat/test", None)
        assert ok is True
        kwargs = repo.create_pull.call_args.kwargs
        assert kwargs["base"] == "develop"

    def test_list_pull_requests_empty_success_message(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock(full_name="owner/repo")
        repo.get_pulls.return_value = []
        mgr._repo = repo

        ok, message = mgr.list_pull_requests(state="open", limit=10)
        assert ok is True
        assert "Hiç" in message


class TestGitHubManagerConflictAndRateLimitEdges:
    def test_create_or_update_file_read_rate_limit_returns_error(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock()
        repo.get_contents.side_effect = RuntimeError("API rate limit exceeded")
        mgr._repo = repo

        ok, message = mgr.create_or_update_file(
            file_path="README.md",
            content="hello",
            message="update",
            branch="main",
        )
        assert ok is False
        assert "dosya okuma hatası" in message
        assert "rate limit" in message.lower()

    def test_create_branch_fails_when_source_branch_missing(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock(default_branch="main")
        repo.get_branch.side_effect = RuntimeError("Branch not found: missing-branch")
        mgr._repo = repo

        ok, message = mgr.create_branch("feature/new-flow", from_branch="missing-branch")
        assert ok is False
        assert "Dal oluşturma hatası" in message
        assert "missing-branch" in message

    def test_create_pull_request_returns_merge_conflict_error(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock(default_branch="main")
        repo.create_pull.side_effect = RuntimeError("merge conflict")
        mgr._repo = repo

        ok, message = mgr.create_pull_request("Conflict PR", "body", "feature/conflict", "main")
        assert ok is False
        assert "Pull Request oluşturma hatası" in message
        assert "merge conflict" in message.lower()

    def test_create_branch_returns_sync_error_when_git_ref_creation_fails(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        source_branch = MagicMock(commit=MagicMock(sha="abc123"))
        repo = MagicMock(default_branch="main")
        repo.get_branch.return_value = source_branch
        repo.create_git_ref.side_effect = RuntimeError("reference update failed")
        mgr._repo = repo

        ok, message = mgr.create_branch("feature/sync-error", from_branch="main")
        assert ok is False
        assert "Dal oluşturma hatası" in message
        assert "reference update failed" in message

    def test_list_branches_handles_api_failure(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock()
        repo.get_branches.side_effect = RuntimeError("branch API timeout")
        mgr._repo = repo

        ok, message = mgr.list_branches(limit=20)
        assert ok is False
        assert "Branch listesi alınamadı" in message
        assert "timeout" in message.lower()

    def test_create_pull_request_returns_error_when_repo_not_set(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._repo = None

        ok, message = mgr.create_pull_request("Title", "Body", "feature/x", "main")
        assert ok is False
        assert "Aktif depo yok" in message


class TestGitHubManagerAuthAndRepoFlows:
    def test_list_repos_owner_organization_uses_all_repo_type(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        org_repo = MagicMock(full_name="org/repo", default_branch="main", private=True)
        org_account = MagicMock(type="Organization")
        org_account.get_repos.return_value = [org_repo]
        mgr._gh = MagicMock()
        mgr._gh.get_user.return_value = org_account

        ok, repos = mgr.list_repos(owner="org")

        assert ok is True
        assert repos[0]["full_name"] == "org/repo"
        org_account.get_repos.assert_called_once_with(type="all")

    def test_create_or_update_file_creates_new_when_not_found(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock()
        repo.get_contents.side_effect = _GitHubHttpError(404, "Not Found")
        mgr._repo = repo

        ok, msg = mgr.create_or_update_file(
            file_path="docs/new.md",
            content="# hello",
            message="add file",
            branch="main",
        )

        assert ok is True
        assert "oluşturuldu" in msg
        repo.create_file.assert_called_once()

    def test_create_branch_rejects_invalid_branch_name(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._repo = MagicMock(default_branch="main")

        ok, message = mgr.create_branch("bad branch name", from_branch="main")
        assert ok is False
        assert "Geçersiz dal adı" in message

    def test_create_or_update_file_update_conflict_returns_error(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        existing = MagicMock(sha="abc123")
        repo = MagicMock()
        repo.get_contents.return_value = existing
        repo.update_file.side_effect = RuntimeError("409 Conflict: sha does not match")
        mgr._repo = repo

        ok, message = mgr.create_or_update_file(
            file_path="src/app.py",
            content="print('x')",
            message="update app",
            branch="feature/conflict",
        )
        assert ok is False
        assert "dosya yazma hatası" in message
        assert "conflict" in message.lower()

    def test_create_branch_existing_ref_conflict_returns_error(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        source_ref = MagicMock(commit=MagicMock(sha="deadbeef"))
        repo = MagicMock(default_branch="main")
        repo.get_branch.return_value = source_ref
        repo.create_git_ref.side_effect = RuntimeError("Reference already exists (409)")
        mgr._repo = repo

        ok, message = mgr.create_branch("feature/existing")
        assert ok is False
        assert "Dal oluşturma hatası" in message
        assert "409" in message


class TestGitHubManagerPrFormattingAndStateEdges:
    def test_list_pull_requests_invalid_state_falls_back_to_open(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock(full_name="owner/repo")
        repo.get_pulls.return_value = []
        mgr._repo = repo

        ok, _message = mgr.list_pull_requests(state="invalid-state", limit=5)
        assert ok is True
        repo.get_pulls.assert_called_once_with(state="open", sort="updated")

    def test_get_pull_request_includes_suffix_for_more_than_20_files(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")

        from datetime import datetime

        files = [
            MagicMock(status="modified", additions=1, deletions=0, filename=f"file_{i}.py")
            for i in range(25)
        ]
        pr = MagicMock(
            number=17,
            title="Big PR",
            state="open",
            user=MagicMock(login="dev"),
            head=MagicMock(ref="feat/big"),
            base=MagicMock(ref="main"),
            created_at=datetime(2026, 1, 1, 10, 0),
            updated_at=datetime(2026, 1, 2, 10, 0),
            additions=100,
            deletions=10,
            changed_files=25,
            comments=3,
            html_url="https://example/pr/17",
            body="description",
        )
        pr.get_files.return_value = files
        repo = MagicMock(full_name="owner/repo")
        repo.get_pull.return_value = pr
        mgr._repo = repo

        ok, details = mgr.get_pull_request(17)
        assert ok is True
        assert "(+5 dosya daha)" in details


class TestGitHubManagerAdditionalServiceErrors:
    def test_list_repos_handles_401_from_service(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        mgr._gh = MagicMock()
        mgr._gh.get_user.side_effect = _GitHubHttpError(401, "Unauthorized")

        ok, repos = mgr.list_repos(owner="private-owner")
        assert ok is False
        assert repos == []

    def test_create_or_update_file_non_404_get_contents_error_returns_read_error(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock()
        repo.get_contents.side_effect = RuntimeError("500 Internal Server Error")
        mgr._repo = repo

        ok, message = mgr.create_or_update_file(
            file_path="README.md",
            content="hello",
            message="update readme",
            branch="main",
        )
        assert ok is False
        assert "dosya okuma hatası" in message.lower()
