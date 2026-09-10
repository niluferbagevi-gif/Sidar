"""Regression tests for update_install_module_hash_manifest.py's git helper.

``sha256sum_git_show`` used to invoke a bare ``"git"`` argv[0], which Bandit
flags as B607 (partial executable path) in addition to the unavoidable B603
(subprocess call without ``shell=True``) -- a PATH lookup at call time is a
real (if low-severity) supply-chain surface if an earlier PATH entry ever
shadowed the real ``git``. It now resolves ``git`` via ``shutil.which`` and
requires the result to be an absolute path before running it (the same
fail-closed pattern used by ``scripts/ci/verify_required_checks.py``'s
``_repo_from_git_remote`` and ``web/routes/project_ops.py``'s
``_execute_allowed_git_command``), which is why only ``# nosec B603`` remains
on that call -- B607 no longer fires. See ``bandit-suppression-baseline.json``
``debt_plan.completed_reviews`` for the reviewed rationale.
"""

from __future__ import annotations

import pytest

from scripts.tools import update_install_module_hash_manifest as manifest_tool


def test_sha256sum_git_show_fails_closed_when_git_is_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest_tool.shutil, "which", lambda _name: None)
    assert manifest_tool.sha256sum_git_show("HEAD", "README.md") is None


def test_sha256sum_git_show_fails_closed_on_non_absolute_which_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relative/partial path from ``shutil.which`` (e.g. a spoofed PATH) must not run either."""
    monkeypatch.setattr(manifest_tool.shutil, "which", lambda _name: "git")
    assert manifest_tool.sha256sum_git_show("HEAD", "README.md") is None


def test_sha256sum_git_show_reads_a_known_blob_through_the_guarded_invocation() -> None:
    digest = manifest_tool.sha256sum_git_show("HEAD", "README.md")
    assert digest is not None
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_sha256sum_git_show_returns_none_for_unknown_path() -> None:
    assert manifest_tool.sha256sum_git_show("HEAD", "definitely/not/a/real/path.txt") is None
