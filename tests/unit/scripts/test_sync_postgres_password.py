from __future__ import annotations

from pathlib import Path

from scripts import sync_postgres_password as sync


def test_build_alter_user_sql_quotes_identifier_and_literal() -> None:
    sql = sync.build_alter_user_sql('sidar"dev', "pa'ss")

    assert sql == 'ALTER USER "sidar""dev" WITH PASSWORD \'pa\'\'ss\';'


def test_dry_run_redacts_password_and_does_not_run_subprocess(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_USER=sidar\nPOSTGRES_PASSWORD=super-secret-password\n",
        encoding="utf-8",
    )
    called = False

    def fake_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("dry-run must not call subprocess")

    monkeypatch.setattr(sync.subprocess, "run", fake_run)

    assert sync.main(["--env-file", str(env_file), "--dry-run"]) == 0
    output = capsys.readouterr().out

    assert called is False
    assert "super-secret-password" not in output
    assert "uv run python -m scripts.sync_postgres_password --apply" in output


def test_apply_runs_docker_compose_with_safe_argv(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_USER=sidar\nPOSTGRES_PASSWORD=super-secret-password\n",
        encoding="utf-8",
    )
    calls = []

    class Completed:
        returncode = 0

    def fake_run(command, check=False):
        calls.append((command, check))
        return Completed()

    monkeypatch.setattr(sync.subprocess, "run", fake_run)

    assert sync.main(["--env-file", str(env_file), "--apply"]) == 0
    assert calls
    command, check = calls[0]
    assert check is False
    assert command[:5] == ["docker", "compose", "exec", "-T", "postgres"]
    assert command[-1] == 'ALTER USER "sidar" WITH PASSWORD \'super-secret-password\';'
