from scripts.ci.check_benchmark_regressions import find_regressions


def _artifact(entries: dict[str, float], *, workload_class: str = "") -> dict[str, object]:
    return {
        "benchmarks": [
            {
                "fullname": n,
                "stats": {"mean": m},
                "extra_info": {"workload_class": workload_class},
            }
            for n, m in entries.items()
        ]
    }


def test_io_workload_uses_noise_tolerant_limit() -> None:
    name = "test_multi_user_session_message_workload_scales_with_concurrency[postgresql]"
    assert (
        find_regressions(
            _artifact({name: 0.01}), _artifact({name: 0.0124}), default_limit=10, io_limit=35
        )
        == []
    )


def test_cpu_workload_keeps_strict_limit() -> None:
    assert find_regressions(
        _artifact({"test_cpu": 0.01}),
        _artifact({"test_cpu": 0.0124}),
        default_limit=10,
        io_limit=35,
    ) == ["test_cpu: mean %24.00 arttı (eşik %10)"]


def test_large_io_regression_still_fails_closed() -> None:
    name = "test_multi_user_session_message_workload_scales_with_concurrency[sqlite]"
    assert find_regressions(
        _artifact({name: 1}), _artifact({name: 1.5}), default_limit=10, io_limit=35
    ) == [f"{name}: mean %50.00 arttı (eşik %35)"]


def test_explicit_workload_metadata_does_not_depend_on_test_name() -> None:
    assert (
        find_regressions(
            _artifact({"renamed_database_benchmark": 1}),
            _artifact({"renamed_database_benchmark": 1.24}, workload_class="io_bound"),
            default_limit=10,
            io_limit=35,
        )
        == []
    )
