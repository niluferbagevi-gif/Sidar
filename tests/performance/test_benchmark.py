"""Performance-oriented sanity checks for deterministic utility paths."""

from __future__ import annotations

import pytest

from scripts.coverage_hotspots import FileCoverage, format_table

pytestmark = pytest.mark.benchmark
pytest.importorskip("pytest_benchmark")


def test_format_table_handles_large_dataset_quickly(benchmark) -> None:
    rows = [
        FileCoverage(
            path=f"module_{index // 100}/file_{index:05d}.py",
            covered=(index % 120) + 1,
            missed=index % 7,
        )
        for index in range(10_000)
    ]

    output = benchmark(format_table, rows)

    assert "| File | Coverage | Missed | Covered |" in output
    assert "module_0/file_00000.py" in output
    assert "module_99/file_09999.py" in output
