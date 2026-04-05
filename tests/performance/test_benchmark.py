"""Performance-oriented sanity checks for deterministic utility paths."""

from __future__ import annotations

import time

from scripts.coverage_hotspots import FileCoverage, format_table


def test_format_table_handles_small_dataset_quickly() -> None:
    rows = [
        FileCoverage(path="core/rag.py", covered=10, missed=2),
        FileCoverage(path="core/db.py", covered=20, missed=1),
        FileCoverage(path="agent/registry.py", covered=30, missed=3),
    ]

    start = time.perf_counter()
    for _ in range(2000):
        output = format_table(rows)
    elapsed = time.perf_counter() - start

    assert "| File | Coverage | Missed | Covered |" in output
    assert "core/rag.py" in output
    # Deterministic utility path for a tiny payload should stay comfortably fast.
    assert elapsed < 1.0
