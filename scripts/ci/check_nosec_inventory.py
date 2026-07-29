"""Ratchet-enforce security/nosec_inventory.tsv against real `# nosec` suppressions.

Bandit's own `nosec` reports (bandit_report.json etc.) are silent by design: a
suppressed finding simply disappears from the CI-facing report. That silence is
useful for genuinely reviewed suppressions and dangerous for unreviewed ones,
since nothing forces a suppression to ever be revisited. This script closes
that gap without touching Bandit's skip behavior itself:

1. Every real `# nosec` comment in tracked Python source must have a matching
   `security/nosec_inventory.tsv` entry (path, line) - no silent/unregistered
   suppressions.
2. Every inventory entry must still point at a real `# nosec` at that exact
   (path, line) - if the code moved, the entry is stale and must be updated
   rather than left describing a line that no longer exists.
3. `review_by` dates that have passed fail closed, exactly like the other
   dated-policy checks in this repo (see scripts/ci/check_policy_dates.py).
4. The total number of registered entries can never exceed the ratchet
   ceiling recorded in the inventory file's `# ratchet_max_entries: N` header
   line. The ceiling only ever moves down, via `--update`, never up by hand.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tokenize
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY_PATH = ROOT / "security/nosec_inventory.tsv"
RATCHET_HEADER_RE = re.compile(r"^#\s*ratchet_max_entries:\s*(\d+)\s*$", re.MULTILINE)
NOSEC_COMMENT_RE = re.compile(r"#\s*nosec\b\s*(?P<codes>(?:[:,]?\s*B\d{3}\s*)*)", re.IGNORECASE)


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    line: int
    bandit_rule: str
    reason: str
    owner: str
    review_by: date
    replacement_plan: str


def _parse_iso_date(raw: str, *, line_number: int) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"nosec_inventory.tsv line {line_number}: invalid review_by date {raw!r}; "
            "use YYYY-MM-DD"
        ) from exc


def parse_inventory(path: Path) -> tuple[list[InventoryEntry], int | None]:
    """Parse the inventory TSV, returning (entries, ratchet_max_entries)."""
    if not path.exists():
        return [], None

    entries: list[InventoryEntry] = []
    ratchet_max_entries: int | None = None

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            ratchet_match = RATCHET_HEADER_RE.match(stripped)
            if ratchet_match:
                ratchet_max_entries = int(ratchet_match.group(1))
            continue

        parts = [part.strip() for part in raw_line.split("\t", maxsplit=6)]
        if len(parts) != 7 or any(not part for part in parts):
            raise ValueError(
                f"nosec_inventory.tsv line {line_number}: expected 7 tab-separated fields: "
                "path, line, bandit_rule, reason, owner, review_by, replacement_plan"
            )
        entry_path, line_raw, bandit_rule, reason, owner, review_by_raw, replacement_plan = parts
        try:
            entry_line = int(line_raw)
        except ValueError as exc:
            raise ValueError(
                f"nosec_inventory.tsv line {line_number}: line field must be an integer, "
                f"got {line_raw!r}"
            ) from exc
        entries.append(
            InventoryEntry(
                path=entry_path,
                line=entry_line,
                bandit_rule=bandit_rule,
                reason=reason,
                owner=owner,
                review_by=_parse_iso_date(review_by_raw, line_number=line_number),
                replacement_plan=replacement_plan,
            )
        )

    return entries, ratchet_max_entries


def _normalize_codes(raw_codes: str) -> str:
    normalized = re.sub(r"[:,]", " ", raw_codes.strip())
    return " ".join(normalized.split()) or "ALL"


def _bandit_exclude_dirs(root: Path) -> set[str]:
    """Read `[tool.bandit] exclude_dirs` so this checker's scope matches Bandit's.

    A `# nosec` under a directory Bandit never scans (e.g. `tests/`) produces no
    Bandit finding and needs no inventory entry; without this, adding ordinary
    test fixtures that happen to contain the literal text `# nosec` would force
    pointless inventory registrations for suppressions Bandit itself ignores.
    """
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.exists():
        return set()
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    raw = data.get("tool", {}).get("bandit", {}).get("exclude_dirs", [])
    return {str(item) for item in raw if item}


def collect_nosec_occurrences(root: Path) -> dict[tuple[str, int], str]:
    """Return {(relative_path, line): bandit_codes} for every real `# nosec` comment.

    Uses `tokenize` (not a text/regex scan) so that "nosec" appearing inside a
    string literal or a `#`-comment that merely *talks about* nosec - rather
    than being one - is never mistaken for a real suppression.
    """
    tracked_files = subprocess.check_output(  # nosec B603 B607  # fixed git subcommand, no shell.
        ["git", "-C", str(root), "ls-files", "*.py"], text=True
    ).splitlines()
    exclude_dirs = _bandit_exclude_dirs(root)

    occurrences: dict[tuple[str, int], str] = {}
    for relative_path in tracked_files:
        if not relative_path:
            continue
        if exclude_dirs and set(Path(relative_path).parts) & exclude_dirs:
            continue
        file_path = root / relative_path
        try:
            with file_path.open("rb") as file_obj:
                tokens = tokenize.tokenize(file_obj.readline)
                for tok in tokens:
                    if tok.type != tokenize.COMMENT or "nosec" not in tok.string.lower():
                        continue
                    match = NOSEC_COMMENT_RE.search(tok.string)
                    if not match:
                        continue
                    occurrences[(relative_path, tok.start[0])] = _normalize_codes(
                        match.group("codes")
                    )
        except (SyntaxError, tokenize.TokenError, UnicodeDecodeError, OSError):
            continue
    return occurrences


def check_nosec_inventory(
    root: Path,
    inventory_path: Path = DEFAULT_INVENTORY_PATH,
    *,
    today: date | None = None,
) -> list[str]:
    """Return a list of human-readable failures, empty when the inventory is clean."""
    effective_today = today or date.today()
    entries, ratchet_max_entries = parse_inventory(inventory_path)
    occurrences = collect_nosec_occurrences(root)

    failures: list[str] = []

    registered_keys = {(entry.path, entry.line) for entry in entries}
    unregistered = sorted(set(occurrences) - registered_keys)
    for path, line in unregistered:
        failures.append(
            f"unregistered nosec: {path}:{line} has a `# nosec` suppression not listed in "
            f"{inventory_path.name}. Add an entry (path, line, bandit_rule, reason, owner, "
            "review_by, replacement_plan)."
        )

    for entry in entries:
        key = (entry.path, entry.line)
        if key not in occurrences:
            failures.append(
                f"stale nosec entry: {inventory_path.name} lists {entry.path}:{entry.line} but "
                "no `# nosec` exists there anymore. If the line moved, update the entry; if the "
                "suppression was removed, delete the entry."
            )
            continue
        actual_codes = occurrences[key]
        if entry.bandit_rule != actual_codes:
            failures.append(
                f"nosec rule mismatch: {entry.path}:{entry.line} is suppressed for "
                f"{actual_codes!r} but {inventory_path.name} records bandit_rule={entry.bandit_rule!r}."
            )
        if entry.review_by < effective_today:
            failures.append(
                f"expired nosec review: {entry.path}:{entry.line} review_by "
                f"{entry.review_by.isoformat()} has passed; re-review and update the entry "
                f"(owner: {entry.owner})."
            )

    if ratchet_max_entries is None:
        failures.append(
            f"{inventory_path.name} is missing a `# ratchet_max_entries: N` header line."
        )
    elif len(entries) > ratchet_max_entries:
        failures.append(
            f"nosec ratchet exceeded: {len(entries)} registered entries > "
            f"ratchet_max_entries={ratchet_max_entries}. New suppressions must replace/remove "
            "an existing one, or the ratchet must be raised deliberately in the same PR that "
            "adds the suppression (never silently)."
        )

    return failures


def update_ratchet(inventory_path: Path = DEFAULT_INVENTORY_PATH) -> int:
    """Rewrite the `# ratchet_max_entries:` header to the current registered entry count."""
    entries, _ = parse_inventory(inventory_path)
    content = inventory_path.read_text(encoding="utf-8")
    new_content, count = RATCHET_HEADER_RE.subn(
        f"# ratchet_max_entries: {len(entries)}", content, count=1
    )
    if count != 1:
        raise ValueError(f"{inventory_path.name} is missing a `# ratchet_max_entries:` header line")
    inventory_path.write_text(new_content, encoding="utf-8")
    return len(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--today", default="", help="Override current date for tests (YYYY-MM-DD).")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite ratchet_max_entries to the current registered entry count and exit.",
    )
    args = parser.parse_args(argv)

    if args.update:
        new_ceiling = update_ratchet(args.inventory)
        print(f"nosec ratchet_max_entries updated to {new_ceiling}")
        return 0

    today = date.fromisoformat(args.today) if args.today else None
    try:
        failures = check_nosec_inventory(args.root, args.inventory, today=today)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"nosec inventory check error: {exc}", file=sys.stderr)
        return 2

    if failures:
        print("security/nosec_inventory.tsv drift detected:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("security/nosec_inventory.tsv matches the tracked `# nosec` suppressions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
