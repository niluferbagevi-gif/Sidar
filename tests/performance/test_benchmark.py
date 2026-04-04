def test_benchmark_placeholder(benchmark) -> None:
    benchmark(lambda: 1 + 1)
