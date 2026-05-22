import os
import subprocess
import textwrap


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
            if [[ "$1" == "python" && "$2" == "install" ]]; then
              exit 0
            fi
            if [[ "$1" == "venv" ]]; then
              venv_dir="${@: -1}"
              mkdir -p "$venv_dir/bin"
              cat > "$venv_dir/bin/python" <<'EOS'
#!/usr/bin/env bash
echo "Python 3.11.9"
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
        ok(){ :; }
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
        """
    )

    subprocess.run(
        ["bash", "-lc", smoke_script, "sidar-smoke", str(script_dir), str(fake_bin)],
        cwd=os.getcwd(),
        check=True,
    )
