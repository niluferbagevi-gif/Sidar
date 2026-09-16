"""Fail closed when a CHANGELOG.md [Unreleased] entry exceeds its word budget.

CHANGELOG.md documents (see its own top-of-file note) that it "contains only
version-to-version diffs, short fix notes, and tech-debt-closure summaries"
and that detailed resolution history belongs in docs/archive/. Nothing
previously enforced that: individual [Unreleased] entries had grown into
multi-paragraph root-cause essays, pushing the file past 1200 lines / 300 KB
(see docs/archive/unreleased_root_cause_detail.md for the archived detail
that caused this check to be added).

This check turns that documented policy into an enforced, one-way budget:
each top-level bullet (`- **...`) inside the current ``## [Unreleased]``
section must stay within a word-count budget (roughly 2-3 sentences). Detail
beyond that -- root-cause analysis, rejected alternatives, exhaustive test
references -- belongs in docs/archive/ (docs/archive/resolved_issues_v3.md's
next phase once a version closes, or docs/archive/unreleased_root_cause_detail.md
before that), linked from the short entry if useful.

Deliberately simpler than the bandit-suppression and module-notes ratchets
(no ``--update`` flag, and the budget is a fixed per-entry word count rather
than a single running total): a legitimate long entry is a sign the detail
belongs in the archive, not a baseline to raise.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET_PATH = ROOT / "CHANGELOG.md"
DEFAULT_BASELINE = ROOT / "scripts" / "ci" / "changelog-entry-budget-baseline.json"

_UNRELEASED_HEADER = re.compile(r"^## \[Unreleased\]\s*$")
_NEXT_RELEASE_HEADER = re.compile(r"^## \[")
_BULLET = re.compile(r"^- \*\*")


def unreleased_entries(text: str) -> list[tuple[int, str]]:
    """Return (line_number, line) for each top-level bullet in ``## [Unreleased]``."""
    lines = text.splitlines()
    entries: list[tuple[int, str]] = []
    in_unreleased = False
    for lineno, line in enumerate(lines, start=1):
        if _UNRELEASED_HEADER.match(line):
            in_unreleased = True
            continue
        if in_unreleased and _NEXT_RELEASE_HEADER.match(line):
            break
        if in_unreleased and _BULLET.match(line):
            entries.append((lineno, line))
    return entries


def word_count(line: str) -> int:
    """Return the whitespace-delimited word count of a single bullet line."""
    return len(line.split())


def main(argv: list[str] | None = None) -> int:
    """Check every [Unreleased] bullet against the committed per-entry word budget."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=TARGET_PATH)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args(argv)

    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        maximum = baseline["maximum_words_per_entry"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"CHANGELOG entry budget baseline is invalid: {args.baseline}: {exc}")
        return 2
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        print("maximum_words_per_entry must be a positive integer")
        return 2

    if not args.target.is_file():
        print(f"CHANGELOG.md not found: {args.target}")
        return 2

    text = args.target.read_text(encoding="utf-8")
    entries = unreleased_entries(text)
    violations = [
        (lineno, word_count(line)) for lineno, line in entries if word_count(line) > maximum
    ]

    print(
        f"CHANGELOG.md [Unreleased] madde bütçesi: {len(entries)} madde denetlendi "
        f"(maximum={maximum} kelime/madde)"
    )
    if not violations:
        return 0

    print(
        f"{len(violations)} madde kelime bütçesini aşıyor. Yeni maddeler 2-3 cümleyle "
        "sınırlı tutulmalı; kök-neden analizi/test referansları gibi ayrıntılar "
        "docs/archive/ altına (bkz. docs/archive/unreleased_root_cause_detail.md) taşınmalı:"
    )
    for lineno, count in violations:
        print(f"  - CHANGELOG.md:{lineno} ({count} kelime > {maximum})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
