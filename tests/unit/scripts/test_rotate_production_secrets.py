"""Tests for the production secret rotation command."""

from pathlib import Path

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
