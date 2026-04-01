from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_benchmark") is None,
    reason="pytest-benchmark eklentisi yüklü değil",
)


def test_small_sort_benchmark(benchmark):
    data = list(range(1000, 0, -1))

    def _sort():
        return sorted(data)

    result = benchmark(_sort)
    assert result[0] == 1
    assert result[-1] == 1000
