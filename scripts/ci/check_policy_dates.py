"""Fail closed when dated pyproject policy/debt markers have expired."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_PYPROJECT = Path("pyproject.toml")
DEFAULT_PIP_AUDIT_POLICY = Path("security/pip-audit-ignores.tsv")
NEXT_REVIEW_RE = re.compile(r"next_review=(\d{4}-\d{2}-\d{2})")
RUNTIME_VALIDATION_KEY = (
    "tool.sidar.dependency_profile_plan.production_minimal_runtime_validation.review_by"
)


def _parse_date(value: Any, *, key: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


def _add_if_expired(
    failures: list[str],
    *,
    label: str,
    value: Any,
    key: str,
    today: date,
) -> None:
    policy_date = _parse_date(value, key=key)
    if policy_date < today:
        failures.append(f"{label} ({key}) expired on {policy_date.isoformat()}")


def _add_if_due_soon(
    warnings: list[str],
    *,
    label: str,
    value: Any,
    key: str,
    today: date,
    warn_within_days: int,
) -> None:
    policy_date = _parse_date(value, key=key)
    days_remaining = (policy_date - today).days
    if 0 <= days_remaining <= warn_within_days:
        warnings.append(
            f"{label} ({key}) is due on {policy_date.isoformat()} ({days_remaining} days remaining)"
        )


def pip_audit_review_dates(policy_path: Path) -> list[tuple[str, date]]:
    """Return ``(vuln_id, next_review)`` for every active pip-audit ignore entry.

    Expiry itself is enforced by ``scripts/pip_audit_ignore_args.py`` in the
    security gate; the ``next_review=`` marker in each reason is the earlier,
    softer date that was repeatedly missed, so it is tracked here as well.

    Raises:
        ValueError: When an entry has no ``next_review=YYYY-MM-DD`` marker.
    """
    if not policy_path.exists():
        return []
    dates: list[tuple[str, date]] = []
    for line_number, raw_line in enumerate(
        policy_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        vuln_id = raw_line.split("\t", 1)[0].strip()
        match = NEXT_REVIEW_RE.search(raw_line)
        if match is None:
            raise ValueError(
                f"{policy_path}:{line_number}: {vuln_id} has no next_review=YYYY-MM-DD marker"
            )
        dates.append(
            (vuln_id, _parse_date(match.group(1), key=f"{policy_path}:{line_number} next_review"))
        )
    return dates


def check_policy_date_warnings(
    pyproject_path: Path,
    *,
    today: date | None = None,
    warn_within_days: int | None = None,
    pip_audit_policy: Path | None = None,
) -> list[str]:
    """Return active dated policy/debt markers that are approaching review/expiry."""
    effective_today = today or date.today()
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    sidar = data.get("tool", {}).get("sidar", {})
    ruff_debt = sidar.get("ruff_debt", {})
    dependency_plan = sidar.get("dependency_profile_plan", {})
    torch_reminder = dependency_plan.get("torch_upgrade_reminder", {})
    runtime_validation = dependency_plan.get("production_minimal_runtime_validation")
    configured_window = torch_reminder.get("warning_window_days", 45)
    warning_window = (
        warn_within_days if warn_within_days is not None else int(configured_window or 45)
    )
    warnings: list[str] = []

    if torch_reminder.get("status") != "resolved":
        _add_if_due_soon(
            warnings,
            label="Torch CVE policy review",
            value=torch_reminder.get("review_by", ""),
            key="tool.sidar.dependency_profile_plan.torch_upgrade_reminder.review_by",
            today=effective_today,
            warn_within_days=warning_window,
        )
        _add_if_due_soon(
            warnings,
            label="Torch CVE policy exception",
            value=torch_reminder.get("expires", ""),
            key="tool.sidar.dependency_profile_plan.torch_upgrade_reminder.expires",
            today=effective_today,
            warn_within_days=warning_window,
        )
    _add_if_due_soon(
        warnings,
        label="Ruff D100-D107 docstring ratchet review",
        value=ruff_debt.get("docstring_ratchet_review_by", ""),
        key="tool.sidar.ruff_debt.docstring_ratchet_review_by",
        today=effective_today,
        warn_within_days=warning_window,
    )
    if runtime_validation is not None:
        _add_if_due_soon(
            warnings,
            label="Production-minimal runtime evidence review",
            value=runtime_validation.get("review_by", ""),
            key=RUNTIME_VALIDATION_KEY,
            today=effective_today,
            warn_within_days=warning_window,
        )
    if pip_audit_policy is not None:
        for vuln_id, next_review in pip_audit_review_dates(pip_audit_policy):
            _add_if_due_soon(
                warnings,
                label=f"pip-audit ignore review for {vuln_id}",
                value=next_review.isoformat(),
                key=f"{pip_audit_policy} next_review",
                today=effective_today,
                warn_within_days=warning_window,
            )
    return warnings


def check_policy_dates(
    pyproject_path: Path, *, today: date | None = None, pip_audit_policy: Path | None = None
) -> list[str]:
    """Return expired dated policy/debt markers from pyproject.toml."""
    effective_today = today or date.today()
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    sidar = data.get("tool", {}).get("sidar", {})
    failures: list[str] = []

    ruff_debt = sidar.get("ruff_debt", {})
    _add_if_expired(
        failures,
        label="Ruff D100-D107 docstring ratchet review",
        value=ruff_debt.get("docstring_ratchet_review_by", ""),
        key="tool.sidar.ruff_debt.docstring_ratchet_review_by",
        today=effective_today,
    )

    dependency_plan = sidar.get("dependency_profile_plan", {})
    torch_reminder = dependency_plan.get("torch_upgrade_reminder", {})
    if torch_reminder.get("status") != "resolved":
        _add_if_expired(
            failures,
            label="Torch CVE policy review",
            value=torch_reminder.get("review_by", ""),
            key="tool.sidar.dependency_profile_plan.torch_upgrade_reminder.review_by",
            today=effective_today,
        )
        _add_if_expired(
            failures,
            label="Torch CVE policy exception",
            value=torch_reminder.get("expires", ""),
            key="tool.sidar.dependency_profile_plan.torch_upgrade_reminder.expires",
            today=effective_today,
        )

    # Once the section exists its review date is mandatory: a missing or
    # malformed value is a config error rather than a silent pass.
    runtime_validation = dependency_plan.get("production_minimal_runtime_validation")
    if runtime_validation is not None:
        _add_if_expired(
            failures,
            label="Production-minimal runtime evidence review",
            value=runtime_validation.get("review_by", ""),
            key=RUNTIME_VALIDATION_KEY,
            today=effective_today,
        )

    # An overdue next_review fails here, weeks before the entry's hard expiry
    # breaks the pip-audit security gate.
    if pip_audit_policy is not None:
        for vuln_id, next_review in pip_audit_review_dates(pip_audit_policy):
            _add_if_expired(
                failures,
                label=f"pip-audit ignore review for {vuln_id}",
                value=next_review.isoformat(),
                key=f"{pip_audit_policy} next_review",
                today=effective_today,
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    """Report upcoming policy dates and fail on expired or malformed ones."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_PYPROJECT)
    parser.add_argument("--pip-audit-policy", type=Path, default=DEFAULT_PIP_AUDIT_POLICY)
    parser.add_argument("--today", default="", help="Override current date for tests (YYYY-MM-DD).")
    parser.add_argument(
        "--warn-within-days",
        type=int,
        default=None,
        help="Print non-failing warnings for policy dates due within this many days.",
    )
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else None
    try:
        failures = check_policy_dates(
            args.pyproject, today=today, pip_audit_policy=args.pip_audit_policy
        )
        warnings = check_policy_date_warnings(
            args.pyproject,
            today=today,
            warn_within_days=args.warn_within_days,
            pip_audit_policy=args.pip_audit_policy,
        )
    except (OSError, ValueError) as exc:
        print(f"policy date check error: {exc}", file=sys.stderr)
        return 2

    if warnings:
        print("Upcoming Sidar policy/debt dates:", file=sys.stderr)
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)

    if failures:
        print("Expired Sidar policy/debt dates:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
