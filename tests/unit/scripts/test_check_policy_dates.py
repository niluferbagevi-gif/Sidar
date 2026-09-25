from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.ci.check_policy_dates import (
    check_policy_date_warnings,
    check_policy_dates,
    main,
    pip_audit_review_dates,
)


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


def _write_runtime_validation_pyproject(path: Path, *, review: str | None) -> None:
    """Write a pyproject whose only live date is the runtime validation review."""
    review_line = f'review_by = "{review}"\n' if review is not None else ""
    path.write_text(
        f"""
[tool.sidar.ruff_debt]
docstring_ratchet_review_by = "2099-01-01"

[tool.sidar.dependency_profile_plan.torch_upgrade_reminder]
status = "resolved"

[tool.sidar.dependency_profile_plan.production_minimal_runtime_validation]
status = "release-blocking"
{review_line}""",
        encoding="utf-8",
    )


def test_check_policy_dates_fails_after_runtime_validation_review(tmp_path: Path) -> None:
    """An overdue production-minimal evidence review fails closed."""
    pyproject = tmp_path / "pyproject.toml"
    _write_runtime_validation_pyproject(pyproject, review="2027-03-31")

    assert check_policy_dates(pyproject, today=date(2027, 3, 31)) == []
    assert check_policy_dates(pyproject, today=date(2027, 4, 1)) == [
        (
            "Production-minimal runtime evidence review "
            "(tool.sidar.dependency_profile_plan.production_minimal_runtime_validation.review_by) "
            "expired on 2027-03-31"
        ),
    ]


def test_check_policy_dates_warns_before_runtime_validation_review(tmp_path: Path) -> None:
    """The production-minimal evidence review warns inside the window."""
    pyproject = tmp_path / "pyproject.toml"
    _write_runtime_validation_pyproject(pyproject, review="2027-03-31")

    warnings = check_policy_date_warnings(pyproject, today=date(2027, 3, 21), warn_within_days=45)

    assert warnings == [
        (
            "Production-minimal runtime evidence review "
            "(tool.sidar.dependency_profile_plan.production_minimal_runtime_validation.review_by) "
            "is due on 2027-03-31 (10 days remaining)"
        ),
    ]


def test_check_policy_dates_requires_runtime_validation_review_date(tmp_path: Path) -> None:
    """A runtime validation section without review_by is a config error."""
    pyproject = tmp_path / "pyproject.toml"
    _write_runtime_validation_pyproject(pyproject, review=None)

    assert main(["--pyproject", str(pyproject), "--today", "2026-10-01"]) == 2


def test_repository_runtime_validation_review_is_tracked() -> None:
    """The committed production-minimal review date is live and was missed before."""
    assert check_policy_dates(Path("pyproject.toml"), today=date(2027, 3, 31)) == []
    failures = check_policy_dates(Path("pyproject.toml"), today=date(2027, 4, 1))

    assert any("Production-minimal runtime evidence review" in f for f in failures)


def _write_pip_audit_policy(path: Path, *rows: str) -> Path:
    path.write_text(
        "# vuln_id\tpackage\texpires\treason\n" + "".join(f"{row}\n" for row in rows),
        encoding="utf-8",
    )
    return path


def test_pip_audit_review_dates_reads_next_review_markers(tmp_path: Path) -> None:
    """Every active ignore entry exposes its next_review date."""
    policy = _write_pip_audit_policy(
        tmp_path / "ignores.tsv",
        "CVE-1\tpkg\t2026-12-31\treason; next_review=2026-11-30.",
        "CVE-2\tpkg\t2026-12-31\tother; next_review=2026-12-15.",
    )

    assert pip_audit_review_dates(policy) == [
        ("CVE-1", date(2026, 11, 30)),
        ("CVE-2", date(2026, 12, 15)),
    ]
    assert pip_audit_review_dates(tmp_path / "missing.tsv") == []


def test_pip_audit_review_dates_require_a_marker(tmp_path: Path) -> None:
    """An ignore entry without next_review is a config error, not a silent pass."""
    policy = _write_pip_audit_policy(tmp_path / "ignores.tsv", "CVE-1\tpkg\t2026-12-31\tno date")
    pyproject = tmp_path / "pyproject.toml"
    _write_runtime_validation_pyproject(pyproject, review="2099-01-01")

    with pytest.raises(ValueError, match="CVE-1 has no next_review"):
        pip_audit_review_dates(policy)
    assert (
        main(
            [
                "--pyproject",
                str(pyproject),
                "--pip-audit-policy",
                str(policy),
                "--today",
                "2026-10-01",
            ]
        )
        == 2
    )


def test_overdue_pip_audit_review_fails_before_the_entry_expires(tmp_path: Path) -> None:
    """A missed next_review turns CI red while the ignore itself is still active."""
    policy = _write_pip_audit_policy(
        tmp_path / "ignores.tsv", "CVE-1\tpkg\t2026-12-31\treason; next_review=2026-11-30."
    )
    pyproject = tmp_path / "pyproject.toml"
    _write_runtime_validation_pyproject(pyproject, review="2099-01-01")

    assert check_policy_dates(pyproject, today=date(2026, 11, 30), pip_audit_policy=policy) == []
    assert check_policy_dates(pyproject, today=date(2026, 12, 1), pip_audit_policy=policy) == [
        f"pip-audit ignore review for CVE-1 ({policy} next_review) expired on 2026-11-30"
    ]
    assert check_policy_date_warnings(
        pyproject, today=date(2026, 11, 20), warn_within_days=45, pip_audit_policy=policy
    ) == [
        f"pip-audit ignore review for CVE-1 ({policy} next_review) "
        "is due on 2026-11-30 (10 days remaining)"
    ]
    assert (
        main(
            [
                "--pyproject",
                str(pyproject),
                "--pip-audit-policy",
                str(policy),
                "--today",
                "2026-12-01",
            ]
        )
        == 1
    )


def test_repository_pip_audit_ignores_carry_live_review_dates() -> None:
    """The committed ignore policy is reviewed on schedule by the CI date gate."""
    policy = Path("security/pip-audit-ignores.tsv")
    reviews = pip_audit_review_dates(policy)

    assert reviews
    assert all(review < date(2027, 1, 1) for _, review in reviews)
