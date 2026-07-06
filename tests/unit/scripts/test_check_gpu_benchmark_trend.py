from __future__ import annotations

import json

from scripts.ci import check_gpu_benchmark_trend as trend


def _benchmarks(*, ttft: float = 0.090, tps: float = 42.0, vram: float = 2048.0):
    runtime = {
        "ollama_model": "qwen2.5-coder:7b",
        "ollama_num_batch": 512,
        "ollama_num_ctx": 2048,
        "ollama_num_predict": 128,
        "ollama_keep_alive": "30m",
    }
    return [
        {
            "name": "test_gpu_time_to_first_token",
            "stats": {"mean": ttft},
            "extra_info": dict(runtime),
        },
        {
            "name": "test_gpu_tokens_per_second",
            "stats": {"mean": 1.0},
            "extra_info": {
                **runtime,
                "tokens_per_second": tps,
                "quantization_level": "Q4_K_M",
                "architecture": "qwen2",
            },
        },
        {
            "name": "test_gpu_vram_peak_under_load",
            "stats": {"mean": 1.0},
            "extra_info": {"vram_peak_mib": vram},
        },
        {
            "name": "test_gpu_oom_regression_under_load",
            "stats": {"mean": 1.0},
            "extra_info": {"oom_regression_failures": 0},
        },
    ]


def test_profile_key_separates_workload_shaping_ollama_options() -> None:
    profile = trend._profile_key(_benchmarks(), "driver-550")

    assert profile == (
        "Q4_K_M|qwen2|qwen2.5-coder:7b|batch=512|ctx=2048|predict=128|" "keep_alive=30m|driver-550"
    )


def test_regression_direction_does_not_alarm_on_improvements() -> None:
    assert trend._is_regression("ttft_ms", -25.0, 20.0) is False
    assert trend._is_regression("vram_peak_mib", -25.0, 20.0) is False
    assert trend._is_regression("tps", 25.0, 20.0) is False

    assert trend._is_regression("ttft_ms", 25.0, 20.0) is True
    assert trend._is_regression("vram_peak_mib", 25.0, 20.0) is True
    assert trend._is_regression("tps", -25.0, 20.0) is True
    assert trend._is_regression("oom_failures", 1.0, 20.0) is True


def test_main_records_new_profile_without_comparing_incompatible_history(
    monkeypatch, tmp_path, capsys
) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    history_path = tmp_path / "history.json"
    benchmark_path.write_text(json.dumps({"benchmarks": _benchmarks()}), encoding="utf-8")
    history_path.write_text(
        json.dumps({"profiles": {"old-profile": [{"metrics": {"ttft_ms": 1.0}}]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        trend.sys,
        "argv",
        [
            "check_gpu_benchmark_trend.py",
            str(benchmark_path),
            str(history_path),
            "7",
            "20",
            "driver-550",
        ],
    )

    assert trend.main() == 0
    assert "baseline oluşturuluyor" in capsys.readouterr().out

    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert len(history["profiles"]) == 2


def test_current_metrics_requires_oom_regression_benchmark() -> None:
    benchmarks = [item for item in _benchmarks() if item["name"] != "test_gpu_oom_regression_under_load"]

    try:
        trend._current_metrics(benchmarks)
    except RuntimeError as exc:
        assert "oom_failures" in str(exc)
    else:
        raise AssertionError("GPU OOM regression benchmark should be required for trend metrics")


def test_main_fails_when_current_oom_failures_are_non_zero(monkeypatch, tmp_path, capsys) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    history_path = tmp_path / "history.json"
    benchmarks = _benchmarks()
    for item in benchmarks:
        if item["name"] == "test_gpu_oom_regression_under_load":
            item["extra_info"]["oom_regression_failures"] = 1
    benchmark_path.write_text(json.dumps({"benchmarks": benchmarks}), encoding="utf-8")
    profile = trend._profile_key(benchmarks, "driver-550")
    history_path.write_text(
        json.dumps({"profiles": {profile: [{"metrics": {"oom_failures": 0.0}}]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        trend.sys,
        "argv",
        [
            "check_gpu_benchmark_trend.py",
            str(benchmark_path),
            str(history_path),
            "7",
            "20",
            "driver-550",
        ],
    )

    assert trend.main() == 1
    assert "GPU OOM regresyonu" in capsys.readouterr().out
