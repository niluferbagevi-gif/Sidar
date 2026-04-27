from __future__ import annotations

import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _find_benchmark(benchmarks: list[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    needle_l = needle.lower()
    for item in benchmarks:
        name = str(item.get("name", "")).lower()
        fullname = str(item.get("fullname", "")).lower()
        if needle_l in name or needle_l in fullname:
            return item
    return None


def _current_metrics(benchmarks: list[dict[str, Any]]) -> dict[str, float]:
    ttft = _find_benchmark(benchmarks, "test_gpu_time_to_first_token")
    tps = _find_benchmark(benchmarks, "test_gpu_tokens_per_second")
    vram = _find_benchmark(benchmarks, "test_gpu_vram_peak_under_load")
    if not ttft or not tps or not vram:
        missing = [
            name
            for name, item in {
                "ttft": ttft,
                "tps": tps,
                "vram": vram,
            }.items()
            if item is None
        ]
        raise RuntimeError(f"Gerekli GPU benchmark girdileri bulunamadı: {', '.join(missing)}")

    ttft_ms = float(ttft.get("stats", {}).get("mean", 0.0)) * 1000.0
    tps_extra = tps.get("extra_info", {}).get("tokens_per_second")
    tps_value = float(tps_extra) if tps_extra is not None else 0.0
    vram_peak = float(vram.get("extra_info", {}).get("vram_peak_mib", 0.0))
    return {
        "ttft_ms": round(ttft_ms, 3),
        "tps": round(tps_value, 3),
        "vram_peak_mib": round(vram_peak, 3),
    }


def _profile_key(benchmarks: list[dict[str, Any]], fallback: str) -> str:
    tps = _find_benchmark(benchmarks, "test_gpu_tokens_per_second")
    extra = {} if tps is None else (tps.get("extra_info", {}) or {})
    quantization = str(extra.get("quantization_level", "unknown")).strip() or "unknown"
    architecture = str(extra.get("architecture", "unknown")).strip() or "unknown"
    return f"{quantization}|{architecture}|{fallback}"


def main() -> int:
    if len(sys.argv) != 6:
        print(
            "Usage: python scripts/ci/check_gpu_benchmark_trend.py "
            "<benchmark.json> <history.json> <window> <threshold_percent> <profile_hint>"
        )
        return 2

    bench_path = Path(sys.argv[1])
    history_path = Path(sys.argv[2])
    window = max(1, int(sys.argv[3]))
    threshold_percent = max(0.1, float(sys.argv[4]))
    profile_hint = sys.argv[5]

    payload = _load_json(bench_path, default={})
    benchmarks = payload.get("benchmarks", [])
    if not isinstance(benchmarks, list) or not benchmarks:
        print("Benchmark verisi boş.")
        return 2

    metrics = _current_metrics(benchmarks)
    profile = _profile_key(benchmarks, profile_hint)

    history = _load_json(history_path, default={"profiles": {}})
    profiles = history.setdefault("profiles", {})
    entries = profiles.setdefault(profile, [])
    recent_entries = entries[-window:]

    failed = False
    if recent_entries:
        for metric_name, current in metrics.items():
            med = statistics.median(
                [
                    float(item["metrics"][metric_name])
                    for item in recent_entries
                    if metric_name in item["metrics"]
                ]
            )
            if med <= 0:
                continue
            pct_delta = ((current - med) / med) * 100.0
            print(
                f"[gpu-trend] profile={profile} metric={metric_name} current={current:.3f} "
                f"median{window}={med:.3f} delta={pct_delta:+.2f}%"
            )
            if abs(pct_delta) > threshold_percent:
                print(
                    f"[ALARM] {metric_name} geçmiş {window} koşu medyanına göre "
                    f"{pct_delta:+.2f}% sapma gösterdi (eşik ±{threshold_percent:.2f}%)."
                )
                failed = True
    else:
        print(f"[gpu-trend] profile={profile} için geçmiş veri yok, baseline oluşturuluyor.")

    entries.append(
        {
            "ts": datetime.now(UTC).isoformat(),
            "metrics": metrics,
        }
    )
    profiles[profile] = entries[-200:]

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
