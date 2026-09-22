"""Security and environment-profile Doctor checks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import core.doctor as _doctor
from core.doctor import DoctorCheck


def _read_env_file_assignments(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE assignments from a dotenv file without expanding secrets."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if not key:  # pragma: no cover - stripping a non-empty assignment key cannot empty it
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def check_environment_profile() -> DoctorCheck:
    """Validate that the selected SIDAR_ENV profile has an isolated dotenv file."""
    profile = os.getenv("SIDAR_ENV", "").strip().lower()
    details: dict[str, Any] = {
        "sidar_env": profile,
        "base_env_path": str(_doctor.BASE_DIR / ".env"),
        "advanced_env_path": str(_doctor.BASE_DIR / ".env.advanced"),
        "recommended_commands": [
            "uv run python -m scripts.bootstrap_env --profile development",
            "cp .env.development.example .env.development",
        ],
    }
    if not profile:
        return DoctorCheck(
            "environment_profile",
            "pass",
            "SIDAR_ENV profile is not set; base dotenv/default settings are in use",
            details,
        )

    profile_path = _doctor.BASE_DIR / f".env.{profile}"
    template_path = _doctor.BASE_DIR / f".env.{profile}.example"
    details.update(
        {
            "profile_env_path": str(profile_path),
            "profile_env_exists": profile_path.exists(),
            "profile_template_path": str(template_path),
            "profile_template_exists": template_path.exists(),
        }
    )

    if profile == "test":
        return DoctorCheck(
            "environment_profile",
            "pass",
            "SIDAR_ENV=test uses test fixtures/process environment isolation",
            details,
        )
    if profile_path.exists():
        profile_values = _read_env_file_assignments(profile_path)
        effective_postgres_db = profile_values.get("POSTGRES_DB") or os.getenv("POSTGRES_DB", "")
        details["profile_postgres_db"] = effective_postgres_db
        if profile in {"development", "dev", "local"} and effective_postgres_db in {
            "sidar",
            "postgres",
        }:
            details["recommended_commands"] = [
                f"uv run python -m scripts.bootstrap_env --profile {profile} --force",
                (
                    f"edit .env.{profile} and set "
                    f"POSTGRES_DB=sidar_{profile if profile != 'dev' else 'development'}"
                ),
            ]
            return DoctorCheck(
                "environment_profile",
                "warn",
                (
                    f"SIDAR_ENV={profile} has .env.{profile}, but "
                    f"POSTGRES_DB={effective_postgres_db!r} is not isolated from the "
                    "base/production database"
                ),
                details,
            )
        return DoctorCheck(
            "environment_profile",
            "pass",
            f"SIDAR_ENV={profile} isolated dotenv file is present",
            details,
        )

    if template_path.exists():
        command = f"uv run python -m scripts.bootstrap_env --profile {profile}"
        details["recommended_commands"] = [command, f"cp .env.{profile}.example .env.{profile}"]
        return DoctorCheck(
            "environment_profile",
            "warn",
            f"SIDAR_ENV={profile} is active but .env.{profile} is missing; create it from "
            f".env.{profile}.example to isolate local settings",
            details,
        )

    return DoctorCheck(
        "environment_profile",
        "warn",
        f"SIDAR_ENV={profile} is active but no .env.{profile} or .env.{profile}.example file "
        f"exists",
        details,
    )


__all__ = ["check_environment_profile"]
