"""Remove Windows Mark-of-the-Web Zone.Identifier sidecar artifacts.

On Windows these markers are normally stored as NTFS Alternate Data Streams
(e.g. ``file.py:Zone.Identifier``).  When files are copied through WSL, archives,
or cross-platform tools, those streams can appear as ordinary sidecar files in a
repository.  They are not project source and should not be linted, packaged, or
covered.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

ZONE_IDENTIFIER_SUFFIX = ":Zone.Identifier"
DEFAULT_PRUNED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "htmlcov",
    }
)


def find_zone_identifier_files(root: Path, *, pruned_dirs: set[str] | None = None) -> list[Path]:
    """Return ordinary files whose names end with ``:Zone.Identifier``."""

    root = root.resolve()
    ignored_dirs = DEFAULT_PRUNED_DIRS if pruned_dirs is None else frozenset(pruned_dirs)
    matches: list[Path] = []

    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ignored_dirs]
        current_path = Path(current_root)
        for filename in filenames:
            if filename.endswith(ZONE_IDENTIFIER_SUFFIX):
                matches.append(current_path / filename)
    return sorted(matches)


def remove_zone_identifier_files(root: Path, *, dry_run: bool = False) -> list[Path]:
    """Delete Zone.Identifier sidecar files under ``root`` and return matches."""

    matches = find_zone_identifier_files(root)
    if dry_run:
        return matches

    for path in matches:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
    return matches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete Windows Zone.Identifier sidecar files from the repository tree."
    )
    parser.add_argument("--root", default=".", type=Path, help="Repository root to scan.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list matching files; do not delete anything.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    matches = remove_zone_identifier_files(args.root, dry_run=args.dry_run)

    if not matches:
        print("Zone.Identifier sidecar artifact bulunamadı.")
        return 0

    action = "Bulundu" if args.dry_run else "Silindi"
    print(f"{action}: {len(matches)} Zone.Identifier sidecar artifact")
    for path in matches:
        print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
