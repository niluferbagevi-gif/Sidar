import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
METADATA_HELPER = REPO_ROOT / "scripts/install_modules/utils/repo_metadata.sh"


def _run_bash(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_installer_metadata_reports_version_revision_and_dirty_state(tmp_path: Path) -> None:
    assert (
        _run_bash(
            "git init -q && git config user.email test@example.com && git config user.name Test",
            tmp_path,
        ).returncode
        == 0
    )
    (tmp_path / "tracked.txt").write_text("clean\n", encoding="utf-8")
    assert _run_bash("git add tracked.txt && git commit -qm initial", tmp_path).returncode == 0

    clean = _run_bash(
        f"source {METADATA_HELPER!s}; INSTALL_SIDAR_VERSION=5.2.0; "
        f"sidar_report_install_source_metadata {tmp_path!s}",
        tmp_path,
    )

    expected_commit = _run_bash("git rev-parse HEAD", tmp_path).stdout.strip()
    assert clean.returncode == 0
    assert "Sidar version : 5.2.0" in clean.stdout
    assert "Git branch    : " in clean.stdout
    assert f"Git commit    : {expected_commit}" in clean.stdout
    assert "Git dirty     : false" in clean.stdout

    (tmp_path / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty = _run_bash(
        f"source {METADATA_HELPER!s}; INSTALL_SIDAR_VERSION=5.2.0; "
        f"sidar_report_install_source_metadata {tmp_path!s}",
        tmp_path,
    )
    assert "Git dirty     : true" in dirty.stdout


def test_installer_metadata_degrades_explicitly_outside_git(tmp_path: Path) -> None:
    result = _run_bash(
        f"source {METADATA_HELPER!s}; INSTALL_SIDAR_VERSION=5.2.0; "
        f"sidar_report_install_source_metadata {tmp_path!s}",
        tmp_path,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "Sidar version : 5.2.0",
        "Git branch    : unavailable",
        "Git commit    : unavailable",
        "Git dirty     : unknown",
    ]
