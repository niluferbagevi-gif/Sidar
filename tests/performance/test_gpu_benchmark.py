"""GPU inference performance benchmarks.

GPU tespit edilip RUN_GPU_STRESS=1 ayarlandığında çalışır.
İlk Ollama/LLM çağrısında model ağırlıkları VRAM'e yüklenir; bu yükleme
süresini istatistiklerden dışarıda tutmak için:
  1. _prepare_client() içinde manuel bir ısınma isteği atılır.
  2. benchmark.pedantic(warmup_rounds=N) ile ek ısınma turları çalıştırılır.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

pytest.importorskip("pytest_benchmark")

from core.llm_client import OllamaClient
from tests.helpers import make_test_config
import tests.smoke.test_gpu_inference as _gpu_smoke

# GPU donanımı yoksa tüm modül atlanır; bireysel testler ek olarak
# RUN_GPU_STRESS=1 denetimi yapar (ikinci katman).
pytestmark = pytest.mark.skipif(
    not _gpu_smoke.is_gpu_available(),
    reason="Sistemde veya WSL2 katmanında NVIDIA GPU bulunamadı, GPU benchmark atlanıyor.",
)

_MODEL: str = _gpu_smoke.MODEL_NAME
_TIMEOUT: int = _gpu_smoke._env_int("GPU_BENCH_TIMEOUT", 60, min_value=10, max_value=300)
_CONCURRENCY: int = _gpu_smoke._env_int("GPU_BENCH_CONCURRENCY", 4, min_value=1, max_value=16)
_WARMUP_ROUNDS: int = _gpu_smoke._env_int("GPU_BENCH_WARMUP_ROUNDS", 1, min_value=1, max_value=4)
_BENCH_ROUNDS: int = _gpu_smoke._env_int("GPU_BENCH_ROUNDS", 5, min_value=2, max_value=20)
_LATENCY_BUDGET_S: int = _gpu_smoke._env_int("GPU_BENCH_LATENCY_BUDGET", 30, min_value=5, max_value=120)


def _require_gpu_stress() -> None:
    if os.getenv("RUN_GPU_STRESS", "0") != "1":
        pytest.skip("GPU benchmark varsayılan olarak kapalıdır (RUN_GPU_STRESS=1 ayarlayın).")


def _make_ollama_client() -> OllamaClient:
    cfg = make_test_config(
        USE_GPU=True,
        OLLAMA_URL="http://localhost:11434",
        OLLAMA_TIMEOUT=_TIMEOUT,
        CODING_MODEL=_MODEL,
    )
    return OllamaClient(cfg)


async def _prepare_client(client: OllamaClient) -> None:
    """Ollama sağlık + model kontrolü yapar; ardından VRAM ısınması için tek istek atar.

    Bu istek benchmark ölçümlerine dahil edilmez.
    """
    if not await client.is_available():
        pytest.skip("Ollama servisine ulaşılamıyor.")
    if _MODEL not in await client.list_models():
        pytest.skip(f"{_MODEL} modeli yüklü değil.")
    await client.chat(
        messages=[{"role": "user", "content": "ısınma"}],
        model=_MODEL,
        json_mode=False,
    )


@pytest.mark.benchmark
@pytest.mark.gpu
@pytest.mark.gpu_stress
def test_gpu_single_inference_latency(benchmark) -> None:
    """Tek GPU inference isteğinin gecikme dağılımını ölçer.

    warmup_rounds ile VRAM model yükleme süresinin istatistikleri bozması engellenir;
    raporlanan mean/stddev yalnızca kararlı durumu (steady-state) yansıtır.

    Geçerli ortam değişkenleri:
      GPU_BENCH_WARMUP_ROUNDS  — pedantic warmup tur sayısı  (varsayılan: 1)
      GPU_BENCH_ROUNDS         — ölçüm tur sayısı            (varsayılan: 5)
      GPU_BENCH_LATENCY_BUDGET — maksimum kabul edilebilir gecikme (sn, varsayılan: 30)
    """
    _require_gpu_stress()
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    client = _make_ollama_client()
    asyncio.run(_prepare_client(client))

    prompt = "GPU benchmark: Türkiye'nin başkenti nedir? Tek cümle yanıt ver."

    def _single_call() -> str:
        return asyncio.run(
            client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=_MODEL,
                json_mode=False,
            )
        )

    result: str = benchmark.pedantic(
        _single_call,
        warmup_rounds=_WARMUP_ROUNDS,
        rounds=_BENCH_ROUNDS,
        iterations=1,
    )

    assert isinstance(result, str) and result.strip(), "Benchmark yanıtı boş döndü."
    mean_s: float = benchmark.stats["mean"]
    assert mean_s <= _LATENCY_BUDGET_S, (
        f"Ortalama gecikme bütçeyi aştı: {mean_s:.2f}s > {_LATENCY_BUDGET_S}s"
    )


@pytest.mark.benchmark
@pytest.mark.gpu
@pytest.mark.gpu_stress
def test_gpu_concurrent_throughput(benchmark) -> None:
    """Eşzamanlı GPU isteklerinin toplam tur süresini ölçer.

    Her benchmark turu _CONCURRENCY adet isteği aynı anda gönderir.
    warmup_rounds ile CUDA context başlatma gecikmesi dışlanır.

    Geçerli ortam değişkenleri:
      GPU_BENCH_CONCURRENCY    — eşzamanlı istek sayısı      (varsayılan: 4)
      GPU_BENCH_WARMUP_ROUNDS  — pedantic warmup tur sayısı  (varsayılan: 1)
      GPU_BENCH_ROUNDS         — ölçüm tur sayısı            (varsayılan: 5)
    """
    _require_gpu_stress()
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    client = _make_ollama_client()
    asyncio.run(_prepare_client(client))

    prompt = "Evet veya Hayır: GPU paralel inference çalışıyor mu?"

    async def _concurrent_round() -> list[str]:
        return list(
            await asyncio.gather(
                *[
                    client.chat(
                        messages=[{"role": "user", "content": prompt}],
                        model=_MODEL,
                        json_mode=False,
                    )
                    for _ in range(_CONCURRENCY)
                ]
            )
        )

    def _run() -> list[str]:
        return asyncio.run(_concurrent_round())

    results: list[str] = benchmark.pedantic(
        _run,
        warmup_rounds=_WARMUP_ROUNDS,
        rounds=_BENCH_ROUNDS,
        iterations=1,
    )

    assert len(results) == _CONCURRENCY, "Bazı eşzamanlı istekler yanıt döndürmedi."
    assert all(isinstance(r, str) and r.strip() for r in results), "Bazı yanıtlar boş döndü."


@pytest.mark.benchmark
@pytest.mark.gpu
@pytest.mark.gpu_stress
def test_gpu_vram_peak_under_load(benchmark) -> None:
    """Benchmark döngüsü sırasında GPU VRAM tepe değerini gözlemler ve doğrular.

    Ölçüm: eşzamanlı istek paketi gönderilirken nvidia-smi her 200 ms'de
    bir örneklenir; her tur için tepe değer kaydedilir.

    Geçerli ortam değişkenleri:
      GPU_BENCH_CONCURRENCY    — eşzamanlı istek sayısı      (varsayılan: 4)
      GPU_BENCH_WARMUP_ROUNDS  — pedantic warmup tur sayısı  (varsayılan: 1)
      GPU_BENCH_ROUNDS         — ölçüm tur sayısı            (varsayılan: 5)
    """
    _require_gpu_stress()
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")
    if _gpu_smoke._read_gpu_memory_used_mib() is None:
        pytest.skip("nvidia-smi VRAM ölçümü kullanılamıyor.")

    client = _make_ollama_client()
    asyncio.run(_prepare_client(client))

    prompt = "GPU VRAM stres testi. Kısa bir cümle yaz."
    observed_peaks: list[int] = []

    async def _workload_with_vram_sampling() -> int:
        stop = asyncio.Event()
        round_peak: list[int] = [0]

        async def _sample() -> None:
            while not stop.is_set():
                reading = _gpu_smoke._read_gpu_memory_used_mib()
                if reading is not None:
                    round_peak[0] = max(round_peak[0], reading)
                await asyncio.sleep(0.2)

        sampler = asyncio.create_task(_sample())
        try:
            await asyncio.gather(
                *[
                    client.chat(
                        messages=[{"role": "user", "content": prompt}],
                        model=_MODEL,
                        json_mode=False,
                    )
                    for _ in range(_CONCURRENCY)
                ]
            )
        finally:
            stop.set()
            await sampler

        return round_peak[0]

    def _run() -> int:
        peak = asyncio.run(_workload_with_vram_sampling())
        observed_peaks.append(peak)
        return peak

    benchmark.pedantic(
        _run,
        warmup_rounds=_WARMUP_ROUNDS,
        rounds=_BENCH_ROUNDS,
        iterations=1,
    )

    assert observed_peaks, "VRAM örneklemesi hiç tamamlanamadı."
    assert max(observed_peaks) > 0, (
        "Beklenen VRAM kullanımı (>0 MiB) gözlemlenmedi; "
        "GPU aktif olmayabilir veya nvidia-smi yanıt vermedi."
    )
