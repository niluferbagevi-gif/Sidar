from types import SimpleNamespace

import main as launcher


class _FakeConfig:
    DATABASE_URL = ""
    CONTAINER_DATABASE_URL = ""


def test_doctor_auto_fix_reloads_database_url_from_dotenv_chain(monkeypatch, tmp_path):
    base_env = tmp_path / ".env"
    advanced_env = tmp_path / ".env.advanced"
    development_env = tmp_path / ".env.development"
    base_env.write_text(
        "POSTGRES_PASSWORD=new-password-1234567890\n"
        "DATABASE_URL=postgresql://sidar:new-password-1234567890@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    advanced_env.write_text(
        "DATABASE_URL=postgresql://sidar:advanced@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    development_env.write_text("WEB_PORT=8765\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:stale@localhost:5432/sidar")
    fake_config = _FakeConfig
    monkeypatch.setattr(
        launcher,
        "config_module",
        SimpleNamespace(
            Config=fake_config,
            get_dotenv_load_report=lambda: [
                {"loaded": True, "path": str(base_env), "override": False},
                {"loaded": True, "path": str(advanced_env), "override": False},
                {"loaded": True, "path": str(development_env), "override": True},
            ],
            get_database_url=lambda: (
                "postgresql://sidar:new-password-1234567890@localhost:5432/sidar"
            ),
            get_container_database_url=lambda: "",
        ),
    )

    assert launcher._reload_database_env_from_loaded_dotenv_chain() is True

    assert (
        launcher.os.environ["DATABASE_URL"]
        == "postgresql://sidar:new-password-1234567890@localhost:5432/sidar"
    )
    assert launcher.os.environ["POSTGRES_PASSWORD"] == "new-password-1234567890"
    assert (
        fake_config.DATABASE_URL
        == "postgresql://sidar:new-password-1234567890@localhost:5432/sidar"
    )


def test_revalidate_doctor_check_flags_lost_env_key_regression(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "_reload_environment_after_auto_fix", lambda details: True)
    updated_check = SimpleNamespace(
        name="database_env",
        status="warn",
        message="DATABASE_URL is not set; database readiness cannot be fully verified",
        details={
            "database_url_set": False,
            "container_database_url_set": True,
            "postgres_password_set": True,
        },
    )

    result = launcher._revalidate_doctor_check_after_auto_fix(
        lambda: updated_check,
        {
            "database_url_set": True,
            "container_database_url_set": True,
            "postgres_password_set": True,
        },
    )

    captured = capsys.readouterr()
    assert result is updated_check
    assert "regresyon üretti" in captured.out
    assert "DATABASE_URL" in captured.out
    assert "kalan uyarıları inceleyin" not in captured.out
