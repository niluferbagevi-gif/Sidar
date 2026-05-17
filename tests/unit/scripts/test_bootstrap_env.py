from __future__ import annotations

from pathlib import Path

import pytest

from scripts import bootstrap_env


def test_bootstrap_profile_env_creates_gitignored_development_file_with_generated_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = tmp_path / ".env.development.example"
    template.write_text(
        "SIDAR_ENV=development\n"
        "POSTGRES_PASSWORD=replace-with-a-strong-24-plus-character-password\n"
        "API_KEY=replace-with-a-local-development-api-key\n"
        "JWT_SECRET_KEY=replace-with-a-local-development-jwt-secret-32-plus-chars\n",
        encoding="utf-8",
    )
    values = iter(["pg-secret", "api-secret", "jwt-secret"])
    monkeypatch.setattr(bootstrap_env.secrets, "token_urlsafe", lambda _size: next(values))

    summary = bootstrap_env.bootstrap_profile_env(project_root=tmp_path)

    target = tmp_path / ".env.development"
    assert summary["created"] is True
    assert summary["generated_secrets"] == {
        "POSTGRES_PASSWORD": True,
        "API_KEY": True,
        "JWT_SECRET_KEY": True,
    }
    assert target.read_text(encoding="utf-8") == (
        "SIDAR_ENV=development\n"
        "POSTGRES_PASSWORD=pg-secret\n"
        "API_KEY=api-secret\n"
        "JWT_SECRET_KEY=jwt-secret\n"
    )


def test_bootstrap_profile_env_is_non_destructive_without_force(tmp_path: Path) -> None:
    (tmp_path / ".env.development.example").write_text("SIDAR_ENV=development\n", encoding="utf-8")
    target = tmp_path / ".env.development"
    target.write_text("SIDAR_ENV=development\nAPI_KEY=keep\n", encoding="utf-8")

    summary = bootstrap_env.bootstrap_profile_env(project_root=tmp_path)

    assert summary["created"] is False
    assert summary["reason"] == "already_exists"
    assert target.read_text(encoding="utf-8") == "SIDAR_ENV=development\nAPI_KEY=keep\n"


def test_bootstrap_profile_env_rejects_unsafe_profiles(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        bootstrap_env.bootstrap_profile_env("../production", project_root=tmp_path)
