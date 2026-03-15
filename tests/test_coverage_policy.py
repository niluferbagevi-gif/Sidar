from pathlib import Path


def test_pytest_ini_keeps_core_pytest_discovery_settings():
    src = Path("pytest.ini").read_text(encoding="utf-8")
    assert "[pytest]" in src
    assert "testpaths = tests" in src
    assert "python_files = test_*.py" in src


def test_run_tests_script_enforces_999pct_quality_gate_and_benchmarks():
    src = Path("run_tests.sh").read_text(encoding="utf-8")
    assert "--cov=." in src
    assert "COVERAGE_FAIL_UNDER" in src
    assert "99.9" in src
    assert "--cov=managers.security" in src
    assert "--cov=core.memory" in src
    assert "--cov=core.rag" in src
    assert "tests/test_benchmark.py" in src


def test_coveragerc_has_fail_under_999():
    src = Path(".coveragerc").read_text(encoding="utf-8")
    assert "[report]" in src
    assert "fail_under = 99.9" in src


def test_ci_has_explicit_coverage_quality_gate_step():
    src = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "Enforce coverage quality gate (99.9%)" in src
    assert "--cov-fail-under=99.9" in src


def test_environment_includes_benchmark_dependency():
    src = Path("environment.yml").read_text(encoding="utf-8")
    assert "pytest-benchmark" in src