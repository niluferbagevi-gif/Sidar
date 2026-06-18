"""Build controlled pip-audit ignore arguments from a dated policy file."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_POLICY_PATH = Path("security/pip-audit-ignores.tsv")


@dataclass(frozen=True)
class PipAuditIgnore:
    vuln_id: str
    package: str
    expires: date
    reason: str


def _parse_iso_date(raw: str, *, line_number: int) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"line {line_number}: invalid expires date {raw!r}; use YYYY-MM-DD"
        ) from exc


def parse_policy(path: Path, *, today: date | None = None) -> list[PipAuditIgnore]:
    """Parse a tab-separated pip-audit ignore policy and reject expired entries."""

    if not path.exists():
        return []

    effective_today = today or date.today()
    ignores: list[PipAuditIgnore] = []
    expired: list[str] = []

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [part.strip() for part in raw_line.split("\t", maxsplit=3)]
        if len(parts) != 4 or any(not part for part in parts):
            raise ValueError(
                f"line {line_number}: expected 4 tab-separated fields: "
                "vuln_id, package, expires, reason"
            )

        vuln_id, package, expires_raw, reason = parts
        expires = _parse_iso_date(expires_raw, line_number=line_number)
        if expires < effective_today:
            expired.append(f"{vuln_id} ({package}) expired on {expires.isoformat()}")
            continue
        ignores.append(
            PipAuditIgnore(vuln_id=vuln_id, package=package, expires=expires, reason=reason)
        )

    if expired:
        raise RuntimeError("Expired pip-audit ignore policy entries: " + "; ".join(expired))
    return ignores


def build_ignore_args(ignores: list[PipAuditIgnore]) -> list[str]:
    """Return pip-audit CLI arguments for active policy entries."""

    args: list[str] = []
    seen: set[str] = set()
    for ignore in ignores:
        if ignore.vuln_id in seen:
            continue
        seen.add(ignore.vuln_id)
        args.extend(["--ignore-vuln", ignore.vuln_id])
    return args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help="Tab-separated policy file with vuln_id, package, expires, reason columns.",
    )
    args = parser.parse_args(argv)

    try:
        ignore_args = build_ignore_args(parse_policy(args.policy))
    except (RuntimeError, ValueError) as exc:
        print(f"pip-audit ignore policy error: {exc}", file=sys.stderr)
        return 2

    for arg in ignore_args:
        print(arg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
