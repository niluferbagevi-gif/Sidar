import os
import subprocess
import textwrap


def test_preflight_sets_autofix_eligible_when_default_covers_and_hardening_enabled(tmp_path):
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()

    wsl_mock = mock_bin / "wsl.exe"
    wsl_mock.write_text(
        textwrap.dedent(
            """#!/usr/bin/env python3
import sys
sys.stdout.buffer.write('Ubuntu\\r\\n'.encode('utf-16le'))
"""
        ),
        encoding="utf-8",
    )
    wsl_mock.chmod(0o755)

    ps_mock = mock_bin / "powershell.exe"
    ps_mock.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    ps_mock.chmod(0o755)

    script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/utils/wsl_gpu_preflight.sh

        step(){ :; }
        info(){ :; }
        warn(){ :; }
        ok(){ :; }
        read(){ :; }

        sidar_read_docker_settings_json(){
            cat <<'JSON'
{"EnableIntegrationWithDefaultWslDistro": true, "integratedWslDistros": []}
JSON
        }

        apply_wsl_integration_autofix(){
            return 1
        }

        export WSL2=true
        export WSL_DISTRO_NAME="Ubuntu"
        export WSL_INTEGRATION_HARDEN_EXPLICIT=true

        docker_desktop_wsl_integration_preflight
        test "${WSL_INTEGRATION_AUTOFIX_ELIGIBLE:-false}" = "true"
        """
    )

    env = os.environ.copy()
    env["PATH"] = f"{mock_bin}:{env['PATH']}"

    subprocess.run(["bash", "-lc", script], cwd=os.getcwd(), env=env, check=True)
