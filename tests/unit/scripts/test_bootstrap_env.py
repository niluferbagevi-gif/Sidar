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
    assert summary["message"] == f"✅ Oluşturuldu: {target}"
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
    assert summary["message"] == f"ℹ️ Zaten mevcut: {target}"
    assert target.read_text(encoding="utf-8") == "SIDAR_ENV=development\nAPI_KEY=keep\n"


def test_bootstrap_profile_env_rejects_unsafe_profiles(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        bootstrap_env.bootstrap_profile_env("../production", project_root=tmp_path)


def test_bootstrap_profile_env_pins_sidar_env_to_selected_profile(tmp_path: Path) -> None:
    (tmp_path / ".env.qa.example").write_text(
        "API_KEY=local\nSIDAR_ENV=development\n", encoding="utf-8"
    )

    summary = bootstrap_env.bootstrap_profile_env(
        "qa", project_root=tmp_path, generate_secrets=False
    )

    assert summary["next_steps"][0] == "export SIDAR_ENV=qa"
    assert (tmp_path / ".env.qa").read_text(encoding="utf-8") == "API_KEY=local\nSIDAR_ENV=qa\n"


def test_render_env_template_adds_missing_sidar_env_for_isolation() -> None:
    rendered, generated = bootstrap_env.render_env_template(
        "API_KEY=local\n", profile="development", generate_secrets=False
    )

    assert generated == {}
    assert rendered == "API_KEY=local\nSIDAR_ENV=development\n"


def test_render_env_template_generates_postgres_password_for_generate_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap_env.secrets, "token_urlsafe", lambda _size: "generated-pg")

    rendered, generated = bootstrap_env.render_env_template(
        "SIDAR_ENV=test\nPOSTGRES_PASSWORD=__GENERATE__\n",
        profile="test",
    )

    assert generated["POSTGRES_PASSWORD"] is True
    assert "POSTGRES_PASSWORD=generated-pg" in rendered
    assert "__GENERATE__" not in rendered


def test_bootstrap_env_main_prints_feedback_to_stderr_and_json_to_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / ".env.development"

    def _fake_bootstrap_profile_env(*_args, **_kwargs):
        return {
            "profile": "development",
            "created": True,
            "reason": "created",
            "message": f"✅ Oluşturuldu: {target}",
            "target": str(target),
            "generated_secrets": {},
        }

    monkeypatch.setattr(bootstrap_env, "bootstrap_profile_env", _fake_bootstrap_profile_env)

    assert bootstrap_env.main(["--profile", "development"]) == 0

    captured = capsys.readouterr()
    assert "✅ Oluşturuldu:" in captured.err
    assert '"created": true' in captured.out
    assert str(target) in captured.out
