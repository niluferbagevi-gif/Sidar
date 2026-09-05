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
  if [[ "${2:-}" == *"sys.version_info.micro"* ]]; then
    echo "3.11.15"
  else
    echo "3.11"
  fi
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
        [[ "$output" == *"WARN:PYTHON_VERSION=3.12 algılandı; runtime için 3.11.15 zorunlu."* ]]

        venv_calls_before="$(grep -c "^venv " "$UV_STUB_LOG")"
        [[ "$venv_calls_before" == "2" ]]
        output="$(create_uv_venv 2>&1)"
        venv_calls_after="$(grep -c "^venv " "$UV_STUB_LOG")"
        [[ "$output" == *"OK:.venv mevcut sürümle uyumlu: 3.11.15"* ]]
        [[ "$venv_calls_before" == "$venv_calls_after" ]]
        """
    )

    subprocess.run(
        ["bash", "-lc", smoke_script, "sidar-smoke", str(script_dir), str(fake_bin)],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(tmp_path / "uv.log")),
        check=True,
    )


def test_create_uv_venv_preserves_full_patch_version_from_pyvenv_fallback(tmp_path):
    script_dir = tmp_path / "sidar"
    venv_dir = script_dir / ".venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (venv_dir / "bin" / "python").chmod(0o755)
    (venv_dir / "bin" / "activate").write_text("true\n", encoding="utf-8")
    (venv_dir / "pyvenv.cfg").write_text("version = 3.11.15\n", encoding="utf-8")

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    uv_stub = fake_bin / "uv"
    uv_stub.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "${UV_STUB_LOG:?}"\n'
        '[[ "$*" == "python install 3.11.15" ]]\n',
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)

    script = textwrap.dedent(
        r"""
        set -euo pipefail
        source scripts/install_modules/utils/python_env.sh
        step(){ :; }; info(){ :; }; warn(){ :; }; fail(){ exit 1; }
        ok(){ echo "OK:$*"; }
        export SCRIPT_DIR="$1" PATH="$2:$PATH"
        unset PYTHON_VERSION
        create_uv_venv
        """
    )
    result = subprocess.run(
        ["bash", "-lc", script, "sidar-smoke", str(script_dir), str(fake_bin)],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(tmp_path / "uv.log")),
        check=True,
        capture_output=True,
        text=True,
    )

    assert "OK:.venv mevcut sürümle uyumlu: 3.11.15" in result.stdout
    assert "venv --python" not in (tmp_path / "uv.log").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("profile_exports", "expected_sync_call"),
    [
        ("", "sync --frozen --all-extras"),
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
            'export DEPENDENCY_PROFILE="custom"\nexport SIDAR_DEPENDENCY_EXTRAS="dev openai '
            'postgres"',
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
              "sync --frozen --all-extras") exit 0 ;;
              "sync --frozen --extra dev-light") exit 0 ;;
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

        unset DEPENDENCY_PROFILE SIDAR_DEPENDENCY_PROFILE SIDAR_DEPENDENCY_EXTRAS \
          RUN_CI_FULL_VALIDATION
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


def test_install_python_deps_retries_uv_sync_on_transient_failure_then_succeeds(tmp_path):
    """Review bulgusu: `uv sync` tek denemeydi, retry/backoff'u yoktu.

    install_python_deps()'in artık geçici bir `uv sync` başarısızlığında tüm
    fazı baştan resume etmeden önce birkaç kez daha denediğini doğrular.
    """
    script_dir = tmp_path / "sidar"
    script_dir.mkdir(parents=True)
    (script_dir / "uv.lock").touch()

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "dpkg-query").write_text(
        "#!/usr/bin/env bash\nprintf 'Status: install ok installed\\n'\n",
        encoding="utf-8",
    )
    # İlk iki `uv sync` denemesi ağ zaman aşımı gibi başarısız olur, üçüncüsü
    # başarılı olur.
    (fake_bin / "uv").write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >> "${UV_STUB_LOG:?}"
            case "$*" in
              "sync --frozen --all-extras")
                count_file="${UV_CALL_COUNT_FILE:?}"
                count=0
                [[ -f "$count_file" ]] && count="$(cat "$count_file")"
                count=$((count + 1))
                echo "$count" > "$count_file"
                if (( count < 3 )); then
                  echo "error: Failed to download distributions" >&2
                  echo "Caused by: operation timed out" >&2
                  exit 1
                fi
                exit 0
                ;;
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
        warn(){ echo "WARN:$*"; }
        fail(){ echo "FAIL:$*"; exit 1; }
        ensure_env_file_secrets_after_uv_sync(){ :; }
        validate_runtime_env_loading(){ :; }

        export SCRIPT_DIR="$1"
        export PATH="$2:$PATH"
        export UPGRADE_LOCK=false
        export PYTHON_VERSION="3.11"
        export DEPENDENCY_PROFILE="dev-full"
        export SIDAR_INSTALL_SKIP_RETRY_SLEEP=1

        install_python_deps
        echo "SUCCESS-ON-RETRY"

        sync_calls="$(grep -c '^sync --frozen --all-extras$' "$UV_STUB_LOG")"
        [[ "$sync_calls" -eq 3 ]]
        """
    )

    result = subprocess.run(
        ["bash", "-lc", smoke_script, "sidar-uv-sync-retry", str(script_dir), str(fake_bin)],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(
            UV_STUB_LOG=str(tmp_path / "retry-uv.log"),
            UV_CALL_COUNT_FILE=str(tmp_path / "retry-count"),
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    assert "SUCCESS-ON-RETRY" in result.stdout
    assert "deneme 1/3" in result.stdout
    assert "deneme 2/3" in result.stdout


def test_install_python_deps_exhausts_uv_sync_retries_and_fails(tmp_path):
    """A persistently failing `uv sync` still fails closed after all retries."""
    script_dir = tmp_path / "sidar"
    script_dir.mkdir(parents=True)
    (script_dir / "uv.lock").touch()

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "dpkg-query").write_text(
        "#!/usr/bin/env bash\nprintf 'Status: install ok installed\\n'\n",
        encoding="utf-8",
    )
    (fake_bin / "uv").write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >> "${UV_STUB_LOG:?}"
            case "$*" in
              "sync --frozen --all-extras")
                echo "Caused by: operation timed out" >&2
                exit 1
                ;;
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
        warn(){ echo "WARN:$*"; }
        fail(){ echo "FAIL:$*"; exit 1; }
        ensure_env_file_secrets_after_uv_sync(){ :; }
        validate_runtime_env_loading(){ :; }

        export SCRIPT_DIR="$1"
        export PATH="$2:$PATH"
        export UPGRADE_LOCK=false
        export PYTHON_VERSION="3.11"
        export DEPENDENCY_PROFILE="dev-full"
        export SIDAR_INSTALL_SKIP_RETRY_SLEEP=1

        install_python_deps
        """
    )

    result = subprocess.run(
        ["bash", "-lc", smoke_script, "sidar-uv-sync-exhausted", str(script_dir), str(fake_bin)],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(tmp_path / "exhausted-uv.log")),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert (
        "FAIL:Bağımlılık kurulumu başarısız oldu (uv sync --frozen --all-extras, 3 denemeden sonra)"
        in result.stdout
    )
    sync_calls = (
        (tmp_path / "exhausted-uv.log")
        .read_text(encoding="utf-8")
        .count("sync --frozen --all-extras")
    )
    assert sync_calls == 3


def test_install_python_deps_sets_uv_http_timeout_with_override(tmp_path):
    """Review bulgusu: uv'nin varsayılan HTTP timeout'u (30sn) hiç ayarlanmıyordu.

    install_python_deps()'in artık UV_HTTP_TIMEOUT'u varsayılan bir değere
    ayarladığını ve SIDAR_UV_HTTP_TIMEOUT ile override edilebildiğini
    doğrular.
    """
    script_dir = tmp_path / "sidar"
    script_dir.mkdir(parents=True)
    (script_dir / "uv.lock").touch()

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "dpkg-query").write_text(
        "#!/usr/bin/env bash\nprintf 'Status: install ok installed\\n'\n",
        encoding="utf-8",
    )
    (fake_bin / "uv").write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf 'CALL=%s UV_HTTP_TIMEOUT=%s\n' "$*" "${UV_HTTP_TIMEOUT:-<unset>}" \
                >> "${UV_STUB_LOG:?}"
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
        export DEPENDENCY_PROFILE="dev-full"

        install_python_deps
        """
    )

    default_log = tmp_path / "default-timeout-uv.log"
    subprocess.run(
        [
            "bash",
            "-lc",
            smoke_script,
            "sidar-uv-http-timeout-default",
            str(script_dir),
            str(fake_bin),
        ],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(default_log)),
        check=True,
    )
    assert "UV_HTTP_TIMEOUT=120" in default_log.read_text(encoding="utf-8")

    override_log = tmp_path / "override-timeout-uv.log"
    subprocess.run(
        [
            "bash",
            "-lc",
            smoke_script,
            "sidar-uv-http-timeout-override",
            str(script_dir),
            str(fake_bin),
        ],
        cwd=os.getcwd(),
        env=_clean_subprocess_env(UV_STUB_LOG=str(override_log), SIDAR_UV_HTTP_TIMEOUT="300"),
        check=True,
    )
    assert "UV_HTTP_TIMEOUT=300" in override_log.read_text(encoding="utf-8")


def test_pytorch_cuda_sync_uses_gpu_profile_without_all_extras(tmp_path):
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "uv").write_text(
        textwrap.dedent(
            r"""#!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >> "${UV_STUB_LOG:?}"
            case "$*" in
              "sync --frozen --extra dev-gpu --index https://download.pytorch.org/whl/cu124 \
--reinstall-package torch --reinstall-package torchvision") exit 0 ;;
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

        grep -q "^sync --frozen --extra dev-gpu --index https://download.pytorch.org/whl/cu124 \
--reinstall-package torch --reinstall-package torchvision$" "$UV_STUB_LOG"
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
