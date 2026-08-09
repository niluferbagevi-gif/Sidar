"""Fail closed when dated pyproject policy/debt markers have expired."""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_PYPROJECT = Path("pyproject.toml")


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


def check_policy_date_warnings(
    pyproject_path: Path, *, today: date | None = None, warn_within_days: int | None = None
) -> list[str]:
    """Return active dated policy/debt markers that are approaching review/expiry."""
    effective_today = today or date.today()
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    sidar = data.get("tool", {}).get("sidar", {})
    ruff_debt = sidar.get("ruff_debt", {})
    torch_reminder = sidar.get("dependency_profile_plan", {}).get("torch_upgrade_reminder", {})
    configured_window = torch_reminder.get("warning_window_days", 45)
    warning_window = (
        warn_within_days if warn_within_days is not None else int(configured_window or 45)
    )
    warnings: list[str] = []

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
        label="Ruff E501 global ignore review",
        value=ruff_debt.get("e501_global_ignore_review_by", ""),
        key="tool.sidar.ruff_debt.e501_global_ignore_review_by",
        today=effective_today,
        warn_within_days=warning_window,
    )
    _add_if_due_soon(
        warnings,
        label="Ruff docstring debt campaign close",
        value=ruff_debt.get("close_docstring_campaign_by", ""),
        key="tool.sidar.ruff_debt.close_docstring_campaign_by",
        today=effective_today,
        warn_within_days=warning_window,
    )
    _add_if_due_soon(
        warnings,
        label="Ruff ASYNC240 debt campaign close",
        value=ruff_debt.get("close_async240_campaign_by", ""),
        key="tool.sidar.ruff_debt.close_async240_campaign_by",
        today=effective_today,
        warn_within_days=warning_window,
    )
    return warnings


def check_policy_dates(pyproject_path: Path, *, today: date | None = None) -> list[str]:
    """Return expired dated policy/debt markers from pyproject.toml."""
    effective_today = today or date.today()
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    sidar = data.get("tool", {}).get("sidar", {})
    failures: list[str] = []

    ruff_debt = sidar.get("ruff_debt", {})
    _add_if_expired(
        failures,
        label="Ruff E501 global ignore review",
        value=ruff_debt.get("e501_global_ignore_review_by", ""),
        key="tool.sidar.ruff_debt.e501_global_ignore_review_by",
        today=effective_today,
    )
    _add_if_expired(
        failures,
        label="Ruff docstring debt campaign close",
        value=ruff_debt.get("close_docstring_campaign_by", ""),
        key="tool.sidar.ruff_debt.close_docstring_campaign_by",
        today=effective_today,
    )
    _add_if_expired(
        failures,
        label="Ruff ASYNC240 debt campaign close",
        value=ruff_debt.get("close_async240_campaign_by", ""),
        key="tool.sidar.ruff_debt.close_async240_campaign_by",
        today=effective_today,
    )

    torch_reminder = sidar.get("dependency_profile_plan", {}).get("torch_upgrade_reminder", {})
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
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_PYPROJECT)
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
        failures = check_policy_dates(args.pyproject, today=today)
        warnings = check_policy_date_warnings(
            args.pyproject, today=today, warn_within_days=args.warn_within_days
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
