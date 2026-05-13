from __future__ import annotations

from pathlib import Path

from scripts import cleanup_zone_identifier
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


def test_find_zone_identifier_files_accepts_custom_pruned_dirs(tmp_path: Path) -> None:
    skipped = tmp_path / "custom" / "ignored.txt:Zone.Identifier"
    skipped.parent.mkdir()
    skipped.write_text("ignored", encoding="utf-8")
    included = tmp_path / ".git" / "config:Zone.Identifier"
    included.parent.mkdir()
    included.write_text("included when defaults are replaced", encoding="utf-8")

    matches = find_zone_identifier_files(tmp_path, pruned_dirs={"custom"})

    assert matches == [included]


def test_remove_zone_identifier_files_ignores_raced_deletions(tmp_path: Path, monkeypatch) -> None:
    sidecar = tmp_path / "asset.png:Zone.Identifier"
    sidecar.write_text("metadata", encoding="utf-8")

    def raise_file_not_found(self: Path) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(Path, "unlink", raise_file_not_found)

    matches = remove_zone_identifier_files(tmp_path)

    assert matches == [sidecar]


def test_main_reports_no_artifacts(tmp_path: Path, capsys) -> None:
    exit_code = cleanup_zone_identifier.main(["--root", str(tmp_path)])

    assert exit_code == 0
    assert capsys.readouterr().out == "Zone.Identifier sidecar artifact bulunamadı.\n"


def test_main_dry_run_lists_artifacts_without_deleting(tmp_path: Path, capsys) -> None:
    sidecar = tmp_path / "download.zip:Zone.Identifier"
    sidecar.write_text("metadata", encoding="utf-8")

    exit_code = cleanup_zone_identifier.main(["--root", str(tmp_path), "--dry-run"])

    assert exit_code == 0
    output_lines = capsys.readouterr().out.splitlines()
    assert output_lines == [
        "Bulundu: 1 Zone.Identifier sidecar artifact",
        str(sidecar),
    ]
    assert sidecar.exists()


def test_main_delete_lists_removed_artifacts(tmp_path: Path, capsys) -> None:
    sidecar = tmp_path / "download.zip:Zone.Identifier"
    sidecar.write_text("metadata", encoding="utf-8")

    exit_code = cleanup_zone_identifier.main(["--root", str(tmp_path)])

    assert exit_code == 0
    output_lines = capsys.readouterr().out.splitlines()
    assert output_lines == [
        "Silindi: 1 Zone.Identifier sidecar artifact",
        str(sidecar),
    ]
    assert not sidecar.exists()
