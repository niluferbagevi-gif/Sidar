import os
import shlex
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.smoke.test_install_verification import (
    _SENSITIVE_ENV_KEYS,
    _installer_test_env,
    _run_bash_smoke,
)


def test_installer_test_env_scrubs_sensitive_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for key in _SENSITIVE_ENV_KEYS:
        monkeypatch.setenv(key, f"secret-{key.lower()}")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))

    env = _installer_test_env(tmp_path)

    assert env["SIDAR_ENV"] == "test"
    assert env["SIDAR_KEYS_FILE"] == ""
    assert env["SIDAR_TEST_LOAD_REAL_KEYS"] == "0"
    assert env["SIDAR_INSTALL_TEST_MODE"] == "1"
    assert env["TMPDIR"] == str(tmp_path)
    assert all(env.get(key, "") == "" for key in _SENSITIVE_ENV_KEYS)


def test_runtime_database_url_source_labels_survive_successful_resolution(tmp_path: Path) -> None:
    script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/utils/env_utils.sh
        source scripts/install_modules/utils/database_url.sh

        SCRIPT_DIR="$1"
        unset DATABASE_URL DOTENV_FILE RUNTIME_DATABASE_URL RUNTIME_DATABASE_URL_SOURCE

        export DATABASE_URL="postgresql+asyncpg://sidar:proc@localhost:5432/sidar"
        resolve_runtime_database_url >/dev/null
        printf 'process=%s\n' "$RUNTIME_DATABASE_URL_SOURCE"

        unset DATABASE_URL RUNTIME_DATABASE_URL RUNTIME_DATABASE_URL_SOURCE
        cat > "$SCRIPT_DIR/.env" <<'EOF'
DATABASE_URL=postgresql+asyncpg://sidar:env@localhost:5432/sidar
EOF
        resolve_runtime_database_url >/dev/null
        printf 'env_database=%s\n' "$RUNTIME_DATABASE_URL_SOURCE"

        unset RUNTIME_DATABASE_URL RUNTIME_DATABASE_URL_SOURCE
        cat > "$SCRIPT_DIR/.env" <<'EOF'
SIDAR_ENV=development
EOF
        cat > "$SCRIPT_DIR/.env.development" <<'EOF'
DATABASE_URL=postgresql+asyncpg://sidar:dev@localhost:5432/sidar
EOF
        resolve_runtime_database_url >/dev/null
        printf 'development_database=%s\n' "$RUNTIME_DATABASE_URL_SOURCE"

        unset RUNTIME_DATABASE_URL RUNTIME_DATABASE_URL_SOURCE
        cat > "$SCRIPT_DIR/.env" <<'EOF'
POSTGRES_USER=sidar
POSTGRES_PASSWORD=parts
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=sidar
EOF
        rm -f "$SCRIPT_DIR/.env.development"
        resolve_runtime_database_url >/dev/null
        printf 'env_postgres=%s\n' "$RUNTIME_DATABASE_URL_SOURCE"
        """
    )

    result = subprocess.run(
        ["bash", "-c", script, "sidar-db-url-source", str(tmp_path)],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(tmp_path),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "process=process:DATABASE_URL" in result.stdout
    assert "env_database=.env:DATABASE_URL" in result.stdout
    assert "development_database=.env.development:DATABASE_URL" in result.stdout
    assert "env_postgres=.env:POSTGRES_*" in result.stdout
    assert "bilinmiyor" not in result.stdout


def test_run_migrations_logs_resolved_database_url_source_not_unknown(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python_stub = fake_bin / "python3"
    python_stub.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "${1:-}" == "-m" && "${2:-}" == "alembic" ]]; then
              case "${3:-}" in
                upgrade) echo "upgrade ok"; exit 0 ;;
                current) echo "  0001_initial (head)"; exit 0 ;;
                heads) echo "  0001_initial (head)"; exit 0 ;;
              esac
            fi
            exit 1
            """
        ),
        encoding="utf-8",
    )
    python_stub.chmod(0o755)
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

    script = textwrap.dedent(
        """
        set -euo pipefail
        source scripts/install_modules/utils/env_utils.sh
        source scripts/install_modules/utils/database_url.sh
        source scripts/install_modules/phases/12_alembic.sh

        step() { :; }
        info() { printf 'INFO:%s\n' "$*"; }
        ok() { printf 'OK:%s\n' "$*"; }
        warn() { printf 'WARN:%s\n' "$*"; }
        fail() { printf 'FAIL:%s\n' "$*" >&2; exit 1; }
        debug() { :; }

        export SCRIPT_DIR="$1"
        export PATH="$2:$PATH"
        export DATABASE_URL="sqlite:///$1/alembic-smoke.db"
        export DOCKER_ONLY=false
        export MIGRATION_DOCKER_POLICY=disabled

        run_migrations
        """
    )

    result = subprocess.run(
        ["bash", "-c", script, "sidar-alembic-source", str(tmp_path), str(fake_bin)],
        cwd=Path(os.getcwd()),
        env=_installer_test_env(tmp_path),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Alembic DB URL kaynağı: process:DATABASE_URL" in result.stdout
    assert "Alembic DB URL kaynağı: bilinmiyor" not in result.stdout


def test_install_sidar_is_blank_helper_handles_whitespace(tmp_path: Path) -> None:
    result = _run_bash_smoke(
        """
        set -euo pipefail
        source ./install_sidar.sh >/dev/null
        is_blank ""
        is_blank "   "
        is_blank $'\\t\\n'
        ! is_blank "5.2.0"
        """,
        tmp_path,
    )
    assert result.returncode == 0, (
        "is_blank helper boş/whitespace sürüm kontrollerini beklenen şekilde ele almadı.\n"
        f"--- args ---\n{result.args}\n"
        f"--- stdout ---\n{result.stdout!r}\n"
        f"--- stderr ---\n{result.stderr!r}"
    )


def _valid_user_api_value(key: str, index: int) -> str:
    """Return installer-valid synthetic values for user supplied integration keys."""

    if key == "SLACK_WEBHOOK_URL":
        return f"https://hooks.slack.com/services/test/{index}"
    if key == "JIRA_URL":
        return f"https://example-{index}.atlassian.net"
    if key == "TEAMS_WEBHOOK_URL":
        return f"https://example.invalid/teams/{index}"
    return f"value_{index}"


def test_env_keys_synced_to_runtime_profiles_but_not_test_by_default(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    script_dir.mkdir()
    source_check = _run_bash_smoke(
        "set -euo pipefail; source ./install_sidar.sh; type sidar_user_api_key_names >/dev/null",
        tmp_path,
    )
    if source_check.returncode != 0:
        pytest.skip(
            "install_sidar.sh source edilemedi; API key senkronizasyon adımı anlamlı şekilde çalıştırılamaz.\n"
            f"{source_check.stdout}{source_check.stderr}"
        )

    key_script = "source ./install_sidar.sh; sidar_user_api_key_names"
    keys_result = _run_bash_smoke(key_script, tmp_path)
    assert keys_result.returncode == 0, keys_result.stdout + keys_result.stderr
    keys = [line.strip() for line in keys_result.stdout.splitlines() if line.strip()]
    assert len(keys) == 18

    env_lines = [
        f"{key}={_valid_user_api_value(key, idx)}" for idx, key in enumerate(keys, start=1)
    ]
    (script_dir / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    for name in (".env.advanced", ".env.development", ".env.test"):
        (script_dir / name).write_text(
            "\n".join(f"{key}=" for key in keys) + "\n", encoding="utf-8"
        )

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source ./install_sidar.sh
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        ENV_FILE="$SCRIPT_DIR/.env"
        NO_INTERACTION=true
        unset SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV
        SIDAR_KEYS_FILE="$SCRIPT_DIR/.sidar_keys.env"
        export SCRIPT_DIR ENV_FILE NO_INTERACTION SIDAR_KEYS_FILE
        collect_api_keys_interactive "$ENV_FILE"
        for key in $(sidar_user_api_key_names); do
          expected=$(read_env_value_from_file "$key" "$ENV_FILE")
          actual_secret=$(read_env_value_from_file "$key" "$SIDAR_KEYS_FILE")
          if [[ "$actual_secret" != "$expected" ]]; then
            echo "SIDAR_KEYS_FILE:$key expected=$expected actual=$actual_secret" >&2
            exit 1
          fi
          for profile in .env.advanced .env.development .env.test; do
            actual=$(read_env_value_from_file "$key" "$SCRIPT_DIR/$profile")
            if [[ -n "$actual" && "$actual" == "$expected" ]]; then
              echo "$profile:$key unexpectedly received real key value: $actual" >&2
              exit 1
            fi
          done
        done
        report_env_api_key_status "$ENV_FILE"
        test "$ENV_API_KEYS_TOTAL" -eq 18
        test "$ENV_API_KEYS_FILLED" -eq 18
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined_output = result.stdout + result.stderr
    assert "18 API anahtarı SIDAR_KEYS_FILE" in combined_output
    assert "içinde doğrulandı/güncellendi" in combined_output
    assert "üzerinden .env dosyasına aktarıldı" not in combined_output


def test_env_keys_synced_to_test_profile_with_explicit_opt_in(tmp_path: Path) -> None:
    script_dir = tmp_path / "sidar"
    script_dir.mkdir()
    source_check = _run_bash_smoke(
        "set -euo pipefail; source ./install_sidar.sh; type sidar_user_api_key_names >/dev/null",
        tmp_path,
    )
    if source_check.returncode != 0:
        pytest.skip(
            "install_sidar.sh source edilemedi; API key senkronizasyon adımı anlamlı şekilde çalıştırılamaz.\n"
            f"{source_check.stdout}{source_check.stderr}"
        )

    key_script = "source ./install_sidar.sh; sidar_user_api_key_names"
    keys_result = _run_bash_smoke(key_script, tmp_path)
    assert keys_result.returncode == 0, keys_result.stdout + keys_result.stderr
    keys = [line.strip() for line in keys_result.stdout.splitlines() if line.strip()]
    assert len(keys) == 18

    env_lines = [
        f"{key}={_valid_user_api_value(key, idx)}" for idx, key in enumerate(keys, start=1)
    ]
    (script_dir / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    for name in (".env.advanced", ".env.development", ".env.test"):
        (script_dir / name).write_text(
            "\n".join(f"{key}=" for key in keys) + "\n", encoding="utf-8"
        )

    result = _run_bash_smoke(
        f"""
        set -euo pipefail
        source ./install_sidar.sh
        SCRIPT_DIR={shlex.quote(str(script_dir))}
        ENV_FILE="$SCRIPT_DIR/.env"
        NO_INTERACTION=true
        SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV=1
        SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=1
        SIDAR_KEYS_FILE="$SCRIPT_DIR/.sidar_keys.env"
        export SCRIPT_DIR ENV_FILE NO_INTERACTION SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV SIDAR_KEYS_FILE
        collect_api_keys_interactive "$ENV_FILE"
        for profile in .env.advanced .env.development .env.test; do
          for key in $(sidar_user_api_key_names); do
            expected=$(read_env_value_from_file "$key" "$ENV_FILE")
            actual=$(read_env_value_from_file "$key" "$SCRIPT_DIR/$profile")
            if [[ "$actual" != "$expected" ]]; then
              echo "$profile:$key expected=$expected actual=$actual" >&2
              exit 1
            fi
          done
        done
        """,
        tmp_path,
        timeout_seconds=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined_output = result.stdout + result.stderr
    assert "18 API anahtarı" in combined_output
    assert "materialization açık" in combined_output
    assert ".env: 18 API anahtarı güncellendi." in combined_output
    assert ".env.advanced: 18 API anahtarı güncellendi." in combined_output
    assert ".env.development: 18 API anahtarı güncellendi." in combined_output
    assert ".env.test: 18 API anahtarı güncellendi." in combined_output
