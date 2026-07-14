"""Synchronize packaged Alembic migrations from the repository source tree.

The top-level ``migrations/`` directory is the single source of truth. The
``sidar_assets/migrations/`` copy exists only so installed wheel/sdist builds can
run the same Alembic history without importing from an editable checkout.
"""

from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "migrations"
PACKAGED_DIR = PROJECT_ROOT / "sidar_assets" / "migrations"
SYNC_PATTERNS = ("*.py", "*.mako")


def _sync_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def sync_packaged_migrations() -> list[Path]:
    """Copy source Alembic migration files into ``sidar_assets/migrations``."""

    synced: list[Path] = []
    for pattern in SYNC_PATTERNS:
        for source in sorted(SOURCE_DIR.rglob(pattern)):
            relative_path = source.relative_to(SOURCE_DIR)
            destination = PACKAGED_DIR / relative_path
            _sync_file(source, destination)
            synced.append(destination.relative_to(PROJECT_ROOT))
    return synced


def main() -> None:
    synced = sync_packaged_migrations()
    print(f"Synced {len(synced)} packaged migration file(s).")
    for path in synced:
        print(path.as_posix())


if __name__ == "__main__":
    main()
