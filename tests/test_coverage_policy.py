from pathlib import Path


def test_pytest_ini_keeps_core_pytest_discovery_settings():
    src = Path("pytest.ini").read_text(encoding="utf-8")
    assert "[pytest]" in src
    assert "testpaths = tests" in src
    assert "python_files = test_*.py" in src


def test_run_tests_script_enforces_global_and_core_coverage_thresholds():
    src = Path("run_tests.sh").read_text(encoding="utf-8")
    assert "--cov=." in src
    assert "--cov-fail-under=70" in src
    assert "--cov=managers.security" in src
    assert "--cov=core.memory" in src
    assert "--cov=core.rag" in src
    assert "--cov-fail-under=80" in src
