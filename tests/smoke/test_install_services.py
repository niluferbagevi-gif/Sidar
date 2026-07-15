import shlex
from pathlib import Path

from tests.smoke.test_install_verification import _run_bash_smoke


def test_docker_compose_start_checks_daemon_access_before_up() -> None:
    services_docker = Path("scripts/install_modules/utils/services_docker.sh").read_text(
        encoding="utf-8"
    )
    start_idx = services_docker.index("start_docker_services_or_fail()")
    start_body = services_docker[
        start_idx : services_docker.index("wait_for_compose_services_health()", start_idx)
    ]

    assert "ensure_docker_compose_access_or_fail()" in services_docker
    assert "docker info" in services_docker
    assert "sudo -n docker info" in services_docker
    assert 'ensure_docker_compose_access_or_fail "${compose_cmd[@]}"' in start_body
    assert "permission denied" in services_docker
    assert "docker grubuna ekleyin" in services_docker
    assert start_body.index("ensure_docker_compose_access_or_fail") < start_body.index(
        "maybe_reset_postgres_volume_after_password_hardening"
    )
    assert start_body.index("ensure_docker_compose_access_or_fail") < start_body.index(" up -d ")


def test_compose_health_wait_timeout_honors_env(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    compose = fake_bin / "compose"
    compose.write_text(
        "#!/usr/bin/env bash\nif [[ $1 == ps && $2 == -q ]]; then echo fake-container; exit 0; fi\nexit 2\n",
        encoding="utf-8",
    )
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\nif [[ $1 == inspect ]]; then echo starting; exit 0; fi\nexit 0\n",
        encoding="utf-8",
    )
    compose.chmod(0o755)
    docker.chmod(0o755)

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        export PATH={shlex.quote(str(fake_bin))}:$PATH
        export COMPOSE_HEALTH_WAIT_TIMEOUT_SECONDS=1
        export COMPOSE_HEALTH_WAIT_POLL_SECONDS=1
        source ./install_sidar.sh
        if wait_for_compose_services_health compose -- postgres; then
          echo "timeout was expected" >&2
          exit 1
        fi
        """,
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "timeout=1s" in combined
    assert "Servis health timeout: postgres" in combined
