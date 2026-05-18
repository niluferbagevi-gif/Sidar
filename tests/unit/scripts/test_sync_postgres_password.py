from __future__ import annotations

import json
import shutil
import subprocess

from scripts import sync_postgres_password


def test_sync_postgres_password_uses_stdin_and_redacts_secret(monkeypatch):
    calls = {}
    secret = "super-secret-password-123456"

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=f"ALTER ROLE {secret}\n")

    monkeypatch.setenv("SIDAR_ENV", "development")
    monkeypatch.setenv("POSTGRES_USER", "sidar")
    monkeypatch.setenv("POSTGRES_PASSWORD", secret)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = sync_postgres_password.sync_postgres_password_with_docker_compose()

    assert summary["changed"] is True
    assert summary["postgres_user"] == "sidar"
    assert secret not in " ".join(calls["cmd"])
    assert "ALTER USER" in calls["kwargs"]["input"]
    assert secret in calls["kwargs"]["input"]
    assert calls["kwargs"]["cwd"] == sync_postgres_password.PROJECT_ROOT


def test_sync_postgres_password_loads_missing_values_from_dotenv(monkeypatch, tmp_path):
    calls = {}
    secret = "dotenv-secret-password-123456"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SIDAR_ENV=development\n"
        "POSTGRES_USER=sidar\n"
        f"POSTGRES_PASSWORD={secret}\n"
        "POSTGRES_DB=sidar\n",
        encoding="utf-8",
    )

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ALTER ROLE\n")

    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.setattr(sync_postgres_password, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = sync_postgres_password.sync_postgres_password_with_docker_compose()

    assert summary["postgres_user"] == "sidar"
    assert calls["cmd"][calls["cmd"].index("-U") + 1] == "sidar"
    assert calls["cmd"][calls["cmd"].index("-d") + 1] == "sidar"
    assert secret in calls["kwargs"]["input"]


def test_sync_postgres_password_refuses_non_dev_without_override(monkeypatch):
    monkeypatch.setenv("SIDAR_ENV", "production")
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret-password-123456")

    try:
        sync_postgres_password.sync_postgres_password_with_docker_compose()
    except RuntimeError as exc:
        assert "Refusing to mutate PostgreSQL credentials" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected RuntimeError")


def test_sync_postgres_password_main_emits_redacted_summary(monkeypatch, capsys):
    secret = "super-secret-password-123456"

    def fake_sync(*, allow_non_dev=False):
        assert allow_non_dev is False
        return {
            "changed": True,
            "method": "docker-compose",
            "postgres_user": "sidar",
            "postgres_password_set": True,
        }

    monkeypatch.setenv("POSTGRES_PASSWORD", secret)
    monkeypatch.setattr(sync_postgres_password, "sync_postgres_password_with_docker_compose", fake_sync)

    assert sync_postgres_password.main([]) == 0

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert json.loads(captured.out)["postgres_password_set"] is True
