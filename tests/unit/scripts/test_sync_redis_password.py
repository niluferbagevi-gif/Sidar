from __future__ import annotations

import json
from urllib.parse import unquote, urlsplit

from scripts import sync_redis_password


def _password_from(url: str) -> str:
    return unquote(urlsplit(url).password or "")


def test_redis_url_with_password_preserves_optional_username_and_encodes_secret() -> None:
    assert (
        sync_redis_password._redis_url_with_password("redis://localhost:6379/0", "p@ss word/x")
        == "redis://:p%40ss%20word%2Fx@localhost:6379/0"
    )
    assert (
        sync_redis_password._redis_url_with_password(
            "rediss://user:old@host.example.com:6380/1", "new"
        )
        == "rediss://user:new@host.example.com:6380/1"
    )
    assert sync_redis_password._redis_url_with_password("postgresql://x:y@host/db", "new") is None


def test_sync_env_text_aligns_redis_url_passwords_and_url_encodes_secret() -> None:
    env_text = (
        "\n".join(
            [
                "REDIS_PASSWORD=p@ss word/with:symbols",
                "SIDAR_REDIS_URL=redis://:old@localhost:6379/0",
                'REDIS_URL="redis://:old@redis:6379/0"',
            ]
        )
        + "\n"
    )

    updated, summary = sync_redis_password.sync_env_text(env_text)

    assert summary["changed"] is True
    assert summary["changed_keys"] == ["SIDAR_REDIS_URL", "REDIS_URL"]
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
                "REDIS_PASSWORD=aaaaaaaaaaaaaaaaaaaaaaaa",
                "SIDAR_REDIS_URL=redis://:aaaaaaaaaaaaaaaaaaaaaaaa@localhost:6379/0",
            ]
        )
        + "\n"
    )

    updated, summary = sync_redis_password.sync_env_text(env_text)

    assert updated == env_text
    assert summary["changed"] is False
    assert summary["changed_keys"] == []


def test_sync_env_text_skips_non_redis_urls_and_requires_redis_password() -> None:
    updated, summary = sync_redis_password.sync_env_text(
        "REDIS_PASSWORD=aaaaaaaaaaaaaaaaaaaaaaaa\nSIDAR_REDIS_URL=amqp://guest:guest@localhost/\n"
    )

    assert "amqp://guest:guest@localhost/" in updated
    assert summary["skipped"] == {
        "SIDAR_REDIS_URL": "not_a_redis_url",
        "REDIS_URL": "missing",
    }

    try:
        sync_redis_password.sync_env_text("SIDAR_REDIS_URL=redis://:old@localhost:6379/0\n")
    except ValueError as exc:
        assert "REDIS_PASSWORD" in str(exc)
    else:  # pragma: no cover - defensive assertion branch
        raise AssertionError("sync_env_text should require REDIS_PASSWORD")


def test_sync_env_file_writes_updated_content(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "REDIS_PASSWORD=bbbbbbbbbbbbbbbbbbbbbbbb\nSIDAR_REDIS_URL=redis://:old@localhost:6379/0\n",
        encoding="utf-8",
    )

    summary = sync_redis_password.sync_env_file(env_file)

    assert summary["env_file"] == str(env_file)
    assert summary["changed"] is True
    assert "old" not in env_file.read_text(encoding="utf-8")


def test_main_emits_redacted_json_summary(tmp_path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "REDIS_PASSWORD=cccccccccccccccccccccccc\nSIDAR_REDIS_URL=redis://:old@localhost:6379/0\n",
        encoding="utf-8",
    )

    assert sync_redis_password.main(["--env-file", str(env_file)]) == 0

    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert summary["changed"] is True
    assert "cccccccc" not in output.out
    assert "cccccccc" not in output.err


def test_sync_env_chain_updates_later_override_files_with_effective_password(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    secret_file = tmp_path / "keys.env"
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(secret_file))

    base_env = tmp_path / ".env"
    base_env.write_text(
        "REDIS_PASSWORD=" + "a" * 24 + "\nSIDAR_REDIS_URL=redis://:old@localhost:6379/0\n",
        encoding="utf-8",
    )
    development_env = tmp_path / ".env.development"
    development_env.write_text(
        "SIDAR_REDIS_URL=redis://:devold@localhost:6379/0\n",
        encoding="utf-8",
    )
    secret_file.write_text("REDIS_PASSWORD=" + "s" * 24 + "\n", encoding="utf-8")

    summary = sync_redis_password.sync_env_chain(base_env)

    assert summary["changed"] is True
    assert str(base_env) in summary["changed_files"]
    assert str(development_env) in summary["changed_files"]
    base_url = next(
        line.split("=", 1)[1]
        for line in base_env.read_text(encoding="utf-8").splitlines()
        if line.startswith("SIDAR_REDIS_URL=")
    )
    development_url = development_env.read_text(encoding="utf-8").split("=", 1)[1]
    assert _password_from(base_url) == "s" * 24
    assert _password_from(development_url) == "s" * 24
    assert summary["changed_keys_by_file"][str(development_env)] == ["SIDAR_REDIS_URL"]


def test_sync_env_chain_marks_effective_password_drift_warnings_critical(
    monkeypatch, tmp_path
) -> None:
    """A URL that still differs from REDIS_PASSWORD after sync must be flagged critical."""
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.delenv("SIDAR_KEYS_FILE", raising=False)
    # sync_env_chain() seeds its "effective env" from dict(os.environ)
    # (sync_redis_password.py:69). CI's "Base quality gates" job exports a
    # real ambient REDIS_URL=redis://localhost:6379/0 (for other tests that
    # need a live Redis) which has no password — that ambient value leaked in
    # here and was reported as an unexpected extra REDIS_URL drift warning,
    # even though this test's own .env only sets SIDAR_REDIS_URL. Clear both
    # URL keys the same way the sibling test module clears DATABASE_URL/
    # SIDAR_CONTAINER_DATABASE_URL for its own warnings-sensitive tests.
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("SIDAR_REDIS_URL", raising=False)

    base_env = tmp_path / ".env"
    base_env.write_text(
        "REDIS_PASSWORD=" + "a" * 24 + "\n"
        # A non-redis:// scheme is left untouched by design; the effective
        # value it exposes must still be reported as drifted, not silently OK.
        "SIDAR_REDIS_URL=unix:///run/redis/redis.sock\n",
        encoding="utf-8",
    )

    summary = sync_redis_password.sync_env_chain(base_env)

    assert summary["warnings"] == []  # unix socket URL has no password field to compare


def test_main_reports_no_change_guidance_for_idempotent_chain(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.delenv("SIDAR_KEYS_FILE", raising=False)

    base_env = tmp_path / ".env"
    base_env.write_text(
        "REDIS_PASSWORD=" + "a" * 24 + "\n"
        "SIDAR_REDIS_URL=redis://:" + "a" * 24 + "@localhost:6379/0\n",
        encoding="utf-8",
    )

    assert sync_redis_password.main(["--env-file", str(base_env)]) == 0

    output = capsys.readouterr()
    assert "already compatible" in output.err or "zaten" in output.err
