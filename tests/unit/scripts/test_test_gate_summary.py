from __future__ import annotations

import json
import textwrap
from pathlib import Path

from scripts.test_gates import summary


def _summary_args(output_path: Path, junit_dir: Path) -> list[str]:
    return [
        str(output_path),
        "passed",  # smoke
        "passed",  # integration
        "skipped",  # e2e
        "passed",  # frontend_lint
        "passed",  # frontend_typecheck
        "passed",  # frontend_coverage
        "skipped",  # frontend_bundle_budget
        "passed",  # frontend_e2e
        "passed",  # benchmark
        "false",  # production_ready
        str(junit_dir),
        "true",  # backend_failed_tests_enabled
        "raw-module-fallback",
        "7",
        "9",
        "2",
        "3",
        "https://mirror.example/install_modules",
        "not_run",
        "partial_stage",
        "selected stage set does not cover the full production readiness gate",
        "partial",
        "true",
        "20",
        "development_local",
        "seeded_not_compared",
        "baseline",
        "",
        "",
        "0",
        "0",
        "1",
        "",
        "artifacts/benchmark/benchmark.json",
        "smoke",
        "test:e2e:smoke",
    ]


def test_summary_helper_writes_run_tests_payload_and_failed_backend_tests(tmp_path: Path) -> None:
    junit_dir = tmp_path / "pytest"
    junit_dir.mkdir()
    (junit_dir / "backend-unit.xml").write_text(
        textwrap.dedent(
            """\
            <testsuites>
              <testsuite name="pytest">
                <testcase classname="tests.unit.root.test_config" name="test_failure">
                  <failure message="failed">details</failure>
                </testcase>
                <testcase classname="tests.unit.root.test_config" name="test_error"
                          file="tests/unit/root/test_config.py">
                  <error message="errored">details</error>
                </testcase>
                <testcase classname="tests.unit.root.test_config" name="test_passed" />
              </testsuite>
            </testsuites>
            """
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "test-summary.json"

    assert summary.main(_summary_args(output_path, junit_dir)) == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["production_readiness_detail"] == {
        "status": "partial_stage",
        "reason": "selected stage set does not cover the full production readiness gate",
        "required_command": "make production-readiness",
        "equivalent_direct_command": (
            "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
            "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
        ),
        "validation_class": "partial",
        "release_blocking": True,
        "release_gate_exit_code": 20,
    }
    assert payload["benchmark_baseline"]["local_seed_command"] == (
        "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required bash run_tests.sh --stage all"
    )
    assert payload["backend_failed_tests"] == [
        "tests/unit/root/test_config.py::test_failure",
        "tests/unit/root/test_config.py::test_error",
    ]
    assert payload["installer"] == {
        "bootstrap_mode": "raw-module-fallback",
        "raw_fallback_modules_downloaded": 7,
        "remote_module_download_attempts": 9,
        "http_429_retries": 2,
        "remote_module_cache_hits": 3,
        "remote_module_base_url": "https://mirror.example/install_modules",
    }


def test_summary_helper_rejects_wrong_argument_count(tmp_path: Path, capsys) -> None:
    assert summary.main([str(tmp_path / "test-summary.json")]) == 2

    captured = capsys.readouterr()
    assert "expected 37 arguments" in captured.err


def test_summary_helper_skips_malicious_backend_junit_xml(tmp_path: Path) -> None:
    junit_dir = tmp_path / "pytest"
    junit_dir.mkdir()
    (junit_dir / "backend-unit.xml").write_text(
        textwrap.dedent(
            """\
            <!DOCTYPE testsuites [
              <!ENTITY xxe SYSTEM "file:///etc/passwd">
            ]>
            <testsuites>
              <testsuite name="pytest">
                <testcase classname="tests.unit.root.test_config" name="test_failure">
                  <failure message="&xxe;">details</failure>
                </testcase>
              </testsuite>
            </testsuites>
            """
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "test-summary.json"

    assert summary.main(_summary_args(output_path, junit_dir)) == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["backend_failed_tests"] == []
