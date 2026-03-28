"""
managers/github_manager.py için birim testleri.
_is_not_found_error, GitHubManager.SAFE_TEXT_EXTENSIONS,
GitHubManager.SAFE_EXTENSIONLESS, constructor (no token).
"""
from __future__ import annotations

import sys


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
