from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from scripts import sync_postgres_password


def _write_env(
    path: Path,
    *,
    sidar_env: str = "development",
    password: str,
    pre_harden_password: str | None = None,
) -> None:
    lines = [
        f"SIDAR_ENV={sidar_env}",
        "POSTGRES_USER=sidar",
        "POSTGRES_DB=sidar",
        f"POSTGRES_PASSWORD={password}",
    ]
    if pre_harden_password is not None:
        lines.append(f"PRE_HARDEN_DB_PASSWORD={pre_harden_password}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_sync_postgres_password_uses_docker_exec_stdin_and_redacts_secret(
    monkeypatch, tmp_path: Path
):
    calls = {}
    secret = "super-secret-password-123456"
    env_file = tmp_path / ".env"
    _write_env(env_file, password=secret)

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=f"ALTER ROLE {secret}\n")

    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = sync_postgres_password.sync_postgres_password_with_docker_exec(env_file=env_file)

    assert summary["changed"] is True
    assert summary["method"] == "docker-exec"
    assert summary["postgres_user"] == "sidar"
    assert calls["cmd"][:3] == ["/usr/bin/docker", "exec", "-i"]
    assert "-e" in calls["cmd"]
    assert f"PGPASSWORD={secret}" in calls["cmd"]
    assert "sidar_postgres" in calls["cmd"]
    assert "psql" in calls["cmd"]
    assert "ALTER USER" in calls["kwargs"]["input"]
    assert secret in calls["kwargs"]["input"]
    assert calls["kwargs"]["timeout"] == 90
    assert calls["kwargs"]["cwd"] == sync_postgres_password.PROJECT_ROOT


def test_sync_postgres_password_reads_later_dotenv_override(monkeypatch, tmp_path: Path):
    calls = {}
    base_secret = "base-secret-password-123456"
    override_secret = "override-secret-password-123456"
    env_file = tmp_path / ".env"
    override_file = tmp_path / ".env.development"
    _write_env(env_file, password=base_secret)
    override_file.write_text(
        f"POSTGRES_PASSWORD={override_secret}\nPOSTGRES_USER=sidar\n", encoding="utf-8"
    )

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ALTER ROLE\n")

    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = sync_postgres_password.sync_postgres_password_with_docker_exec(env_file=env_file)

    assert f"PGPASSWORD={override_secret}" in calls["cmd"]
    assert override_secret in calls["kwargs"]["input"]
    assert base_secret not in calls["kwargs"]["input"]
    assert str(override_file) in summary["checked_files"]



def test_sync_postgres_password_prefers_pre_harden_password_for_docker_auth(
    monkeypatch, tmp_path: Path
):
    calls = {}
    old_secret = "old-volume-password-123456"
    new_secret = "new-env-password-123456"
    env_file = tmp_path / ".env"
    _write_env(env_file, password=new_secret, pre_harden_password=old_secret)

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ALTER ROLE\n")

    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    sync_postgres_password.sync_postgres_password_with_docker_exec(env_file=env_file)

    assert f"PGPASSWORD={old_secret}" in calls["cmd"]
    assert f"PGPASSWORD={new_secret}" not in calls["cmd"]
    assert new_secret in calls["kwargs"]["input"]


def test_sync_postgres_password_falls_back_to_current_password_when_old_secret_fails(
    monkeypatch, tmp_path: Path
):
    calls = []
    old_secret = "stale-volume-password-123456"
    new_secret = "current-env-password-123456"
    env_file = tmp_path / ".env"
    _write_env(env_file, password=new_secret, pre_harden_password=old_secret)

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if f"PGPASSWORD={old_secret}" in cmd:
            return subprocess.CompletedProcess(cmd, 2, stdout="password authentication failed")
        return subprocess.CompletedProcess(cmd, 0, stdout="ALTER ROLE\n")

    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = sync_postgres_password.sync_postgres_password_with_docker_exec(env_file=env_file)

    assert len(calls) == 2
    assert f"PGPASSWORD={old_secret}" in calls[0][0]
    assert f"PGPASSWORD={new_secret}" in calls[1][0]
    assert summary["changed"] is True


def test_sync_postgres_password_reads_pre_harden_password_file_and_removes_it(
    monkeypatch, tmp_path: Path
):
    calls = {}
    old_secret = "old-file-volume-password-123456"
    new_secret = "new-file-env-password-123456"
    env_file = tmp_path / ".env"
    password_file = tmp_path / "pre_harden_postgres_password"
    password_file.write_text(old_secret, encoding="utf-8")
    _write_env(env_file, password=new_secret)

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=f"ALTER ROLE {old_secret} {new_secret}\n")

    monkeypatch.delenv("PRE_HARDEN_DB_PASSWORD", raising=False)
    monkeypatch.setenv("PRE_HARDEN_DB_PASSWORD_FILE", str(password_file))
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = sync_postgres_password.sync_postgres_password_with_docker_exec(env_file=env_file)

    assert f"PGPASSWORD={old_secret}" in calls["cmd"]
    assert new_secret in calls["kwargs"]["input"]
    assert summary["command"] == "docker exec -i -e PGPASSWORD=*** <postgres_container> psql -U <admin> -d <admin_db>"
    assert not password_file.exists()



def test_sync_postgres_password_honors_timeout_env(monkeypatch, tmp_path: Path):
    calls = {}
    secret = "timeout-secret-password-123456"
    env_file = tmp_path / ".env"
    _write_env(env_file, password=secret)

    def fake_run(cmd, **kwargs):
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ALTER ROLE\n")

    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setenv("SIDAR_PG_SYNC_TIMEOUT", "123")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    sync_postgres_password.sync_postgres_password_with_docker_exec(env_file=env_file)

    assert calls["kwargs"]["timeout"] == 123


def test_sync_postgres_password_invalid_timeout_falls_back(monkeypatch, tmp_path: Path):
    calls = {}
    secret = "timeout-fallback-secret-password-123456"
    env_file = tmp_path / ".env"
    _write_env(env_file, password=secret)

    def fake_run(cmd, **kwargs):
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ALTER ROLE\n")

    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setenv("SIDAR_PG_SYNC_TIMEOUT", "not-an-int")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    sync_postgres_password.sync_postgres_password_with_docker_exec(env_file=env_file)

    assert calls["kwargs"]["timeout"] == 90


def test_sync_postgres_password_refuses_non_dev_from_env_file_without_override(
    monkeypatch, tmp_path: Path
):
    env_file = tmp_path / ".env"
    _write_env(env_file, sidar_env="production", password="super-secret-password-123456")
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")

    try:
        sync_postgres_password.sync_postgres_password_with_docker_exec(env_file=env_file)
    except RuntimeError as exc:
        assert "Refusing to mutate PostgreSQL credentials" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected RuntimeError")


def test_sync_postgres_password_backward_compatible_wrapper_uses_docker_exec(
    monkeypatch, tmp_path: Path
):
    calls = {}
    env_file = tmp_path / ".env"
    _write_env(env_file, password="super-secret-password-123456")

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ALTER ROLE\n")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = sync_postgres_password.sync_postgres_password_with_docker_compose(env_file=env_file)

    assert summary["method"] == "docker-exec"
    assert calls["cmd"][1:3] == ["exec", "-i"]
    assert any(arg.startswith("PGPASSWORD=") for arg in calls["cmd"])


def test_sync_postgres_password_main_emits_redacted_summary(monkeypatch, capsys, tmp_path: Path):
    secret = "super-secret-password-123456"
    env_file = tmp_path / ".env"
    _write_env(env_file, password=secret)

    def fake_sync(*, allow_non_dev=False, env_file=None, postgres_container=None):
        assert allow_non_dev is False
        assert postgres_container is None
        return {
            "changed": True,
            "method": "docker-exec",
            "postgres_user": "sidar",
            "postgres_password_set": True,
            "checked_files": [str(env_file)],
        }

    monkeypatch.setattr(
        sync_postgres_password, "sync_postgres_password_with_docker_exec", fake_sync
    )

    assert sync_postgres_password.main(["--env-file", str(env_file)]) == 0

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert json.loads(captured.out)["postgres_password_set"] is True
