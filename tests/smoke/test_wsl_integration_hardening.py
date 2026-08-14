import json
import os
import subprocess
import textwrap

import pytest

pytestmark = pytest.mark.installer_smoke


@pytest.mark.parametrize(
    ("settings", "expected_default", "expected_distros"),
    [
        (
            {
                "EnableIntegrationWithDefaultWslDistro": True,
                "IntegratedWslDistros": ["Ubuntu", "Ubuntu-24.04"],
            },
            "true",
            "Ubuntu,Ubuntu-24.04",
        ),
        (
            {
                "enableIntegrationWithDefaultWslDistro": False,
                "integratedWslDistros": ["Ubuntu-26.04"],
            },
            "false",
            "Ubuntu-26.04",
        ),
        (
            {"wslEngineEnabled": True, "wsl": {"distros": {"Ubuntu": True}}},
            "true",
            "Ubuntu",
        ),
        (
            {
                "integration": {
                    "wslEngineEnabled": True,
                    "wslDistros": {"Ubuntu-Preview": True},
                }
            },
            "true",
            "Ubuntu-Preview",
        ),
    ],
)
def test_wsl_integration_settings_schema_variants_are_normalized(
    settings, expected_default, expected_distros
):
    """Docker Desktop'ın eski ve yeni settings şemalarını aynı sözleşmeye indirger."""
    script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/utils/wsl_gpu_preflight.sh
        sidar_read_docker_settings_json(){ printf '%s' "$DOCKER_SETTINGS_JSON"; }
        sidar_resolve_wsl_integration_fields
        """
    )
    env = os.environ.copy()
    env["DOCKER_SETTINGS_JSON"] = json.dumps(settings)

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=os.getcwd(),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    resolved = dict(line.split("=", 1) for line in result.stdout.splitlines())

    assert resolved["enable_default"].lower() == expected_default
    assert resolved["integrated_csv"] == expected_distros


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
    ps_mock.write_text(
        textwrap.dedent(
            """#!/usr/bin/env bash
set -euo pipefail
cmd="${*: -1}"
if [[ "$cmd" == *"EnableIntegrationWithDefaultWslDistro"* ]]; then
  printf 'True\\r\\n'
elif [[ "$cmd" == *"IntegratedWslDistros"* ]]; then
  printf 'Ubuntu\\r\\n'
else
  printf '\\r\\n'
fi
"""
        ),
        encoding="utf-8",
    )
    ps_mock.chmod(0o755)

    script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/utils/wsl_gpu_preflight.sh

        step(){ :; }
        info(){ :; }
        warn(){ :; }
        ok(){ :; }

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

    subprocess.run(["bash", "-c", script], cwd=os.getcwd(), env=env, check=True)


def test_preflight_keeps_autofix_disabled_when_default_covers_and_hardening_disabled(tmp_path):
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
    ps_mock.write_text(
        textwrap.dedent(
            """#!/usr/bin/env bash
set -euo pipefail
cmd="${*: -1}"
if [[ "$cmd" == *"EnableIntegrationWithDefaultWslDistro"* ]]; then
  printf 'True\\r\\n'
elif [[ "$cmd" == *"IntegratedWslDistros"* ]]; then
  printf 'Ubuntu\\r\\n'
else
  printf '\\r\\n'
fi
"""
        ),
        encoding="utf-8",
    )
    ps_mock.chmod(0o755)

    script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/utils/wsl_gpu_preflight.sh

        step(){ :; }
        info(){ :; }
        warn(){ :; }
        ok(){ :; }

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
        export WSL_INTEGRATION_HARDEN_EXPLICIT=false

        docker_desktop_wsl_integration_preflight
        test "${WSL_INTEGRATION_AUTOFIX_ELIGIBLE:-false}" = "false"
        """
    )

    env = os.environ.copy()
    env["PATH"] = f"{mock_bin}:{env['PATH']}"

    subprocess.run(["bash", "-c", script], cwd=os.getcwd(), env=env, check=True)
