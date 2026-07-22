from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("phase", "failed_cmd", "reason", "expected_reason", "expected_rc"),
    [
        (
            "03_runtime",
            "sh /tmp/ollama_install_script",
            "OLLAMA_INSTALL_SHA256 checksum değeri tanımlı değil; supply-chain doğrulamasını korumak için duruldu.",
            "remote-script-checksum-missing",
            1,
        ),
        (
            "06_services",
            "run_pre_service_installer_smoke_gate",
            "Servis öncesi installer smoke gate başarısız: INSTALL_SIDAR_VERSION=<boş> beklenen "
            "pyproject.toml sürümüyle eşleşmiyor.",
            "installer-smoke-gate-failure",
            1,
        ),
        (
            "02_repo",
            "fail",
            "Mevcut /home/user/Sidar re-exec install_sidar.sh SHA256 farklı; hash drift kaynağını "
            "temizleyin.",
            "installer-hash-drift",
            1,
        ),
        (
            "06_services",
            "pytest tests/smoke",
            "EnvironmentFileNotFound: environment.yml stale conda installer signal",
            "learned-non-retryable-failure",
            1,
        ),
        (
            "06_services",
            "pytest tests/smoke",
            "Smoke test failed. FAILED tests/smoke/test_install.py::test_profile_matrix",
            "test-gate-failure",
            1,
        ),
        (
            "05_frontend",
            "npm install",
            "temporary network timeout",
            "transient-phase-retry",
            0,
        ),
    ],
)
def test_phase_remediation_strategy_classifies_signals_from_specific_to_generic(
    phase: str,
    failed_cmd: str,
    reason: str,
    expected_reason: str,
    expected_rc: int,
) -> None:
    script = r"""
        set +e
        source scripts/install_modules/utils/install_remediation.sh
        set +e
        info() { :; }
        warn() { :; }
        sidar_write_remediation_report() { printf 'REPORT:%s|%s|%s\n' "$1" "$2" "$3"; }
        sidar_phase_remediation_strategy "$1" "$2" "$3"
        rc="$?"
        printf 'RC:%s\n' "$rc"
    """

    result = subprocess.run(
        ["bash", "-c", script, "bash", phase, failed_cmd, reason],
        cwd=REPO_ROOT,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        capture_output=True,
        text=True,
        check=True,
    )

    assert f"REPORT:{phase}|{expected_reason}|" in result.stdout
    assert f"RC:{expected_rc}" in result.stdout
    if expected_reason == "installer-smoke-gate-failure":
        assert "test-gate-failure" not in result.stdout


def test_install_modules_declare_strict_mode_for_standalone_safety() -> None:
    missing = []
    for module in sorted((REPO_ROOT / "scripts/install_modules").rglob("*.sh")):
        first_lines = module.read_text(encoding="utf-8").splitlines()[:5]
        if "set -Eeuo pipefail" not in first_lines:
            missing.append(str(module.relative_to(REPO_ROOT)))

    assert missing == []


def test_install_remediation_uses_structured_failure_codes_and_scoped_venv_cleanup() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            source ./scripts/install_modules/utils/install_remediation.sh
            sidar_failure_code_for_signal \
                'run_pre_service_installer_smoke_gate' \
                'installer smoke gate başarısız'
            sidar_failure_code_for_signal \
                'pytest tests/smoke' \
                'FAILED tests/smoke/test_install.py::test_x'
            if sidar_is_root_owned_venv_remediation_signal \
                04_workspace 'rm -rf .venv' 'Permission denied'; then
                echo root-owned-venv
            fi
            if sidar_is_root_owned_venv_remediation_signal \
                06_services 'rm -rf /var/lib/sidar' 'Permission denied'; then
                echo unsafe-service-cleanup
            else
                echo service-cleanup-blocked
            fi
            """,
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert result.stdout.splitlines() == [
        "installer-smoke-gate-failure",
        "test-gate-failure",
        "root-owned-venv",
        "service-cleanup-blocked",
    ]
