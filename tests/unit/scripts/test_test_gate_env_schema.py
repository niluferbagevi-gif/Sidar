"""Tests for declarative quality-gate environment name validation."""

from __future__ import annotations

from scripts.test_gates import env_schema


def test_schema_accepts_declared_names_and_ignores_unrelated_environment() -> None:
    environ = {
        "BENCHMARK_COMPARE_FAIL": "mean:10%",
        "FRONTEND_E2E_NPM_SCRIPT": "test:e2e",
        "PATH": "/usr/bin",
        "GITHUB_RUN_ID": "123",
    }

    assert env_schema.unknown_test_gate_env(environ) == []


def test_schema_suggests_benchmark_typo_and_unknown_owned_name() -> None:
    findings = env_schema.unknown_test_gate_env(
        {
            "BENCMARK_COMPARE_FAIL": "mean:10%",
            "FRONTEND_E2E_UNKNOWN_SWITCH": "1",
        }
    )

    assert findings[0] == ("BENCMARK_COMPARE_FAIL", "BENCHMARK_COMPARE_FAIL")
    assert findings[1][0] == "FRONTEND_E2E_UNKNOWN_SWITCH"


def test_main_fails_fast_by_default_and_supports_explicit_warning_mode(monkeypatch, capsys) -> None:
    monkeypatch.setenv("BENCMARK_COMPARE_FAIL", "mean:10%")
    monkeypatch.delenv("TEST_ENV_SCHEMA_MODE", raising=False)

    assert env_schema.main() == 2
    assert "BENCHMARK_COMPARE_FAIL" in capsys.readouterr().err

    monkeypatch.setenv("TEST_ENV_SCHEMA_MODE", "warn")
    assert env_schema.main() == 0
    assert "Bilinmeyen" in capsys.readouterr().err
