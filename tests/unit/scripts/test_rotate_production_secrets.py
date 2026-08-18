"""Tests for the production secret rotation command."""

from pathlib import Path

import scripts.rotate_production_secrets as rotation
from scripts.rotate_production_secrets import ROTATION_KEYS, main


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")


def test_audit_rejects_secrets_shared_with_development(tmp_path, capsys):
    """A strong value is still unsafe when production and development share it."""
    shared = "A_unique_but_shared_value_1234567890-ABCDEFG"
    values = {key: f"{shared}-{index}" for index, key in enumerate(ROTATION_KEYS)}
    production = tmp_path / ".env.production"
    development = tmp_path / ".env.development"
    _write_env(production, values)
    _write_env(development, values)

    assert main(["--env-file", str(production), "--reference-env", str(development)]) == 1
    output = capsys.readouterr()
    assert "shared_with_non_production" in output.err
    assert shared not in output.err


def test_apply_rotates_all_values_atomically_and_keeps_them_private(tmp_path, capsys):
    """Explicit rotation creates isolated strong values and a mode-600 dotenv."""
    old = {
        key: f"old-shared-value-{index}-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for index, key in enumerate(ROTATION_KEYS)
    }
    production = tmp_path / ".env.production"
    development = tmp_path / ".env.development"
    _write_env(production, old)
    _write_env(development, old)

    assert (
        main(
            [
                "--env-file",
                str(production),
                "--reference-env",
                str(development),
                "--apply",
                "--ack-memory-key-impact",
            ]
        )
        == 0
    )
    content = production.read_text(encoding="utf-8")
    output = capsys.readouterr()
    assert production.stat().st_mode & 0o777 == 0o600
    assert all(f"{key}=" in content for key in ROTATION_KEYS)
    assert all(value not in content for value in old.values())
    assert all(value not in output.out for value in content.splitlines())


def test_apply_requires_memory_key_impact_acknowledgement(tmp_path):
    """Rotation cannot silently destroy access to Fernet-encrypted records."""
    production = tmp_path / ".env.production"
    _write_env(production, {})

    try:
        main(["--env-file", str(production), "--apply"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("rotation unexpectedly proceeded without acknowledgement")


def test_generated_secrets_retry_values_rejected_by_post_write_audit(monkeypatch):
    """Random placeholder-like output cannot make rotation fail intermittently."""
    rejected = "random-output-rejected-by-policy"
    accepted = "Kp9_Zm7-Qx2_Vc8-Nr5_Wf6-Yh3_Tj4-Ls9_Bd7-Gn2"
    candidates = iter([rejected, accepted])

    monkeypatch.setattr(rotation, "is_weak_secret", lambda value: value == rejected)

    assert rotation._generate_accepted_secret(lambda: next(candidates)) == accepted


def test_rotation_keys_cover_postgres_and_redis_passwords():
    """Fail-closed regression for a review comment.

    Rotation used to skip POSTGRES_PASSWORD/REDIS_PASSWORD entirely, and no
    automatic sync script existed for the Redis side of that gap (see
    scripts/sync_redis_password.py).
    """
    assert "POSTGRES_PASSWORD" in ROTATION_KEYS
    assert "REDIS_PASSWORD" in ROTATION_KEYS


def test_apply_propagates_rotated_postgres_and_redis_passwords_into_embedded_urls(tmp_path):
    """Rotating POSTGRES_PASSWORD/REDIS_PASSWORD must not leave stale URLs behind."""
    production = tmp_path / ".env.production"
    _write_env(
        production,
        {
            "POSTGRES_USER": "sidar",
            "POSTGRES_PASSWORD": "old-postgres-password-value",
            "REDIS_PASSWORD": "old-redis-password-value",
            "DATABASE_URL": "postgresql+asyncpg://sidar:old-postgres-password-value@127.0.0.1:5432/sidar",
            "SIDAR_CONTAINER_DATABASE_URL": (
                "postgresql+asyncpg://sidar:old-postgres-password-value@postgres:5432/sidar"
            ),
            "SIDAR_REDIS_URL": "redis://:old-redis-password-value@127.0.0.1:6379/0",
        },
    )

    assert (
        main(
            [
                "--env-file",
                str(production),
                "--reference-env",
                "/dev/null",
                "--apply",
                "--ack-memory-key-impact",
            ]
        )
        == 0
    )

    content = production.read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in content.splitlines() if "=" in line)
    assert "old-postgres-password-value" not in content
    assert "old-redis-password-value" not in content
    assert values["POSTGRES_PASSWORD"] in values["DATABASE_URL"]
    assert values["POSTGRES_PASSWORD"] in values["SIDAR_CONTAINER_DATABASE_URL"]
    assert values["REDIS_PASSWORD"] in values["SIDAR_REDIS_URL"]


def test_audit_flags_embedded_url_password_left_stale_after_manual_edit(tmp_path, capsys):
    """A DATABASE_URL/SIDAR_REDIS_URL that drifts from the bare password must fail the audit."""
    production = tmp_path / ".env.production"
    _write_env(
        production,
        {
            "POSTGRES_PASSWORD": "current-postgres-password-value-abc",
            "DATABASE_URL": "postgresql+asyncpg://sidar:STALE-password@127.0.0.1:5432/sidar",
            "REDIS_PASSWORD": "current-redis-password-value-xyz",
            "SIDAR_REDIS_URL": "redis://:STALE-password@127.0.0.1:6379/0",
        },
    )

    assert main(["--env-file", str(production), "--reference-env", "/dev/null"]) == 1
    output = capsys.readouterr()
    assert "DATABASE_URL: embedded_url_password_stale" in output.err
    assert "SIDAR_REDIS_URL: embedded_url_password_stale" in output.err
