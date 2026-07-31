from __future__ import annotations

import runpy

import pytest

import core.doctor as doctor


def test_python_m_core_doctor_entrypoint_delegates_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the ``python -m core.doctor`` entry point without running real checks."""
    calls = []

    def fake_main() -> int:
        calls.append("main")
        return 7

    monkeypatch.setattr(doctor, "main", fake_main)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("core.doctor.__main__", run_name="__main__")

    assert exc_info.value.code == 7
    assert calls == ["main"]


def test_database_env_fix_runs_allowlisted_command_and_clears_editable_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in repair must not preserve dotenv URLs in the Doctor process."""
    check = doctor.DoctorCheck(
        "database_env",
        "fail",
        "drift",
        {
            "auto_fix": ("uv run python -m scripts.sync_database_passwords --remove-explicit-urls"),
            "database_url_source": "/repo/.env.development",
            "container_database_url_source": "",
        },
    )
    monkeypatch.setattr(doctor, "check_database_env", lambda: check)
    monkeypatch.setattr(doctor, "_run_command", lambda command, timeout: (0, "updated"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:secret@localhost/sidar")
    monkeypatch.setenv("SIDAR_CONTAINER_DATABASE_URL", "postgresql://sidar:secret@postgres/sidar")

    result = doctor._apply_database_env_fix()

    assert result["attempted"] is True
    assert result["success"] is True
    assert "DATABASE_URL" not in doctor.os.environ
    assert "SIDAR_CONTAINER_DATABASE_URL" in doctor.os.environ


def test_database_env_fix_does_not_run_when_check_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy environments remain read-only even when --fix is requested."""
    monkeypatch.setattr(
        doctor,
        "check_database_env",
        lambda: doctor.DoctorCheck("database_env", "pass", "ok", {}),
    )
    monkeypatch.setattr(
        doctor,
        "_run_command",
        lambda *_args, **_kwargs: pytest.fail("repair command should not run"),
    )

    result = doctor._apply_database_env_fix()

    assert result == {
        "check": "database_env",
        "before_status": "pass",
        "attempted": False,
        "success": True,
        "message": "database environment already healthy; no repair was needed",
    }
