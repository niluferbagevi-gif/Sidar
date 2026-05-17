from __future__ import annotations

import json
from urllib.parse import unquote, urlsplit

from scripts import sync_database_passwords


def _password_from(url: str) -> str:
    return unquote(urlsplit(url).password or "")


def test_sync_env_text_aligns_postgres_url_passwords_and_url_encodes_secret() -> None:
    env_text = "\n".join(
        [
            "POSTGRES_PASSWORD=p@ss word/with:symbols",
            "DATABASE_URL=postgresql://sidar:old@localhost:5432/sidar?sslmode=disable",
            'SIDAR_CONTAINER_DATABASE_URL="postgresql+asyncpg://sidar:old@postgres:5432/sidar"',
        ]
    ) + "\n"

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
    env_text = "\n".join(
        [
            "POSTGRES_PASSWORD=aaaaaaaaaaaaaaaaaaaaaaaa",
            "DATABASE_URL=postgresql://sidar:aaaaaaaaaaaaaaaaaaaaaaaa@localhost:5432/sidar",
            "SIDAR_CONTAINER_DATABASE_URL=postgresql://sidar:aaaaaaaaaaaaaaaaaaaaaaaa@postgres:5432/sidar",
        ]
    ) + "\n"

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
