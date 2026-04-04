from __future__ import annotations

import pytest

pytest.importorskip("pytest_benchmark")

from core.ci_remediation import _extract_suspected_targets


@pytest.mark.benchmark
def test_extract_suspected_targets_benchmark(benchmark) -> None:
    text = "Failure in core/db.py and managers/github_manager.py with AssertionError"
    result = benchmark(lambda: _extract_suspected_targets(text))
    assert result == ["core/db.py", "managers/github_manager.py"]
