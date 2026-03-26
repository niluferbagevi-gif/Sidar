from pathlib import Path


def test_pytest_ini_keeps_core_pytest_discovery_settings():
    src = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.pytest.ini_options]" in src
    assert 'testpaths = ["tests"]' in src
    assert 'python_files = ["test_*.py"]' in src


def test_run_tests_script_enforces_100pct_quality_gate_and_benchmarks():
    src = Path("run_tests.sh").read_text(encoding="utf-8")
    assert "--cov=." in src
    assert "COVERAGE_FAIL_UNDER" in src
    assert "100" in src
    assert "--cov=managers.security" in src
    assert "--cov=core.memory" in src
    assert "--cov=core.rag" in src
    assert "tests/test_benchmark.py" in src


def test_coveragerc_has_fail_under_100():
    src = Path(".coveragerc").read_text(encoding="utf-8")
    assert "[report]" in src
    assert "fail_under = 100" in src


def test_ci_has_explicit_coverage_quality_gate_step():
    src = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "Run targeted Swarm + Active Learning regression slice" in src
    assert "tests/test_swarm_orchestrator.py tests/test_active_learning.py" in src
    assert "Enforce coverage quality gate (100%)" in src
    assert "--cov-fail-under=100" in src


def test_environment_includes_benchmark_dependency():
    src = Path("environment.yml").read_text(encoding="utf-8")
    assert "python=3.11" in src
