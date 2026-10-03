"""Contract tests for the read-only self-hosted runner host continuity doctor."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_runner_host_continuity.sh"
RUNBOOK = ROOT / "docs" / "runbooks" / "gpu-runner-continuity.md"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_help_and_unknown_argument_contract() -> None:
    """--help exits cleanly; an unknown flag is a usage error, not a finding."""
    help_result = _run("--help")
    assert help_result.returncode == 0
    assert "--since" in help_result.stdout

    bad = _run("--bogus")
    assert bad.returncode == 2
    assert "Bilinmeyen argüman" in bad.stderr


def test_runs_on_any_linux_host_and_reports_a_verdict() -> None:
    """The doctor must finish on a non-runner host with a PASS/FAIL verdict, never crash."""
    result = _run("--since", "1 hour ago")
    assert result.returncode in {0, 1}
    assert "[PASS] Platform:" in result.stdout
    assert "Kesinti kanıtı" in result.stdout
    verdict = "FAIL bulgusu yok." if result.returncode == 0 else "FAIL bulgusu var."
    assert verdict in result.stdout


def test_windows_tools_are_only_queried_never_changed() -> None:
    """The doctor is read-only: powercfg/schtasks calls may only use /query."""
    source = SCRIPT.read_text(encoding="utf-8")
    invocations = re.findall(r'"\$(powercfg|schtasks)"\s+(/\w+)', source)
    assert invocations, "expected powercfg/schtasks invocations"
    assert {flag for _, flag in invocations} == {"/query"}
    for mutating in ("systemctl enable", "systemctl start", "powercfg /change", "schtasks /create"):
        for line in source.splitlines():
            if mutating in line:
                assert re.search(r"\b(fail|warn)\b", line), line


def test_runbook_documents_the_doctor_and_remediation_steps() -> None:
    """The runbook must point operators at the doctor and every remediation it checks."""
    runbook = RUNBOOK.read_text(encoding="utf-8")
    section = runbook.split("## Host'u 7/24 açık tutma", 1)[1]
    assert "./scripts/check_runner_host_continuity.sh" in section
    for step in (
        "sudo ./svc.sh install",
        "systemd=true",
        "powercfg /change standby-timeout-ac 0",
        "powercfg /change hibernate-timeout-ac 0",
        "--exec sleep infinity",
    ):
        assert step in section, step
