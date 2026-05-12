from __future__ import annotations

from pathlib import Path

from scripts.cleanup_zone_identifier import (
    find_zone_identifier_files,
    remove_zone_identifier_files,
)


def test_find_zone_identifier_files_discovers_sidecars_and_prunes_git(tmp_path: Path) -> None:
    sidecar = tmp_path / "downloaded.py:Zone.Identifier"
    sidecar.write_text("[ZoneTransfer]\nZoneId=3\n", encoding="utf-8")
    regular = tmp_path / "downloaded.py"
    regular.write_text("print('ok')\n", encoding="utf-8")
    git_sidecar = tmp_path / ".git" / "config:Zone.Identifier"
    git_sidecar.parent.mkdir()
    git_sidecar.write_text("ignored", encoding="utf-8")

    matches = find_zone_identifier_files(tmp_path)

    assert matches == [sidecar]


def test_remove_zone_identifier_files_deletes_only_sidecars(tmp_path: Path) -> None:
    sidecar = tmp_path / "asset.png:Zone.Identifier"
    sidecar.write_text("metadata", encoding="utf-8")
    regular = tmp_path / "asset.png"
    regular.write_text("image bytes", encoding="utf-8")

    matches = remove_zone_identifier_files(tmp_path)

    assert matches == [sidecar]
    assert not sidecar.exists()
    assert regular.exists()


def test_remove_zone_identifier_files_dry_run_keeps_files(tmp_path: Path) -> None:
    sidecar = tmp_path / "doc.pdf:Zone.Identifier"
    sidecar.write_text("metadata", encoding="utf-8")

    matches = remove_zone_identifier_files(tmp_path, dry_run=True)

    assert matches == [sidecar]
    assert sidecar.exists()
