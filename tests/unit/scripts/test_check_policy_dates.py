from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts.ci.check_policy_dates import check_policy_date_warnings, check_policy_dates, main


def _write_policy_pyproject(
    path: Path,
    *,
    ruff: str,
    review: str,
    expires: str,
) -> None:
    path.write_text(
        f"""
[tool.sidar.ruff_debt]
docstring_ratchet_review_by = "{ruff}"

[tool.sidar.dependency_profile_plan.torch_upgrade_reminder]
review_by = "{review}"
expires = "{expires}"
""",
        encoding="utf-8",
    )


def test_check_policy_dates_accepts_active_repository_dates() -> None:
    """The committed pyproject has no expired policy dates on a normal day."""
    failures = check_policy_dates(Path("pyproject.toml"), today=date(2026, 7, 7))

    assert failures == []


def test_resolved_repository_torch_review_has_no_date_warning() -> None:
    """A resolved torch CVE reminder produces no upcoming-date warning."""
    warnings = check_policy_date_warnings(Path("pyproject.toml"), today=date(2026, 7, 16))

    assert not any("Torch CVE" in warning for warning in warnings)


def test_repository_ruff_debt_dates_do_not_expire_on_2026_10_01() -> None:
    """The 2026-09-30 E501/ASYNC240/docstring dates were closed or replaced."""
    assert check_policy_dates(Path("pyproject.toml"), today=date(2026, 10, 1)) == []


def test_check_policy_dates_warns_for_docstring_ratchet_review_window(tmp_path: Path) -> None:
    """The D100-D107 ratchet review date warns inside the configured window."""
    pyproject = tmp_path / "pyproject.toml"
    _write_policy_pyproject(
        pyproject,
        ruff="2027-03-31",
        review="2027-12-31",
        expires="2027-12-31",
    )

    warnings = check_policy_date_warnings(pyproject, today=date(2027, 3, 1), warn_within_days=45)

    assert warnings == [
        (
            "Ruff D100-D107 docstring ratchet review "
            "(tool.sidar.ruff_debt.docstring_ratchet_review_by) "
            "is due on 2027-03-31 (30 days remaining)"
        ),
    ]


def test_check_policy_dates_fails_after_ruff_and_torch_policy_dates(tmp_path: Path) -> None:
    """Expired ruff and torch policy dates are all reported, in order."""
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
            "Ruff D100-D107 docstring ratchet review "
            "(tool.sidar.ruff_debt.docstring_ratchet_review_by) expired on 2026-09-30"
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


def test_check_policy_dates_fails_closed_when_docstring_review_date_is_missing(
    tmp_path: Path,
) -> None:
    """A missing docstring ratchet review date is a config error, not a pass."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.sidar.ruff_debt]\n", encoding="utf-8")

    assert main(["--pyproject", str(pyproject), "--today", "2026-10-01"]) == 2


def test_check_policy_dates_cli_does_not_warn_for_resolved_torch_review(capsys) -> None:
    """The CLI stays quiet about a resolved torch CVE review."""
    assert main(["--today", "2026-07-16", "--warn-within-days", "45"]) == 0

    captured = capsys.readouterr()
    assert "Torch CVE policy" not in captured.err


def test_check_policy_dates_cli_returns_nonzero_for_expired_policy(tmp_path: Path) -> None:
    """The CLI exits non-zero once any tracked policy date has expired."""
    pyproject = tmp_path / "pyproject.toml"
    _write_policy_pyproject(
        pyproject,
        ruff="2026-09-30",
        review="2026-08-15",
        expires="2026-09-15",
    )

    assert main(["--pyproject", str(pyproject), "--today", "2026-09-16"]) == 1
