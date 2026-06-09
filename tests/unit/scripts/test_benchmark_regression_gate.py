from __future__ import annotations

import os
import subprocess
from pathlib import Path

import scripts.ci.verify_benchmark_regression_gate as gate


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["pytest"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_pytest_builds_isolated_benchmark_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, cwd, env, text, capture_output, check):  # noqa: ANN001
        captured.update(
            command=command,
            cwd=cwd,
            env=env,
            text=text,
            capture_output=capture_output,
            check=check,
        )
        return _completed(0, stdout="ok")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    result = gate._run_pytest(tmp_path, "0.123", "--benchmark-save=baseline")

    assert result.returncode == 0
    assert captured["cwd"] == tmp_path
    assert captured["text"] is True
    assert captured["capture_output"] is True
    assert captured["check"] is False
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:4] == [gate.sys.executable, "-m", "pytest", "-q"]
    assert "--benchmark-disable-gc" in command
    assert "--benchmark-warmup=off" in command
    assert "--benchmark-save=baseline" in command
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["SIDAR_SYNTHETIC_BENCH_DELAY_SECONDS"] == "0.123"
    assert set(os.environ).issubset(env)


def test_write_synthetic_benchmark_uses_environment_driven_delay(tmp_path: Path) -> None:
    test_file = gate._write_synthetic_benchmark(tmp_path)

    content = test_file.read_text(encoding="utf-8")
    assert test_file.name == "test_synthetic_benchmark_regression.py"
    assert 'os.environ["SIDAR_SYNTHETIC_BENCH_DELAY_SECONDS"]' in content
    assert "benchmark.pedantic(workload, rounds=5, iterations=1, warmup_rounds=1)" in content


def test_main_succeeds_only_when_compare_fail_reports_regression(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    class TempDir:
        def __enter__(self) -> str:
            return str(tmp_path)

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    def fake_tempdir(prefix: str) -> TempDir:
        assert prefix == "sidar-benchmark-gate-"
        return TempDir()

    def fake_run_pytest(workdir: Path, delay_seconds: str, *extra_args: str):  # noqa: ANN001
        calls.append((delay_seconds, extra_args))
        if delay_seconds == gate._FAST_DELAY_SECONDS:
            baseline_dir = workdir / ".benchmarks" / "Linux-CPython-3.11-64bit"
            baseline_dir.mkdir(parents=True)
            (baseline_dir / "0001_baseline.json").write_text("{}", encoding="utf-8")
            return _completed(0, stdout="baseline ok")
        return _completed(1, stderr="Performance has regressed.")

    monkeypatch.setattr(gate.tempfile, "TemporaryDirectory", fake_tempdir)
    monkeypatch.setattr(gate, "_run_pytest", fake_run_pytest)

    assert gate.main() == 0
    assert calls[0] == (gate._FAST_DELAY_SECONDS, ("--benchmark-save=baseline",))
    assert calls[1][0] == gate._SLOW_DELAY_SECONDS
    assert str(tmp_path / ".benchmarks" / "Linux-CPython-3.11-64bit" / "0001_baseline.json") in calls[1][1][0]
    assert calls[1][1][1] == f"--benchmark-compare-fail={gate._COMPARE_FAIL_THRESHOLD}"


def test_main_returns_baseline_failure_code(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gate.tempfile, "TemporaryDirectory", lambda prefix: _StaticTempDir(tmp_path))
    monkeypatch.setattr(gate, "_run_pytest", lambda *args: _completed(3, stderr="baseline failed"))

    assert gate.main() == 3


def test_main_fails_when_baseline_file_is_missing(monkeypatch, tmp_path: Path) -> None:
    def fake_run_pytest(*args):  # noqa: ANN001
        return _completed(0, stdout="baseline ok")

    monkeypatch.setattr(gate.tempfile, "TemporaryDirectory", lambda prefix: _StaticTempDir(tmp_path))
    monkeypatch.setattr(gate, "_run_pytest", fake_run_pytest)

    assert gate.main() == 1


def test_main_fails_when_regression_run_passes(monkeypatch, tmp_path: Path) -> None:
    call_count = 0

    def fake_run_pytest(workdir: Path, delay_seconds: str, *extra_args: str):  # noqa: ANN001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            baseline_dir = workdir / ".benchmarks" / "Linux-CPython-3.11-64bit"
            baseline_dir.mkdir(parents=True)
            (baseline_dir / "0001_baseline.json").write_text("{}", encoding="utf-8")
        return _completed(0, stdout="passed")

    monkeypatch.setattr(gate.tempfile, "TemporaryDirectory", lambda prefix: _StaticTempDir(tmp_path))
    monkeypatch.setattr(gate, "_run_pytest", fake_run_pytest)

    assert gate.main() == 1


def test_main_fails_when_nonzero_run_is_not_regression_alarm(monkeypatch, tmp_path: Path) -> None:
    call_count = 0

    def fake_run_pytest(workdir: Path, delay_seconds: str, *extra_args: str):  # noqa: ANN001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            baseline_dir = workdir / ".benchmarks" / "Linux-CPython-3.11-64bit"
            baseline_dir.mkdir(parents=True)
            (baseline_dir / "0001_baseline.json").write_text("{}", encoding="utf-8")
            return _completed(0, stdout="baseline ok")
        return _completed(4, stderr="usage error")

    monkeypatch.setattr(gate.tempfile, "TemporaryDirectory", lambda prefix: _StaticTempDir(tmp_path))
    monkeypatch.setattr(gate, "_run_pytest", fake_run_pytest)

    assert gate.main() == 1


class _StaticTempDir:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> str:
        return str(self.path)

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None
