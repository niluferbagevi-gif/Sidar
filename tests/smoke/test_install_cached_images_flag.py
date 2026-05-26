import os
import re
import subprocess
from pathlib import Path


def _extract_function(script_text: str, function_name: str) -> str:
    pattern = rf"^({function_name}\(\) \{{[\s\S]*?^\}})\s*$"
    match = re.search(pattern, script_text, flags=re.MULTILINE)
    assert match, f"function not found: {function_name}"
    return match.group(1)


def test_last_flag_skips_compose_pull(tmp_path: Path) -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")
    fn = _extract_function(install_script, "ensure_fresh_images_or_skip")

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True)
    compose_stub = fake_bin / "docker-compose-stub"
    log_file = tmp_path / "compose_calls.log"
    compose_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"$*\" >> {log_file}\n",
        encoding="utf-8",
    )
    compose_stub.chmod(0o755)

    bash_test = f"""
set -euo pipefail
{fn}
info() {{ :; }}
warn() {{ :; }}

USE_LAST_IMAGES=true
{compose_stub} pull --quiet >/dev/null 2>&1 || true
rm -f {log_file}
ensure_fresh_images_or_skip {compose_stub}
[[ ! -f {log_file} ]]

USE_LAST_IMAGES=false
ensure_fresh_images_or_skip {compose_stub}
[[ -f {log_file} ]]
grep -q '^pull --ignore-buildable --quiet$' {log_file}
"""

    subprocess.run(["bash", "-lc", bash_test], check=True, cwd=os.getcwd())
