import os
import re
import subprocess
from pathlib import Path


def _extract_function(script_text: str, function_name: str) -> str:
    pattern = rf"^({function_name}\(\) \{{[\s\S]*?^\}})\s*$"
    match = re.search(pattern, script_text, flags=re.MULTILINE)
    assert match, f"function not found: {function_name}"
    return match.group(1)


def _build_docker_stub(bin_dir: Path, log_file: Path) -> Path:
    stub = bin_dir / "docker"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "docker $*" >> {log_file}\n'
        'case "$1" in\n'
        '  volume) [[ "$2" == "inspect" ]] && exit 0 ;;\n'
        '  image)  [[ "$2" == "inspect" ]] && exit 0 ;;\n'
        'esac\n'
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _run(script: str, env: dict) -> None:
    subprocess.run(["bash", "-lc", script], check=True, cwd=os.getcwd(), env=env)


def test_from_zero_cleanup_skipped_when_use_last_images(tmp_path: Path) -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")
    fn = _extract_function(install_script, "from_zero_cleanup_or_skip")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    _build_docker_stub(bin_dir, log_file)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    _run(
        f"""set -euo pipefail
{fn}
info(){{ :; }}; warn(){{ :; }}; ok(){{ :; }}
USE_LAST_IMAGES=true
WIPE_MODELS=false
OFFLINE_MODE=false
FROM_ZERO_CLEANUP_DONE=false
from_zero_cleanup_or_skip docker compose
[[ ! -s {log_file} ]]
""",
        env,
    )


def test_from_zero_cleanup_wipes_postgres_redis_but_preserves_ollama_by_default(
    tmp_path: Path,
) -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")
    fn = _extract_function(install_script, "from_zero_cleanup_or_skip")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    _build_docker_stub(bin_dir, log_file)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    _run(
        f"""set -euo pipefail
{fn}
info(){{ :; }}; warn(){{ :; }}; ok(){{ :; }}
USE_LAST_IMAGES=false
WIPE_MODELS=false
OFFLINE_MODE=false
FROM_ZERO_CLEANUP_DONE=false
from_zero_cleanup_or_skip docker compose
grep -q 'down --remove-orphans' {log_file}
grep -q 'volume rm sidar_postgres_data' {log_file}
grep -q 'volume rm sidar_redis_data' {log_file}
grep -q 'image rm redis:alpine' {log_file}
grep -q 'image rm pgvector/pgvector:pg16' {log_file}
grep -q 'image rm grafana/grafana:latest' {log_file}
! grep -q 'volume rm sidar_ollama_data' {log_file}
! grep -q 'image rm ollama/ollama' {log_file}
""",
        env,
    )


def test_from_zero_cleanup_with_wipe_models_removes_ollama_too(tmp_path: Path) -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")
    fn = _extract_function(install_script, "from_zero_cleanup_or_skip")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    _build_docker_stub(bin_dir, log_file)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    _run(
        f"""set -euo pipefail
{fn}
info(){{ :; }}; warn(){{ :; }}; ok(){{ :; }}
USE_LAST_IMAGES=false
WIPE_MODELS=true
OFFLINE_MODE=false
FROM_ZERO_CLEANUP_DONE=false
from_zero_cleanup_or_skip docker compose
grep -q 'volume rm sidar_ollama_data' {log_file}
grep -q 'image rm ollama/ollama:latest' {log_file}
""",
        env,
    )


def test_from_zero_cleanup_sentinel_prevents_double_run(tmp_path: Path) -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")
    fn = _extract_function(install_script, "from_zero_cleanup_or_skip")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    _build_docker_stub(bin_dir, log_file)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    _run(
        f"""set -euo pipefail
{fn}
info(){{ :; }}; warn(){{ :; }}; ok(){{ :; }}
USE_LAST_IMAGES=false
WIPE_MODELS=false
OFFLINE_MODE=false
FROM_ZERO_CLEANUP_DONE=true
from_zero_cleanup_or_skip docker compose
[[ ! -s {log_file} ]]
""",
        env,
    )


def test_from_zero_cleanup_skipped_in_offline_mode(tmp_path: Path) -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")
    fn = _extract_function(install_script, "from_zero_cleanup_or_skip")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    _build_docker_stub(bin_dir, log_file)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    _run(
        f"""set -euo pipefail
{fn}
info(){{ :; }}; warn(){{ :; }}; ok(){{ :; }}
USE_LAST_IMAGES=false
WIPE_MODELS=false
OFFLINE_MODE=true
FROM_ZERO_CLEANUP_DONE=false
from_zero_cleanup_or_skip docker compose
[[ ! -s {log_file} ]]
""",
        env,
    )
