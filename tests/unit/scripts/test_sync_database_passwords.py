from __future__ import annotations

import json
from urllib.parse import unquote, urlsplit

from scripts import sync_database_passwords


def _password_from(url: str) -> str:
    return unquote(urlsplit(url).password or "")


def test_sync_env_text_aligns_postgres_url_passwords_and_url_encodes_secret() -> None:
    env_text = (
        "\n".join(
            [
                "POSTGRES_PASSWORD=p@ss word/with:symbols",
                "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar?sslmode=disable",
                'SIDAR_CONTAINER_DATABASE_URL="postgresql+asyncpg://sidar:old@postgres:5432/sidar"',
            ]
        )
        + "\n"
    )

    updated, summary = sync_database_passwords.sync_env_text(env_text)

    assert summary["changed"] is True
    assert summary["changed_keys"] == ["DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL"]
    assert "p%40ss%20word%2Fwith%3Asymbols" in updated
    assert _password_from(updated.splitlines()[1].split("=", 1)[1]) == "p@ss word/with:symbols"
    assert (
        _password_from(updated.splitlines()[2].split("=", 1)[1].strip('"'))
        == "p@ss word/with:symbols"
    )


def test_sync_env_text_is_idempotent_for_matching_passwords() -> None:
    env_text = (
        "\n".join(
            [
                "POSTGRES_PASSWORD=aaaaaaaaaaaaaaaaaaaaaaaa",
                "DATABASE_URL=postgresql://sidar:aaaaaaaaaaaaaaaaaaaaaaaa@localhost:5432/sidar",
                "SIDAR_CONTAINER_DATABASE_URL=postgresql://sidar:aaaaaaaaaaaaaaaaaaaaaaaa@postgres:5432/sidar",
            ]
        )
        + "\n"
    )

    updated, summary = sync_database_passwords.sync_env_text(env_text)

    assert updated == env_text
    assert summary["changed"] is False
    assert summary["changed_keys"] == []


def test_sync_env_text_skips_non_postgres_urls_and_requires_postgres_password() -> None:
    updated, summary = sync_database_passwords.sync_env_text(
        "POSTGRES_PASSWORD=aaaaaaaaaaaaaaaaaaaaaaaa\nDATABASE_URL=sqlite:///tmp/sidar.db\n"
    )

    assert "sqlite:///tmp/sidar.db" in updated
    assert summary["skipped"] == {
        "DATABASE_URL": "not_postgresql_or_missing_username",
        "SIDAR_CONTAINER_DATABASE_URL": "missing",
    }

    try:
        sync_database_passwords.sync_env_text(
            "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar\n"
        )
    except ValueError as exc:
        assert "POSTGRES_PASSWORD" in str(exc)
    else:  # pragma: no cover - defensive assertion branch
        raise AssertionError("sync_env_text should require POSTGRES_PASSWORD")


def test_sync_env_file_writes_updated_content(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_PASSWORD=bbbbbbbbbbbbbbbbbbbbbbbb\n"
        "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar\n",
        encoding="utf-8",
    )

    summary = sync_database_passwords.sync_env_file(env_file)

    assert summary["env_file"] == str(env_file)
    assert summary["changed"] is True
    assert "old" not in env_file.read_text(encoding="utf-8")


def test_main_emits_redacted_json_summary(monkeypatch, tmp_path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_PASSWORD=cccccccccccccccccccccccc\n"
        "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar\n",
        encoding="utf-8",
    )

    assert sync_database_passwords.main(["--env-file", str(env_file)]) == 0

    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert summary["changed"] is True
    assert "cccccccc" not in output.out
    assert "cccccccc" not in output.err


def test_sync_env_chain_updates_later_override_files_with_effective_password(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    secret_file = tmp_path / "keys.env"
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(secret_file))

    base_env = tmp_path / ".env"
    base_env.write_text(
        "POSTGRES_PASSWORD=" + "a" * 24 + "\n"
        "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    advanced_env = tmp_path / ".env.advanced"
    advanced_env.write_text(
        "SIDAR_CONTAINER_DATABASE_URL=postgresql://sidar:old@postgres:5432/sidar\n",
        encoding="utf-8",
    )
    development_env = tmp_path / ".env.development"
    development_env.write_text(
        "DATABASE_URL=postgresql://sidar:devold@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    secret_file.write_text("POSTGRES_PASSWORD=" + "s" * 24 + "\n", encoding="utf-8")

    summary = sync_database_passwords.sync_env_chain(base_env)

    assert summary["changed"] is True
    assert str(base_env) in summary["changed_files"]
    assert str(advanced_env) in summary["changed_files"]
    assert str(development_env) in summary["changed_files"]
    base_database_url = next(
        line.split("=", 1)[1]
        for line in base_env.read_text(encoding="utf-8").splitlines()
        if line.startswith("DATABASE_URL=")
    )
    development_database_url = development_env.read_text(encoding="utf-8").split("=", 1)[1]
    advanced_container_url = advanced_env.read_text(encoding="utf-8").split("=", 1)[1]
    assert _password_from(base_database_url) == "s" * 24
    assert _password_from(development_database_url) == "s" * 24
    assert _password_from(advanced_container_url) == "s" * 24
    assert summary["changed_keys_by_file"][str(development_env)] == ["DATABASE_URL"]


def test_sync_env_chain_reports_missing_override_url_keys_without_leaking_secret(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIDAR_CONTAINER_DATABASE_URL", raising=False)
    secret_file = tmp_path / "keys.env"
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(secret_file))

    base_env = tmp_path / ".env"
    base_env.write_text(
        "POSTGRES_PASSWORD=" + "a" * 24 + "\n"
        "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    secret_file.write_text("POSTGRES_PASSWORD=" + "s" * 24 + "\n", encoding="utf-8")

    summary = sync_database_passwords.sync_env_chain(base_env)

    secret_summary = next(
        item for item in summary["file_summaries"] if item["label"] == "secret:SIDAR_KEYS_FILE"
    )
    assert secret_summary["skipped"] == {
        "DATABASE_URL": "missing",
        "SIDAR_CONTAINER_DATABASE_URL": "missing",
    }
    assert not summary["warnings"]
    assert any(
        note["severity"] == "info" and "does not define DATABASE_URL" in note["message"]
        for note in summary["notes"]
    )
    assert all("s" * 24 not in note["message"] for note in summary["notes"])
    assert (
        _password_from(base_env.read_text(encoding="utf-8").split("DATABASE_URL=", 1)[1])
        == "s" * 24
    )


def test_main_reports_no_change_guidance_for_idempotent_chain(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    env_file = tmp_path / ".env"
    password = "a" * 24
    env_file.write_text(
        f"POSTGRES_PASSWORD={password}\n"
        f"DATABASE_URL=postgresql://sidar:{password}@localhost:5432/sidar\n",
        encoding="utf-8",
    )

    assert sync_database_passwords.main(["--env-file", str(env_file)]) == 0

    captured = capsys.readouterr()
    assert "zaten POSTGRES_PASSWORD ile uyumlu" in captured.err
    assert "reload the launcher environment" in captured.err


def test_sync_env_chain_marks_effective_password_drift_warnings_critical(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:stale@localhost:5432/sidar")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_PASSWORD=" + "n" * 24 + "\n"
        "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar\n",
        encoding="utf-8",
    )

    summary = sync_database_passwords.sync_env_chain(env_file)

    assert summary["warnings"] == [
        {
            "severity": "critical",
            "message": (
                "Effective DATABASE_URL password still differs from POSTGRES_PASSWORD after sync; "
                "check later dotenv overrides or unsupported dotenv syntax."
            ),
            "key": "DATABASE_URL",
        }
    ]
    assert summary["notes"] == []

def test_remove_explicit_database_urls_from_text_preserves_non_postgres_url() -> None:
    updated, summary = sync_database_passwords.remove_explicit_database_urls_from_text(
        "POSTGRES_PASSWORD=cccccccccccccccccccccccc\n"
        "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar\n"
        "SIDAR_CONTAINER_DATABASE_URL=sqlite:///tmp/sidar.db\n"
        "WEB_PORT=8080\n"
    )

    assert "DATABASE_URL=postgresql" not in updated
    assert "SIDAR_CONTAINER_DATABASE_URL=sqlite:///tmp/sidar.db" in updated
    assert "WEB_PORT=8080" in updated
    assert summary["changed"] is True
    assert summary["removed_keys"] == ["DATABASE_URL"]
    assert summary["skipped"] == {"SIDAR_CONTAINER_DATABASE_URL": "not_postgresql"}


def test_sync_env_chain_can_remove_explicit_postgres_urls(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_PASSWORD=" + "d" * 24 + "\n"
        "POSTGRES_HOST=localhost\n"
        "POSTGRES_CONTAINER_HOST=postgres\n"
        "POSTGRES_PORT=5432\n"
        "POSTGRES_DB=sidar\n"
        "POSTGRES_USER=sidar\n"
        "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar\n"
        "SIDAR_CONTAINER_DATABASE_URL=postgresql://sidar:old@postgres:5432/sidar\n",
        encoding="utf-8",
    )

    summary = sync_database_passwords.sync_env_chain(env_file, remove_explicit_urls=True)

    text = env_file.read_text(encoding="utf-8")
    assert "DATABASE_URL=" not in text
    assert "SIDAR_CONTAINER_DATABASE_URL=" not in text
    assert "POSTGRES_PASSWORD=" in text
    assert summary["changed"] is True
    assert summary["strategy"] == "remove_explicit_urls"
    assert summary["changed_keys"] == ["DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL"]
