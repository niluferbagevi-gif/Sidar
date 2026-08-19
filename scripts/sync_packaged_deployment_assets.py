"""Synchronize packaged Helm chart and docker_setup assets from the repository source tree.

``helm/sidar/`` and ``docker_setup/`` are the single sources of truth for deployment
assets. The ``sidar_assets/helm/sidar/`` and ``sidar_assets/docker_setup/`` copies exist
only so installed wheel/sdist builds ship the same manifests without importing from an
editable checkout. ``sidar_assets/paths.py`` prefers the packaged copy over the
repository layout whenever it is present (wheel/container installs), so a stale or
hand-edited packaged copy ships silently broken deployment assets — see
``tests/unit/core/test_assets_and_offline_bundle.py`` for the parity guard this script
keeps green.
"""

from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SYNC_TARGETS: tuple[tuple[Path, Path], ...] = (
    (PROJECT_ROOT / "helm" / "sidar", PROJECT_ROOT / "sidar_assets" / "helm" / "sidar"),
    (PROJECT_ROOT / "docker_setup", PROJECT_ROOT / "sidar_assets" / "docker_setup"),
)


def _mirror_directory(source: Path, destination: Path) -> list[Path]:
    """Make ``destination`` byte-for-byte identical to ``source``.

    Copies every file from ``source`` into ``destination`` (creating directories as
    needed) and removes any file or now-empty directory under ``destination`` that no
    longer exists in ``source``, so stale packaged files cannot linger and drift
    silently.
    """
    synced: list[Path] = []
    source_files = {path.relative_to(source) for path in source.rglob("*") if path.is_file()}

    for relative_path in sorted(source_files):
        destination_file = destination / relative_path
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative_path, destination_file)
        synced.append(destination_file)

    if destination.is_dir():
        for existing in sorted(destination.rglob("*"), reverse=True):
            if existing.is_file():
                if existing.relative_to(destination) not in source_files:
                    existing.unlink()
            elif existing.is_dir() and not any(existing.iterdir()):
                existing.rmdir()

    return synced


def sync_packaged_deployment_assets() -> list[Path]:
    """Mirror the Helm chart and docker_setup source trees into ``sidar_assets/``."""
    synced: list[Path] = []
    for source, destination in SYNC_TARGETS:
        synced.extend(_mirror_directory(source, destination))
    return synced


def main() -> None:
    synced = sync_packaged_deployment_assets()
    print(f"Synced {len(synced)} packaged deployment asset file(s).")
    for path in synced:
        print(path.relative_to(PROJECT_ROOT).as_posix())


if __name__ == "__main__":
    main()
