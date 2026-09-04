from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_remote_script_interactive_pin_remains_available_in_auto_install(
    tmp_path: Path,
) -> None:
    """AUTO_INSTALL must not suppress the explicit remote-script trust gate."""
    if shutil.which("script") is None:
        pytest.skip("util-linux script komutu bu ortamda yok")

    downloaded = tmp_path / "install.sh"
    downloaded.write_text("#!/bin/sh\necho safe fixture\n", encoding="utf-8")
    probe = tmp_path / "probe.sh"
    probe.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        "warn() { printf 'WARN:%s\\n' \"$*\"; }\n"
        "info() { printf 'INFO:%s\\n' \"$*\"; }\n"
        "source scripts/install_modules/utils/remote_script.sh\n"
        # install_sidar.sh masks and logs output through a process-substitution
        # pipe, so stdout is deliberately not a TTY at the trust gate.
        "exec > >(cat) 2>&1\n"
        "log_pipe_pid=$!\n"
        "AUTO_INSTALL=true NO_INTERACTION=false PAGER=cat "
        'review_and_pin_remote_script_checksum "$1" '
        "https://example.invalid/install.sh fixture abc123 FIXTURE_SHA256\n"
        "printf 'PIN=%s\\n' \"$FIXTURE_SHA256\"\n"
        # Bash does not automatically wait for process substitutions. Close the
        # writer and join `cat`, otherwise the final PIN line can be lost when
        # util-linux `script` observes the probe shell exiting first.
        "exec 1>&- 2>&-\n"
        'wait "$log_pipe_pid"\n',
        encoding="utf-8",
    )
    probe.chmod(0o755)

    result = subprocess.run(
        ["script", "-qec", f"{probe} {downloaded}", "/dev/null"],
        cwd=REPO_ROOT,
        input="evet\nevet\n",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "HATA: fixture checksum değeri tanımlı değil" in result.stdout
    assert "checksum değerini oluşturmak" in result.stdout
    assert "PIN=abc123" in result.stdout


def test_remote_script_interactive_pin_fails_closed_without_controlling_tty(
    tmp_path: Path,
) -> None:
    """A /dev/tty node alone must not make headless execution interactive."""
    downloaded = tmp_path / "install.sh"
    downloaded.write_text("#!/bin/sh\necho safe fixture\n", encoding="utf-8")
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            warn() { :; }
            info() { :; }
            source scripts/install_modules/utils/remote_script.sh
            if NO_INTERACTION=false PAGER=cat review_and_pin_remote_script_checksum \
                "$1" https://example.invalid/install.sh fixture abc123 FIXTURE_SHA256; then
                echo unexpected-success
            else
                echo fail-closed
            fi
            """,
            "bash",
            str(downloaded),
        ],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        # Redirecting stdin does not detach a child from the parent's
        # controlling terminal. Start a new session so opening /dev/tty really
        # exercises the headless/CI path instead of consuming the test runner's
        # terminal input.
        start_new_session=True,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "fail-closed"


@pytest.mark.parametrize(
    ("phase", "failed_cmd", "reason", "expected_reason", "expected_rc"),
    [
        (
            "03_runtime",
            "sh /tmp/ollama_install_script",
            "OLLAMA_INSTALL_SHA256 checksum değeri tanımlı değil; supply-chain doğrulamasını "
            "korumak için duruldu.",
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
            "06_models",
            "run_coding_model_smoke_prompt",
            "Coding model JSON smoke testi başarısız: Ollama generate çağrısı yanıt vermedi "
            "(qwen2.5-coder:7b, HTTP 500). Ollama hata metni: cuda error: out of memory",
            "coding-model-oom-failure",
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


@pytest.mark.parametrize(
    ("package_version", "expected_rc"),
    [
        ("20.20.2-1nodesource1", 0),
        ("22.14.0-1NODESOURCE1", 0),
        ("20.19.4+dfsg-1ubuntu1", 1),
    ],
)
def test_nodesource_detection_uses_installed_dpkg_version(
    tmp_path: Path,
    package_version: str,
    expected_rc: int,
) -> None:
    """NodeSource detection must not depend on the mutable apt policy cache."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    dpkg_query = fake_bin / "dpkg-query"
    dpkg_query.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$*" == *nodejs* ]] || exit 2\n'
        f"printf '%s' {package_version!r}\n",
        encoding="utf-8",
    )
    dpkg_query.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/install_modules/install_helpers.sh; nodejs_package_is_from_nodesource",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_rc, result.stdout + result.stderr


def test_nodejs_package_source_checks_do_not_use_apt_policy_cache() -> None:
    system_phase = (REPO_ROOT / "scripts/install_modules/phases/03_system.sh").read_text(
        encoding="utf-8"
    )
    react_phase = (REPO_ROOT / "scripts/install_modules/phases/14_react.sh").read_text(
        encoding="utf-8"
    )

    assert "apt-cache policy nodejs" not in system_phase
    assert "apt-cache policy nodejs" not in react_phase
    assert "nodejs_package_is_from_nodesource" in system_phase
    assert "nodejs_package_is_from_nodesource" in react_phase


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


def test_coding_model_oom_failure_gets_concrete_guidance_on_first_occurrence() -> None:
    """Review bulgusu (e): auto-heal 06_models fazına özel bir strateji tanımıyordu.

    Before this fix, a coding-model smoke-test/OOM failure fell through every
    specific classifier, took a blind "transient-phase-retry", and only on the
    *second* (identical) failure did the generic repeated-failure-signature
    fail-fast kick in - with no guidance beyond "aynı failure imzası
    tekrarlandı". This asserts sidar_handle_install_failure now recognizes the
    signature and gives concrete .env guidance on the FIRST occurrence
    (attempt=0), without ever attempting a phase retry.
    """
    script = r"""
        set -Eeuo pipefail
        source scripts/install_modules/utils/install_remediation.sh
        info() { :; }
        warn() { printf 'WARN:%s\n' "$*"; }
        sidar_write_remediation_report() { printf 'REPORT:%s|%s|%s\n' "$1" "$2" "$3"; }
        sidar_resume_after_remediation() { echo "UNEXPECTED-RESUME-CALLED"; exit 1; }

        export SIDAR_CURRENT_INSTALL_PHASE="06_models"
        export SIDAR_INSTALL_REMEDIATION_ATTEMPT=0
        unset SIDAR_INSTALL_LAST_FAILURE_PHASE SIDAR_INSTALL_LAST_FAILURE_SIGNATURE || true

        reason="Coding model JSON smoke testi başarısız: Ollama generate çağrısı yanıt vermedi"
        reason="${reason} (qwen2.5-coder:7b, HTTP 500)."
        reason="${reason} Ollama hata metni: cuda error: out of memory"
        reason="${reason} [GPU belleği yetersiz olabilir (OOM). OLLAMA_NUM_BATCH veya"
        reason="${reason} OLLAMA_CODING_NUM_CTX değerini düşürmeyi ya da eşzamanlı istek sayısını"
        reason="${reason} (OLLAMA_GPU_REQUEST_POOL_SIZE) azaltmayı deneyin.] .env dosyasında"
        reason="${reason} OLLAMA_CODING_NUM_CTX=2048 ayarlayıp kurulumu yeniden deneyin."

        rc=0
        sidar_handle_install_failure 1 148 "run_coding_model_smoke_prompt" "$reason" || rc="$?"
        printf 'RC:%s\n' "$rc"
    """

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        env={"SIDAR_INSTALL_TEST_MODE": "1", "SIDAR_INSTALL_AUTO_HEAL": "1", **os.environ},
        capture_output=True,
        text=True,
        check=True,
    )

    assert "UNEXPECTED-RESUME-CALLED" not in result.stdout
    assert "RC:1" in result.stdout
    assert (
        "REPORT:06_models|coding-model-oom-failure|fail-fast;no-retry;manual-fix-required"
        in result.stdout
    )
    assert "OLLAMA_CODING_NUM_CTX=2048" in result.stdout
    assert "OLLAMA_NUM_BATCH" in result.stdout
    assert "curl -s http://localhost:11434/api/generate" in result.stdout
    assert "ollama ps" in result.stdout
    # This must fire on the FIRST occurrence, not only after a repeated signature.
    assert "aynı failure imzası tekrarlandı" not in result.stdout


def test_resume_after_remediation_carries_dependency_profile_across_reexec(
    tmp_path: Path,
) -> None:
    """Review bulgusu: sidar_resume_after_remediation() seçilen bağımlılık profilini taşımıyordu.

    Fonksiyon, resume re-exec'inde DEPENDENCY_PROFILE / SIDAR_DEPENDENCY_EXTRAS'ı
    taşımıyordu. Bu, resume sonrası select_dependency_profile()'ın "ask"a
    düşmesine (etkileşimsiz ortamlarda sessizce dev-full'a) yol açıyordu.
    Bu test, gerçek `exec env ... "$resume_script"` zincirini çalıştırıp
    sahte bir resume betiğinin bu iki değişkeni gördüğünü doğrular.
    """
    fake_installer = tmp_path / "install_sidar.sh"
    fake_installer.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'RESUMED_DEPENDENCY_PROFILE=%s\\n' \"${DEPENDENCY_PROFILE-<unset>}\"\n"
        "printf 'RESUMED_SIDAR_DEPENDENCY_EXTRAS=%s\\n' \"${SIDAR_DEPENDENCY_EXTRAS-<unset>}\"\n"
        "printf 'RESUMED_PHASE=%s\\n' \"${SIDAR_INSTALL_RESUME_FROM_PHASE-<unset>}\"\n"
    )
    fake_installer.chmod(0o755)

    script = r"""
        set -Eeuo pipefail
        source ./scripts/install_modules/utils/install_remediation.sh
        info() { :; }
        warn() { :; }
        fail() { printf 'UNEXPECTED-FAIL:%s\n' "$*"; exit 1; }

        SIDAR_INSTALL_ORIGINAL_ARGS=()
        export SCRIPT_DIR="$1"
        export DEPENDENCY_PROFILE="dev-gpu"
        export SIDAR_DEPENDENCY_EXTRAS="openai anthropic"

        sidar_resume_after_remediation 04_workspace 1
    """

    result = subprocess.run(
        ["bash", "-c", script, "_", str(tmp_path)],
        cwd=REPO_ROOT,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        capture_output=True,
        text=True,
        check=True,
    )

    assert "UNEXPECTED-FAIL" not in result.stdout
    assert "RESUMED_DEPENDENCY_PROFILE=dev-gpu" in result.stdout
    assert "RESUMED_SIDAR_DEPENDENCY_EXTRAS=openai anthropic" in result.stdout
    assert "RESUMED_PHASE=04_workspace" in result.stdout
