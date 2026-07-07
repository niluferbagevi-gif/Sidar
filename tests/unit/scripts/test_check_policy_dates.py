from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts.ci.check_policy_dates import check_policy_dates, main


def _write_policy_pyproject(path: Path, *, ruff: str, review: str, expires: str) -> None:
    path.write_text(
        f"""
[tool.sidar.ruff_debt]
e501_global_ignore_review_by = "{ruff}"

[tool.sidar.dependency_profile_plan.torch_upgrade_reminder]
review_by = "{review}"
expires = "{expires}"
""",
        encoding="utf-8",
    )


def test_check_policy_dates_accepts_active_repository_dates() -> None:
    failures = check_policy_dates(Path("pyproject.toml"), today=date(2026, 7, 7))

    assert failures == []


def test_check_policy_dates_fails_after_ruff_and_torch_policy_dates(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_policy_pyproject(
        pyproject,
        ruff="2026-09-30",
        review="2026-08-15",
        expires="2026-09-15",
    )

    failures = check_policy_dates(pyproject, today=date(2026, 10, 1))

    assert failures == [
        (
            "Ruff E501 global ignore review "
            "(tool.sidar.ruff_debt.e501_global_ignore_review_by) expired on 2026-09-30"
        ),
        (
            "Torch CVE policy review "
            "(tool.sidar.dependency_profile_plan.torch_upgrade_reminder.review_by) "
            "expired on 2026-08-15"
        ),
        (
            "Torch CVE policy exception "
            "(tool.sidar.dependency_profile_plan.torch_upgrade_reminder.expires) "
            "expired on 2026-09-15"
        ),
    ]


def test_check_policy_dates_cli_returns_nonzero_for_expired_policy(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_policy_pyproject(
        pyproject,
        ruff="2026-09-30",
        review="2026-08-15",
        expires="2026-09-15",
    )

    assert main(["--pyproject", str(pyproject), "--today", "2026-09-16"]) == 1
