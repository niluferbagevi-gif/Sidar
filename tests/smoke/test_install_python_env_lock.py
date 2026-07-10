import os
import subprocess
import textwrap

import pytest

pytestmark = pytest.mark.installer_smoke

_ENV_VARS_THAT_CAN_CHANGE_INSTALLER_PROFILE = (
    "DEPENDENCY_PROFILE",
    "SIDAR_DEPENDENCY_PROFILE",
    "SIDAR_DEPENDENCY_EXTRAS",
    "RUN_CI_FULL_VALIDATION",
)


def _clean_subprocess_env(**overrides: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _ENV_VARS_THAT_CAN_CHANGE_INSTALLER_PROFILE
    }
    env.update(overrides)
    return env


def test_create_uv_venv_pins_python_311_and_warns_on_override(tmp_path):
    script_dir = tmp_path / "sidar"
    script_dir.mkdir(parents=True)

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    uv_stub = fake_bin / "uv"
    uv_stub.write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf "%s\n" "$*" >> "${UV_STUB_LOG:?}"
            if [[ "$1" == "python" && "$2" == "install" ]]; then
              exit 0
            fi
            if [[ "$1" == "python" && "$2" == "find" ]]; then
              echo "/usr/bin/python3.11"
              exit 0
            fi
            if [[ "$1" == "venv" ]]; then
              venv_dir="${@: -1}"
              mkdir -p "$venv_dir/bin"
              cat > "$venv_dir/bin/python" <<'EOS'
#!/usr/bin/env bash
if [[ "${1:-}" == "-c" ]]; then
  echo "3.11"
else
  echo "Python 3.11.9"
fi
EOS
              chmod +x "$venv_dir/bin/python"
              cat > "$venv_dir/bin/activate" <<'EOS'
#!/usr/bin/env bash
VIRTUAL_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VIRTUAL_ENV
export PATH="$VIRTUAL_ENV/bin:$PATH"
EOS
              chmod +x "$venv_dir/bin/activate"
              exit 0
            fi
            echo "unexpected uv call: $*" >&2
            exit 99
            """
        ),
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)

    smoke_script = textwrap.dedent(
        r"""
        set -euo pipefail
        source scripts/install_modules/utils/python_env.sh

        step(){ :; }
        info(){ :; }
        ok(){ echo "OK:$*"; }
        fail(){ echo "FAIL:$*"; exit 1; }
        warn(){ echo "WARN:$*"; }

        export SCRIPT_DIR="$1"
        export PATH="$2:$PATH"

        unset PYTHON_VERSION
        create_uv_venv
        default_version="$($SCRIPT_DIR/.venv/bin/python --version)"
        [[ "$default_version" == Python\ 3.11.* ]]

        rm -rf "$SCRIPT_DIR/.venv"
        export PYTHON_VERSION="3.12"
        output="$(create_uv_venv 2>&1)"
        overridden_version="$($SCRIPT_DIR/.venv/bin/python --version)"
        [[ "$overridden_version" == Python\ 3.11.* ]]
        [[ "$output" == *"WARN:PYTHON_VERSION=3.12 algılandı; runtime için 3.11 zorunlu."* ]]

        venv_calls_before="$(grep -c "^venv " "$UV_STUB_LOG")"
        [[ "$venv_calls_before" == "2" ]]
        output="$(create_uv_venv 2>&1)"
        venv_calls_after="$(grep -c "^venv " "$UV_STUB_LOG")"
        [[ "$output" == *"OK:.venv mevcut sürümle uyumlu: 3.11"* ]]
        [[ "$venv_calls_before" == "$venv_calls_after" ]]
        """
    )

    subprocess.run(
        ["bash", "-lc", smoke_script, "sidar-smoke", str(script_dir), str(fake_bin)],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(tmp_path / "uv.log")),
        check=True,
    )


@pytest.mark.parametrize(
    ("profile_exports", "expected_sync_call"),
    [
        ("", "sync --frozen --extra dev-light"),
        ('export DEPENDENCY_PROFILE="dev-light"', "sync --frozen --extra dev-light"),
        ('export DEPENDENCY_PROFILE="dev-full"', "sync --frozen --all-extras"),
        ('export DEPENDENCY_PROFILE="dev-gpu"', "sync --frozen --extra dev-gpu"),
        (
            'export DEPENDENCY_PROFILE="gpu-runtime"',
            "sync --frozen --extra gpu-runtime --no-dev",
        ),
        (
            'export DEPENDENCY_PROFILE="production"',
            "sync --frozen --extra production --no-dev",
        ),
        (
            'export DEPENDENCY_PROFILE="production-minimal"',
            "sync --frozen --extra production-minimal --no-dev",
        ),
        (
            'export DEPENDENCY_PROFILE="custom"\nexport SIDAR_DEPENDENCY_EXTRAS="dev openai postgres"',
            "sync --frozen --extra dev --extra openai --extra postgres",
        ),
    ],
    ids=[
        "default",
        "dev-light",
        "dev-full",
        "dev-gpu",
        "gpu-runtime",
        "production",
        "production-minimal",
        "custom",
    ],
)
def test_install_python_deps_profile_matrix_uses_expected_uv_sync(
    tmp_path, profile_exports, expected_sync_call
):
    script_dir = tmp_path / "sidar"
    script_dir.mkdir(parents=True)
    (script_dir / "uv.lock").touch()

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "dpkg-query").write_text(
        textwrap.dedent(
            """#!/usr/bin/env bash
            printf "Status: install ok installed\n"
            """
        ),
        encoding="utf-8",
    )
    (fake_bin / "uv").write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >> "${UV_STUB_LOG:?}"
            case "$*" in
              "sync --frozen --extra dev-light") exit 0 ;;
              "sync --frozen --all-extras") exit 0 ;;
              "sync --frozen --extra dev-gpu") exit 0 ;;
              "sync --frozen --extra gpu-runtime --no-dev") exit 0 ;;
              "sync --frozen --extra production --no-dev") exit 0 ;;
              "sync --frozen --extra production-minimal --no-dev") exit 0 ;;
              "sync --frozen --extra dev --extra openai --extra postgres") exit 0 ;;
              "run python -c import pydantic, pydantic_settings") exit 0 ;;
            esac
            printf 'unexpected uv call: %s\n' "$*" >&2
            exit 99
            """
        ),
        encoding="utf-8",
    )
    (fake_bin / "dpkg-query").chmod(0o755)
    (fake_bin / "uv").chmod(0o755)

    smoke_script = textwrap.dedent(
        r"""
        set -euo pipefail
        source scripts/install_modules/install_helpers.sh
        source scripts/install_modules/utils/python_env.sh

        step(){ :; }
        info(){ :; }
        ok(){ :; }
        warn(){ :; }
        fail(){ echo "FAIL:$*"; exit 1; }
        ensure_env_file_secrets_after_uv_sync(){ :; }
        validate_runtime_env_loading(){ :; }

        export SCRIPT_DIR="$1"
        export PATH="$2:$PATH"
        export UPGRADE_LOCK=false
        export PYTHON_VERSION="3.11"
        expected_sync_call="$3"

        unset DEPENDENCY_PROFILE SIDAR_DEPENDENCY_PROFILE SIDAR_DEPENDENCY_EXTRAS RUN_CI_FULL_VALIDATION
        eval "$4"

        install_python_deps

        grep -q "^${expected_sync_call}$" "$UV_STUB_LOG"
        ! grep -q -- "uv pip" "$UV_STUB_LOG"
        """
    )

    subprocess.run(
        [
            "bash",
            "-lc",
            smoke_script,
            "sidar-install-deps-smoke",
            str(script_dir),
            str(fake_bin),
            expected_sync_call,
            profile_exports,
        ],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(tmp_path / "install-python-deps-uv.log")),
        check=True,
    )


def test_runtime_import_failure_guidance_uses_selected_profile_command(tmp_path):
    script_dir = tmp_path / "sidar"
    script_dir.mkdir(parents=True)
    (script_dir / "uv.lock").touch()

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "dpkg-query").write_text(
        '#!/usr/bin/env bash\nprintf "Status: install ok installed\n"\n',
        encoding="utf-8",
    )
    (fake_bin / "uv").write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >> "${UV_STUB_LOG:?}"
            case "$*" in
              "sync --frozen --extra production-minimal --no-dev") exit 0 ;;
              "run python -c import pydantic, pydantic_settings") exit 42 ;;
            esac
            printf 'unexpected uv call: %s\n' "$*" >&2
            exit 99
            """
        ),
        encoding="utf-8",
    )
    (fake_bin / "dpkg-query").chmod(0o755)
    (fake_bin / "uv").chmod(0o755)

    smoke_script = textwrap.dedent(
        r"""
        set -euo pipefail
        source scripts/install_modules/install_helpers.sh
        source scripts/install_modules/utils/python_env.sh

        step(){ :; }
        info(){ :; }
        ok(){ :; }
        warn(){ :; }
        fail(){ echo "FAIL:$*"; exit 1; }
        ensure_env_file_secrets_after_uv_sync(){ :; }
        validate_runtime_env_loading(){ :; }

        export SCRIPT_DIR="$1"
        export PATH="$2:$PATH"
        export UPGRADE_LOCK=false
        export PYTHON_VERSION="3.11"
        export DEPENDENCY_PROFILE="production-minimal"

        install_python_deps
        """
    )

    result = subprocess.run(
        [
            "bash",
            "-lc",
            smoke_script,
            "sidar-runtime-import-guidance",
            str(script_dir),
            str(fake_bin),
        ],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(tmp_path / "runtime-import-guidance-uv.log")),
        text=True,
        capture_output=True,
        check=False,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "uv sync --frozen --extra production-minimal --no-dev" in combined_output
    assert "uv sync --frozen --all-extras" not in combined_output


def test_pytorch_cuda_sync_uses_gpu_profile_without_all_extras(tmp_path):
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "uv").write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >> "${UV_STUB_LOG:?}"
            case "$*" in
              "sync --frozen --extra dev-gpu --index https://download.pytorch.org/whl/cu124 --reinstall-package torch --reinstall-package torchvision") exit 0 ;;
            esac
            printf 'unexpected uv call: %s\n' "$*" >&2
            exit 99
            """
        ),
        encoding="utf-8",
    )
    (fake_bin / "uv").chmod(0o755)

    smoke_script = textwrap.dedent(
        r"""
        set -euo pipefail
        source scripts/install_modules/utils/python_env.sh

        info(){ :; }
        fail(){ echo "FAIL:$*"; exit 1; }

        export PATH="$1:$PATH"
        export DEPENDENCY_PROFILE="dev-light"
        sync_pytorch_cuda_wheels cu124

        grep -q "^sync --frozen --extra dev-gpu --index https://download.pytorch.org/whl/cu124 --reinstall-package torch --reinstall-package torchvision$" "$UV_STUB_LOG"
        ! grep -q -- "--all-extras" "$UV_STUB_LOG"
        ! grep -q -- "torchaudio" "$UV_STUB_LOG"
        """
    )

    subprocess.run(
        ["bash", "-lc", smoke_script, "sidar-cuda-sync", str(fake_bin)],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(tmp_path / "cuda-sync-uv.log")),
        check=True,
    )


def test_install_python_deps_dev_full_uses_all_extras_without_conflicting_extra(tmp_path):
    script_dir = tmp_path / "sidar"
    script_dir.mkdir(parents=True)
    (script_dir / "uv.lock").touch()

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "dpkg-query").write_text(
        textwrap.dedent(
            """#!/usr/bin/env bash
            printf "Status: install ok installed\n"
            """
        ),
        encoding="utf-8",
    )
    (fake_bin / "uv").write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >> "${UV_STUB_LOG:?}"
            case "$*" in
              "sync --frozen --all-extras") exit 0 ;;
              "run python -c import pydantic, pydantic_settings") exit 0 ;;
            esac
            printf 'unexpected uv call: %s\n' "$*" >&2
            exit 99
            """
        ),
        encoding="utf-8",
    )
    (fake_bin / "dpkg-query").chmod(0o755)
    (fake_bin / "uv").chmod(0o755)

    smoke_script = textwrap.dedent(
        r"""
        set -euo pipefail
        source scripts/install_modules/install_helpers.sh
        source scripts/install_modules/utils/python_env.sh

        step(){ :; }
        info(){ :; }
        ok(){ :; }
        warn(){ :; }
        fail(){ echo "FAIL:$*"; exit 1; }
        ensure_env_file_secrets_after_uv_sync(){ :; }
        validate_runtime_env_loading(){ :; }

        export SCRIPT_DIR="$1"
        export PATH="$2:$PATH"
        export UPGRADE_LOCK=false
        export PYTHON_VERSION="3.11"
        unset SIDAR_DEPENDENCY_PROFILE SIDAR_DEPENDENCY_EXTRAS
        export DEPENDENCY_PROFILE="dev-full"

        install_python_deps

        grep -q "^sync --frozen --all-extras$" "$UV_STUB_LOG"
        ! grep -q -- "--extra dev" "$UV_STUB_LOG"
        ! grep -q -- "uv pip" "$UV_STUB_LOG"
        """
    )

    subprocess.run(
        [
            "bash",
            "-lc",
            smoke_script,
            "sidar-install-deps-smoke",
            str(script_dir),
            str(fake_bin),
        ],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(tmp_path / "install-python-deps-uv.log")),
        check=True,
    )
