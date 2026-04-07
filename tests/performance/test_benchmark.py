"""Performance-oriented sanity checks for deterministic utility paths."""

from __future__ import annotations

import pytest

from scripts.coverage_hotspots import FileCoverage, format_table

pytestmark = pytest.mark.benchmark
pytest.importorskip("pytest_benchmark")


def test_format_table_handles_small_dataset_quickly(benchmark) -> None:
    rows = [
        FileCoverage(path="core/rag.py", covered=10, missed=2),
        FileCoverage(path="core/db.py", covered=20, missed=1),
        FileCoverage(path="agent/registry.py", covered=30, missed=3),
    ]

    output = benchmark(format_table, rows)

    assert "| File | Coverage | Missed | Covered |" in output
    assert "core/rag.py" in output
