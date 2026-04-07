"""Performance-oriented sanity checks for deterministic utility paths."""

from __future__ import annotations

import pytest

from scripts.coverage_hotspots import FileCoverage, format_table

pytestmark = pytest.mark.benchmark


@pytest.fixture()
def sample_rows() -> list[FileCoverage]:
    return [
        FileCoverage(path="core/rag.py", covered=10, missed=2),
        FileCoverage(path="core/db.py", covered=20, missed=1),
        FileCoverage(path="agent/registry.py", covered=30, missed=3),
    ]


def test_format_table_handles_small_dataset_quickly(benchmark, sample_rows: list[FileCoverage]) -> None:
    """format_table over a tiny payload should be statistically fast (measured by pytest-benchmark)."""
    output = benchmark(format_table, sample_rows)

    assert "| File | Coverage | Missed | Covered |" in output
    assert "core/rag.py" in output


def test_format_table_output_correctness(sample_rows: list[FileCoverage]) -> None:
    """Verify format_table produces correct output independent of timing."""
    output = format_table(sample_rows)

    assert "| File | Coverage | Missed | Covered |" in output
    assert "core/rag.py" in output
    assert "core/db.py" in output
    assert "agent/registry.py" in output
