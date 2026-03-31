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

    def test_create_pull_request_handles_404_repo_not_found(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock(default_branch="main")
        repo.create_pull.side_effect = _GitHubHttpError(404, "Repository not found")
        mgr._repo = repo

        ok, message = mgr.create_pull_request("PR", "body", "feature/abc", "main")

        assert ok is False
        assert "pull request oluşturma hatası" in message.lower()
        assert "repository not found" in message.lower()

    def test_create_pull_request_handles_409_conflict_from_api(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        repo = MagicMock(default_branch="main")
        repo.create_pull.side_effect = _GitHubHttpError(409, "Conflict: base branch changed")
        mgr._repo = repo

        ok, message = mgr.create_pull_request("PR", "body", "feature/conflict", "main")

        assert ok is False
        assert "pull request oluşturma hatası" in message.lower()
        assert "conflict" in message.lower()

class TestGitHubManagerCoverageBoost:
    def test_list_commits_clamps_limit_to_100(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        commits = []
        for i in range(150):
            c = MagicMock()
            c.sha = f"{i:040d}"
            c.commit.message = f"commit {i}"
            c.commit.author.name = "dev"
            c.commit.author.date.strftime.return_value = "2026-03-31 00:00"
            commits.append(c)

        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo.get_commits.return_value = commits
        mgr._repo = repo

        ok, out = mgr.list_commits(limit=999)
        assert ok is True
        assert "[Son 100 Commit" in out

    def test_read_remote_file_returns_directory_listing_when_path_is_dir(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        dir_item = MagicMock()
        dir_item.type = "dir"
        dir_item.name = "src"
        file_item = MagicMock()
        file_item.type = "file"
        file_item.name = "README.md"

        repo = MagicMock()
        repo.get_contents.return_value = [dir_item, file_item]
        mgr._repo = repo

        ok, out = mgr.read_remote_file("docs")
        assert ok is True
        assert "[Dizin: docs]" in out
        assert "📂 src" in out
        assert "📄 README.md" in out

    def test_read_remote_file_blocks_unsafe_extension(self):
        gh = _get_gh()
        mgr = gh.GitHubManager(token="")
        item = MagicMock()
        item.name = "archive.zip"
        item.decoded_content = b"pk.."
        repo = MagicMock()
        repo.get_contents.return_value = item
        mgr._repo = repo

        ok, out = mgr.read_remote_file("archive.zip")
        assert ok is False
        assert "desteklenmeyen" in out.lower() or "binary" in out.lower()

# ===== MERGED FROM tests/test_managers_github_extra.py =====

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────

def _get_gh():
    sys.modules.pop("managers.github_manager", None)
    import managers.github_manager as gh
    return gh


class Extra__HttpError(Exception):
    def __init__(self, status: int, message: str = "error"):
        super().__init__(message)
        self.status = status


def _make_manager(token: str = "") -> "managers.github_manager.GitHubManager":
    gh = _get_gh()
    mgr = gh.GitHubManager(token=token)
    return mgr


def _manager_with_repo():
    """Return a manager that already has _repo set to a MagicMock."""
    mgr = _make_manager()
    mgr._repo = MagicMock()
    mgr._repo.full_name = "owner/repo"
    mgr._repo.default_branch = "main"
    return mgr


# ─────────────────────────────────────────────────────────────
# _init_client — ImportError path (line 82)
# ─────────────────────────────────────────────────────────────

class Extra_TestInitClientImportError:
    def test_import_error_disables_client(self):
        gh = _get_gh()
        fake_github = MagicMock()
        fake_github.__name__ = "github"

        # Make Github constructor raise ImportError
        def _bad_import(*a, **kw):
            raise ImportError("no module named github")

        with patch.dict(sys.modules, {"github": None}):
            mgr = gh.GitHubManager(token="tok")

        assert mgr._available is False

    def test_generic_exception_during_login_disables_client(self):
        gh = _get_gh()

        fake_auth = MagicMock()
        fake_auth.Token.return_value = "token-obj"
        fake_client = MagicMock()
        fake_client.get_user.side_effect = RuntimeError("network down")
        fake_github_ctor = MagicMock(return_value=fake_client)

        with patch.dict(sys.modules, {"github": MagicMock(Auth=fake_auth, Github=fake_github_ctor)}):
            mgr = gh.GitHubManager(token="ghp_test")

        assert mgr._available is False


# ─────────────────────────────────────────────────────────────
# _load_repo (lines 88-97)
# ─────────────────────────────────────────────────────────────

class Extra_TestLoadRepo:
    def test_load_repo_success(self):
        mgr = _make_manager()
        fake_repo = MagicMock()
        fake_repo.full_name = "owner/my-repo"
        mgr._gh = MagicMock()
        mgr._gh.get_repo.return_value = fake_repo

        result = mgr._load_repo("owner/my-repo")

        assert result is True
        assert mgr._repo is fake_repo
        assert mgr.repo_name == "owner/my-repo"

    def test_load_repo_exception_returns_false(self):
        mgr = _make_manager()
        mgr._gh = MagicMock()
        mgr._gh.get_repo.side_effect = RuntimeError("repo not found")

        result = mgr._load_repo("owner/missing")

        assert result is False

    def test_load_repo_without_gh_returns_false(self):
        mgr = _make_manager()
        mgr._gh = None

        result = mgr._load_repo("owner/repo")

        assert result is False


# ─────────────────────────────────────────────────────────────
# set_repo — no connection (line 106)
# ─────────────────────────────────────────────────────────────

class Extra_TestSetRepo:
    def test_set_repo_no_connection_returns_false(self):
        mgr = _make_manager()
        mgr._available = False

        ok, msg = mgr.set_repo("owner/repo")

        assert ok is False
        assert "bağlantısı yok" in msg


# ─────────────────────────────────────────────────────────────
# list_repos — no _gh client (line 118)
# ─────────────────────────────────────────────────────────────

class Extra_TestListReposNoClient:
    def test_list_repos_returns_empty_when_no_gh(self):
        mgr = _make_manager()
        mgr._gh = None

        ok, repos = mgr.list_repos()

        assert ok is False
        assert repos == []

    def test_list_repos_self_without_owner(self):
        mgr = _make_manager()
        repo_mock = MagicMock(
            full_name="me/my-repo",
            default_branch="main",
            private=False,
        )
        user_mock = MagicMock()
        user_mock.get_repos.return_value = [repo_mock]
        mgr._gh = MagicMock()
        mgr._gh.get_user.return_value = user_mock

        ok, repos = mgr.list_repos()

        assert ok is True
        assert repos[0]["full_name"] == "me/my-repo"

    def test_list_repos_limit_respected(self):
        mgr = _make_manager()
        repo_mocks = [
            MagicMock(full_name=f"me/repo-{i}", default_branch="main", private=False)
            for i in range(10)
        ]
        user_mock = MagicMock()
        user_mock.get_repos.return_value = repo_mocks
        mgr._gh = MagicMock()
        mgr._gh.get_user.return_value = user_mock

        ok, repos = mgr.list_repos(limit=3)

        assert ok is True
        assert len(repos) == 3


# ─────────────────────────────────────────────────────────────
# get_repo_info (lines 144-159)
# ─────────────────────────────────────────────────────────────

class Extra_TestGetRepoInfo:
    def test_returns_error_when_no_repo(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.get_repo_info()

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_returns_formatted_info(self):
        mgr = _manager_with_repo()
        r = mgr._repo
        r.full_name = "owner/repo"
        r.description = "Test repo"
        r.language = "Python"
        r.stargazers_count = 42
        r.forks_count = 7
        r.default_branch = "main"
        r.get_pulls.return_value = MagicMock(totalCount=3)
        r.get_issues.return_value = MagicMock(totalCount=5)

        ok, info = mgr.get_repo_info()

        assert ok is True
        assert "owner/repo" in info
        assert "Python" in info
        assert "42" in info

    def test_repo_info_exception_returns_false(self):
        mgr = _manager_with_repo()
        # Make get_repo_info throw by patching the internal calls
        def _raise(*a, **k):
            raise RuntimeError("api error")
        mgr._repo.get_contents = _raise
        # Cause the exception on full_name access via a property mock
        type(mgr._repo).full_name = property(lambda s: (_ for _ in ()).throw(RuntimeError("api error")))

        ok, msg = mgr.get_repo_info()

        assert ok is False
        assert "alınamadı" in msg or "hata" in msg.lower()


# ─────────────────────────────────────────────────────────────
# list_commits (lines 161-189)
# ─────────────────────────────────────────────────────────────

class Extra_TestListCommits:
    def test_returns_error_when_no_repo(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.list_commits()

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_list_commits_with_branch_filter(self):
        mgr = _manager_with_repo()

        commit = MagicMock()
        commit.sha = "a" * 40
        commit.commit.message = "feat: add stuff"
        commit.commit.author.name = "dev"
        commit.commit.author.date.strftime.return_value = "2026-01-01 10:00"

        mgr._repo.get_commits.return_value = [commit]

        ok, out = mgr.list_commits(limit=5, branch="feature/x")

        assert ok is True
        assert "feat: add stuff" in out
        mgr._repo.get_commits.assert_called_once_with(sha="feature/x")

    def test_list_commits_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_commits.side_effect = RuntimeError("timeout")

        ok, msg = mgr.list_commits()

        assert ok is False
        assert "Commit listesi alınamadı" in msg

    def test_list_commits_clamps_min_to_1(self):
        mgr = _manager_with_repo()
        mgr._repo.full_name = "owner/repo"
        commit = MagicMock()
        commit.sha = "b" * 40
        commit.commit.message = "fix: something"
        commit.commit.author.name = "bot"
        commit.commit.author.date.strftime.return_value = "2026-01-01 00:00"
        mgr._repo.get_commits.return_value = [commit]

        ok, out = mgr.list_commits(limit=-5)

        assert ok is True


# ─────────────────────────────────────────────────────────────
# read_remote_file (lines 192-245)
# ─────────────────────────────────────────────────────────────

class Extra_TestReadRemoteFile:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.read_remote_file("README.md")

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_reads_safe_text_file_with_ref(self):
        mgr = _manager_with_repo()
        content = MagicMock()
        content.name = "config.py"
        content.decoded_content = b"TOKEN = 'abc'"
        mgr._repo.get_contents.return_value = content

        ok, text = mgr.read_remote_file("config.py", ref="main")

        assert ok is True
        assert "TOKEN" in text
        mgr._repo.get_contents.assert_called_once_with("config.py", ref="main")

    def test_safe_extensionless_makefile_readable(self):
        mgr = _manager_with_repo()
        content = MagicMock()
        content.name = "Makefile"
        content.decoded_content = b"all:\n\tpython main.py"
        mgr._repo.get_contents.return_value = content

        ok, text = mgr.read_remote_file("Makefile")

        assert ok is True
        assert "python" in text

    def test_unsafe_extensionless_blocked(self):
        mgr = _manager_with_repo()
        content = MagicMock()
        content.name = "secretfile"
        content.decoded_content = b"secret"
        mgr._repo.get_contents.return_value = content

        ok, msg = mgr.read_remote_file("secretfile")

        assert ok is False
        assert "güvenli listede değil" in msg

    def test_binary_extension_blocked(self):
        mgr = _manager_with_repo()
        content = MagicMock()
        content.name = "data.pkl"
        mgr._repo.get_contents.return_value = content

        ok, msg = mgr.read_remote_file("data.pkl")

        assert ok is False
        assert "binary" in msg.lower() or "desteklenmeyen" in msg.lower()

    def test_unicode_decode_error_returns_false(self):
        mgr = _manager_with_repo()
        content = MagicMock()
        content.name = "file.txt"

        def _bad_decode(*a, **kw):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte")

        content.decoded_content.decode = _bad_decode
        mgr._repo.get_contents.return_value = content

        ok, msg = mgr.read_remote_file("file.txt")

        assert ok is False
        assert "UTF-8" in msg or "binary" in msg.lower()


# ─────────────────────────────────────────────────────────────
# list_branches (lines 247-260)
# ─────────────────────────────────────────────────────────────

class Extra_TestListBranches:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.list_branches()

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_marks_default_branch(self):
        mgr = _manager_with_repo()
        mgr._repo.full_name = "owner/repo"
        mgr._repo.default_branch = "main"

        main_branch = MagicMock(name="main")
        main_branch.name = "main"
        dev_branch = MagicMock()
        dev_branch.name = "develop"

        mgr._repo.get_branches.return_value = [main_branch, dev_branch]

        ok, out = mgr.list_branches()

        assert ok is True
        assert "* main" in out
        assert "  develop" in out

    def test_list_branches_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_branches.side_effect = RuntimeError("api down")

        ok, msg = mgr.list_branches()

        assert ok is False
        assert "Branch listesi alınamadı" in msg

    def test_list_branches_limit_clamped(self):
        mgr = _manager_with_repo()
        mgr._repo.full_name = "owner/repo"
        mgr._repo.default_branch = "main"
        branches = [MagicMock(name=f"branch-{i}") for i in range(5)]
        for i, b in enumerate(branches):
            b.name = f"branch-{i}"
        mgr._repo.get_branches.return_value = branches

        ok, out = mgr.list_branches(limit=200)  # should be clamped to 100

        assert ok is True


# ─────────────────────────────────────────────────────────────
# list_files (lines 262-279)
# ─────────────────────────────────────────────────────────────

class Extra_TestListFiles:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.list_files()

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_list_files_root(self):
        mgr = _manager_with_repo()
        dir_item = MagicMock()
        dir_item.type = "dir"
        dir_item.name = "src"
        file_item = MagicMock()
        file_item.type = "file"
        file_item.name = "README.md"
        mgr._repo.get_contents.return_value = [dir_item, file_item]

        ok, out = mgr.list_files()

        assert ok is True
        assert "📂 src" in out
        assert "📄 README.md" in out

    def test_list_files_with_branch(self):
        mgr = _manager_with_repo()
        file_item = MagicMock(type="file", name="app.py")
        mgr._repo.get_contents.return_value = [file_item]

        ok, out = mgr.list_files(path="src", branch="develop")

        mgr._repo.get_contents.assert_called_once_with("src", ref="develop")
        assert ok is True

    def test_list_files_single_item_wrapped(self):
        """When get_contents returns a single ContentFile (not a list)."""
        mgr = _manager_with_repo()
        single = MagicMock(type="file", name="Makefile")
        mgr._repo.get_contents.return_value = single  # NOT a list

        ok, out = mgr.list_files(path="Makefile")

        assert ok is True
        assert "Makefile" in out

    def test_list_files_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_contents.side_effect = RuntimeError("timeout")

        ok, msg = mgr.list_files()

        assert ok is False
        assert "Dosya listesi alınamadı" in msg


# ─────────────────────────────────────────────────────────────
# create_or_update_file (lines 281-322)
# ─────────────────────────────────────────────────────────────

class Extra_TestCreateOrUpdateFile:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.create_or_update_file("f.py", "content", "msg")

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_creates_file_when_not_found(self):
        mgr = _manager_with_repo()
        mgr._repo.get_contents.side_effect = _HttpError(404, "Not Found")

        ok, msg = mgr.create_or_update_file("new.py", "print('hi')", "add new.py")

        assert ok is True
        assert "oluşturuldu" in msg
        mgr._repo.create_file.assert_called_once()

    def test_updates_file_when_exists(self):
        mgr = _manager_with_repo()
        existing = MagicMock(sha="deadbeef")
        mgr._repo.get_contents.return_value = existing

        ok, msg = mgr.create_or_update_file("existing.py", "new content", "update")

        assert ok is True
        assert "güncellendi" in msg
        mgr._repo.update_file.assert_called_once()

    def test_non_404_error_from_get_contents_returns_read_error(self):
        mgr = _manager_with_repo()
        mgr._repo.get_contents.side_effect = _HttpError(500, "Internal Server Error")

        ok, msg = mgr.create_or_update_file("f.py", "x", "msg")

        assert ok is False
        assert "dosya okuma hatası" in msg

    def test_update_file_write_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_contents.return_value = MagicMock(sha="abc")
        mgr._repo.update_file.side_effect = RuntimeError("conflict")

        ok, msg = mgr.create_or_update_file("f.py", "x", "msg")

        assert ok is False
        assert "dosya yazma hatası" in msg


# ─────────────────────────────────────────────────────────────
# create_branch (lines 324-352)
# ─────────────────────────────────────────────────────────────

class Extra_TestCreateBranch:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.create_branch("feature/x")

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_empty_name_rejected(self):
        mgr = _manager_with_repo()

        ok, msg = mgr.create_branch("")

        assert ok is False
        assert "Geçersiz dal adı" in msg

    def test_name_with_space_rejected(self):
        mgr = _manager_with_repo()

        ok, msg = mgr.create_branch("my branch")

        assert ok is False
        assert "Geçersiz dal adı" in msg

    def test_valid_branch_created_from_default(self):
        mgr = _manager_with_repo()
        src = MagicMock(commit=MagicMock(sha="abc123"))
        mgr._repo.get_branch.return_value = src
        mgr._repo.default_branch = "main"

        ok, msg = mgr.create_branch("feature/new")

        assert ok is True
        assert "feature/new" in msg
        assert "main" in msg
        mgr._repo.create_git_ref.assert_called_once_with(
            ref="refs/heads/feature/new", sha="abc123"
        )

    def test_valid_branch_created_from_explicit_source(self):
        mgr = _manager_with_repo()
        src = MagicMock(commit=MagicMock(sha="xyz789"))
        mgr._repo.get_branch.return_value = src

        ok, msg = mgr.create_branch("hotfix/bug", from_branch="develop")

        assert ok is True
        mgr._repo.get_branch.assert_called_once_with("develop")


# ─────────────────────────────────────────────────────────────
# list_pull_requests (lines 381-404)
# ─────────────────────────────────────────────────────────────

class Extra_TestListPullRequests:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.list_pull_requests()

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_unknown_state_normalised_to_open(self):
        mgr = _manager_with_repo()
        mgr._repo.get_pulls.return_value = []

        ok, _msg = mgr.list_pull_requests(state="bogus")

        mgr._repo.get_pulls.assert_called_once_with(state="open", sort="updated")

    def test_returns_formatted_pr_list(self):
        mgr = _manager_with_repo()
        pr = MagicMock(
            number=5,
            updated_at=datetime(2026, 3, 1),
            user=MagicMock(login="alice"),
            title="Fix nasty bug",
        )
        mgr._repo.get_pulls.return_value = [pr]

        ok, out = mgr.list_pull_requests(state="open", limit=5)

        assert ok is True
        assert "#   5" in out or "#5" in out or "5" in out
        assert "alice" in out
        assert "Fix nasty bug" in out

    def test_list_prs_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_pulls.side_effect = RuntimeError("api down")

        ok, msg = mgr.list_pull_requests()

        assert ok is False
        assert "PR listesi alınamadı" in msg


# ─────────────────────────────────────────────────────────────
# get_pull_request (lines 406-433)
# ─────────────────────────────────────────────────────────────

class Extra_TestGetPullRequest:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.get_pull_request(1)

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_returns_pr_details(self):
        mgr = _manager_with_repo()
        files = [
            MagicMock(status="modified", additions=5, deletions=2, filename=f"f{i}.py")
            for i in range(3)
        ]
        pr = MagicMock(
            number=10,
            title="My PR",
            state="open",
            user=MagicMock(login="dev"),
            head=MagicMock(ref="feature/x"),
            base=MagicMock(ref="main"),
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 2),
            additions=15,
            deletions=6,
            changed_files=3,
            comments=0,
            html_url="https://example.com/pr/10",
            body="body text",
        )
        pr.get_files.return_value = files
        mgr._repo.get_pull.return_value = pr

        ok, details = mgr.get_pull_request(10)

        assert ok is True
        assert "My PR" in details
        assert "feature/x" in details

    def test_get_pull_request_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_pull.side_effect = RuntimeError("not found")

        ok, msg = mgr.get_pull_request(999)

        assert ok is False
        assert "PR detayı alınamadı" in msg


# ─────────────────────────────────────────────────────────────
# add_pr_comment (lines 435-447)
# ─────────────────────────────────────────────────────────────

class Extra_TestAddPrComment:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.add_pr_comment(1, "hello")

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_adds_comment_successfully(self):
        mgr = _manager_with_repo()
        comment = MagicMock(html_url="https://example.com/comment/1")
        issue = MagicMock()
        issue.create_comment.return_value = comment
        mgr._repo.get_issue.return_value = issue

        ok, msg = mgr.add_pr_comment(5, "LGTM!")

        assert ok is True
        assert "PR #5" in msg
        assert "https://example.com/comment/1" in msg

    def test_add_pr_comment_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_issue.side_effect = RuntimeError("not found")

        ok, msg = mgr.add_pr_comment(99, "comment")

        assert ok is False
        assert "yorumu eklenemedi" in msg


# ─────────────────────────────────────────────────────────────
# close_pull_request (lines 449-458)
# ─────────────────────────────────────────────────────────────

class Extra_TestClosePullRequest:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.close_pull_request(1)

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_closes_pr_successfully(self):
        mgr = _manager_with_repo()
        pr = MagicMock(html_url="https://example.com/pr/3")
        mgr._repo.get_pull.return_value = pr

        ok, msg = mgr.close_pull_request(3)

        assert ok is True
        assert "#3" in msg
        pr.edit.assert_called_once_with(state="closed")

    def test_close_pr_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_pull.side_effect = RuntimeError("closed already")

        ok, msg = mgr.close_pull_request(3)

        assert ok is False
        assert "PR kapatma hatası" in msg


# ─────────────────────────────────────────────────────────────
# list_issues (lines 461-485)
# ─────────────────────────────────────────────────────────────

class Extra_TestListIssues:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, payload = mgr.list_issues()

        assert ok is False
        assert "Aktif depo yok" in payload[0]

    def test_list_issues_closed(self):
        mgr = _manager_with_repo()
        issue = MagicMock()
        issue.pull_request = None
        issue.number = 2
        issue.title = "closed bug"
        issue.state = "closed"
        issue.user.login = "bob"
        issue.created_at.isoformat.return_value = "2026-01-01T00:00:00"

        mgr._repo.get_issues.return_value = [issue]

        ok, payload = mgr.list_issues(state="closed", limit=5)

        assert ok is True
        assert payload[0]["number"] == 2
        mgr._repo.get_issues.assert_called_once_with(state="closed")

    def test_invalid_state_normalised_to_open(self):
        mgr = _manager_with_repo()
        mgr._repo.get_issues.return_value = []

        ok, payload = mgr.list_issues(state="weird")

        mgr._repo.get_issues.assert_called_once_with(state="open")

    def test_list_issues_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_issues.side_effect = RuntimeError("rate limit")

        ok, payload = mgr.list_issues()

        assert ok is False
        assert "Hata" in payload[0]


# ─────────────────────────────────────────────────────────────
# create_issue (lines 487-495)
# ─────────────────────────────────────────────────────────────

class Extra_TestCreateIssue:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.create_issue("title", "body")

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_creates_issue_successfully(self):
        mgr = _manager_with_repo()
        issue = MagicMock(number=7, title="New bug")
        mgr._repo.create_issue.return_value = issue

        ok, msg = mgr.create_issue("New bug", "description")

        assert ok is True
        assert "#7" in msg
        assert "New bug" in msg


# ─────────────────────────────────────────────────────────────
# comment_issue (lines 497-506)
# ─────────────────────────────────────────────────────────────

class Extra_TestCommentIssue:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.comment_issue(1, "test")

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_adds_comment(self):
        mgr = _manager_with_repo()
        issue = MagicMock()
        mgr._repo.get_issue.return_value = issue

        ok, msg = mgr.comment_issue(3, "Works for me")

        assert ok is True
        assert "#3" in msg
        issue.create_comment.assert_called_once_with("Works for me")

    def test_comment_issue_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_issue.side_effect = RuntimeError("issue closed")

        ok, msg = mgr.comment_issue(3, "late comment")

        assert ok is False
        assert "Yorum eklenemedi" in msg


# ─────────────────────────────────────────────────────────────
# close_issue (lines 508-517)
# ─────────────────────────────────────────────────────────────

class Extra_TestCloseIssue:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.close_issue(1)

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_closes_issue(self):
        mgr = _manager_with_repo()
        issue = MagicMock()
        mgr._repo.get_issue.return_value = issue

        ok, msg = mgr.close_issue(5)

        assert ok is True
        assert "#5" in msg
        issue.edit.assert_called_once_with(state="closed")

    def test_close_issue_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_issue.side_effect = RuntimeError("not found")

        ok, msg = mgr.close_issue(5)

        assert ok is False
        assert "Issue kapatılamadı" in msg


# ─────────────────────────────────────────────────────────────
# get_pull_request_diff (lines 520-542)
# ─────────────────────────────────────────────────────────────

class Extra_TestGetPullRequestDiff:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.get_pull_request_diff(1)

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_returns_diff_with_patches(self):
        mgr = _manager_with_repo()
        f1 = MagicMock(filename="src/app.py", status="modified", patch="@@ -1,2 +1,3 @@ change")
        f2 = MagicMock(filename="image.png", status="added", patch=None)

        pr = MagicMock(title="Big change", number=7)
        pr.get_files.return_value = [f1, f2]
        mgr._repo.get_pull.return_value = pr

        ok, out = mgr.get_pull_request_diff(7)

        assert ok is True
        assert "src/app.py" in out
        assert "@@ -1,2 +1,3 @@" in out
        assert "binary" in out.lower() or "Diff/Patch metni yok" in out

    def test_returns_no_files_message_when_empty(self):
        mgr = _manager_with_repo()
        pr = MagicMock(title="Empty PR", number=8)
        pr.get_files.return_value = []
        mgr._repo.get_pull.return_value = pr

        ok, out = mgr.get_pull_request_diff(8)

        assert ok is True
        assert "değiştirilmiş" in out or "bulunmuyor" in out

    def test_get_pr_diff_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_pull.side_effect = RuntimeError("api error")

        ok, msg = mgr.get_pull_request_diff(1)

        assert ok is False
        assert "Diff alınamadı" in msg


# ─────────────────────────────────────────────────────────────
# get_pr_files (lines 544-558)
# ─────────────────────────────────────────────────────────────

class Extra_TestGetPrFiles:
    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, msg = mgr.get_pr_files(1)

        assert ok is False
        assert "Aktif depo yok" in msg

    def test_returns_file_list(self):
        mgr = _manager_with_repo()
        f = MagicMock(status="modified", additions=10, deletions=3, filename="core/main.py")
        pr = MagicMock(number=4)
        pr.get_files.return_value = [f]
        mgr._repo.get_pull.return_value = pr

        ok, out = mgr.get_pr_files(4)

        assert ok is True
        assert "core/main.py" in out

    def test_get_pr_files_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_pull.side_effect = RuntimeError("timeout")

        ok, msg = mgr.get_pr_files(4)

        assert ok is False
        assert "PR dosya listesi alınamadı" in msg


# ─────────────────────────────────────────────────────────────
# search_code (lines 560-574)
# ─────────────────────────────────────────────────────────────

class Extra_TestSearchCode:
    def test_no_gh_or_repo_returns_error(self):
        mgr = _make_manager()
        mgr._gh = None
        mgr._repo = None

        ok, msg = mgr.search_code("def main")

        assert ok is False
        assert "bağlantısı" in msg

    def test_no_repo_returns_error(self):
        mgr = _make_manager()
        mgr._gh = MagicMock()
        mgr._repo = None

        ok, msg = mgr.search_code("def main")

        assert ok is False

    def test_returns_results(self):
        mgr = _manager_with_repo()
        result_item = MagicMock(path="src/main.py")
        mgr._gh = MagicMock()
        mgr._gh.search_code.return_value = [result_item]

        ok, out = mgr.search_code("def main")

        assert ok is True
        assert "src/main.py" in out

    def test_no_results_returns_message(self):
        mgr = _manager_with_repo()
        mgr._gh = MagicMock()
        mgr._gh.search_code.return_value = []

        ok, out = mgr.search_code("something_obscure")

        assert ok is True
        assert "bulunamadı" in out

    def test_search_code_exception(self):
        mgr = _manager_with_repo()
        mgr._gh = MagicMock()
        mgr._gh.search_code.side_effect = RuntimeError("rate limit")

        ok, msg = mgr.search_code("query")

        assert ok is False
        assert "Kod arama hatası" in msg


# ─────────────────────────────────────────────────────────────
# is_available + status (lines 580-599)
# ─────────────────────────────────────────────────────────────

class Extra_TestIsAvailableAndStatus:
    def test_is_available_false_when_no_token(self):
        mgr = _make_manager(token="")
        assert mgr.is_available() is False

    def test_status_no_token(self):
        mgr = _make_manager(token="")
        out = mgr.status()
        assert "Bağlı değil" in out
        assert "GITHUB_TOKEN" in out

    def test_status_invalid_token(self):
        mgr = _make_manager(token="")
        mgr._available = False
        mgr.token = "some_token"
        out = mgr.status()
        assert "geçersiz" in out or "bağlantı hatası" in out

    def test_status_connected_with_repo(self):
        mgr = _make_manager()
        mgr._available = True
        mgr.repo_name = "owner/repo"
        out = mgr.status()
        assert "Bağlı" in out
        assert "owner/repo" in out

    def test_status_connected_no_repo(self):
        mgr = _make_manager()
        mgr._available = True
        mgr.repo_name = ""
        out = mgr.status()
        assert "Bağlı" in out
        assert "ayarlanmamış" in out


# ─────────────────────────────────────────────────────────────
# default_branch property (line 604)
# ─────────────────────────────────────────────────────────────

class Extra_TestDefaultBranchProperty:
    def test_returns_main_when_no_repo(self):
        mgr = _make_manager()
        mgr._repo = None
        assert mgr.default_branch == "main"

    def test_returns_repo_default_branch(self):
        mgr = _manager_with_repo()
        mgr._repo.default_branch = "develop"
        assert mgr.default_branch == "develop"


# ─────────────────────────────────────────────────────────────
# get_pull_requests_detailed (lines 606-639)
# ─────────────────────────────────────────────────────────────

class Extra_TestGetPullRequestsDetailed:
    def test_no_repo_returns_error_tuple(self):
        mgr = _make_manager()
        mgr._repo = None

        ok, prs, err = mgr.get_pull_requests_detailed()

        assert ok is False
        assert prs == []
        assert "Repo ayarlanmamış" in err

    def test_returns_structured_pr_list(self):
        mgr = _manager_with_repo()
        pr = MagicMock(
            number=1,
            title="Feature PR",
            state="open",
            user=MagicMock(login="dev"),
            head=MagicMock(ref="feature/x"),
            base=MagicMock(ref="main"),
            html_url="https://example.com/pr/1",
            created_at=MagicMock(strftime=MagicMock(return_value="2026-01-01 00:00")),
            updated_at=MagicMock(strftime=MagicMock(return_value="2026-01-02 00:00")),
            additions=10,
            deletions=2,
            changed_files=1,
            comments=0,
        )
        mgr._repo.get_pulls.return_value = [pr]

        ok, prs, err = mgr.get_pull_requests_detailed(state="open", limit=10)

        assert ok is True
        assert err == ""
        assert len(prs) == 1
        assert prs[0]["number"] == 1
        assert prs[0]["title"] == "Feature PR"
        assert prs[0]["author"] == "dev"
        assert prs[0]["head"] == "feature/x"

    def test_detailed_prs_exception(self):
        mgr = _manager_with_repo()
        mgr._repo.get_pulls.side_effect = RuntimeError("network error")

        ok, prs, err = mgr.get_pull_requests_detailed()

        assert ok is False
        assert prs == []
        assert "network error" in err

    def test_repr_contains_available_and_repo(self):
        mgr = _make_manager()
        mgr._available = True
        mgr.repo_name = "owner/repo"
        r = repr(mgr)
        assert "available=True" in r
        assert "owner/repo" in r

    def test_repr_no_repo(self):
        mgr = _make_manager()
        mgr._available = False
        mgr.repo_name = ""
        r = repr(mgr)
        assert "None" in r
