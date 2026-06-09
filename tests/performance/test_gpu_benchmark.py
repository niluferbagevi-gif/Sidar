"""GPU inference performance benchmarks.

GPU tespit edilip RUN_GPU_STRESS=1 ayarlandığında çalışır.
İlk Ollama/LLM çağrısında model ağırlıkları VRAM'e yüklenir; bu yükleme
süresini istatistiklerden dışarıda tutmak için:
  1. _prepare_client() içinde manuel bir ısınma isteği atılır.
  2. benchmark.pedantic(warmup_rounds=N) ile ek ısınma turları çalıştırılır.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import shutil
import time

import httpx
import pytest

pytest.importorskip("pytest_benchmark")

import tests.smoke.test_gpu_inference as _gpu_smoke
from core.llm_client import OllamaClient
from tests.helpers import make_test_config

# GPU donanımı yoksa tüm modül atlanır; bireysel testler ek olarak
# RUN_GPU_STRESS=1 denetimi yapar (ikinci katman).
pytestmark = pytest.mark.skipif(
    not _gpu_smoke.is_gpu_available(),
    reason="Sistemde veya WSL2 katmanında NVIDIA GPU bulunamadı, GPU benchmark atlanıyor.",
)

_MODEL: str = _gpu_smoke.MODEL_NAME
_TIMEOUT: int = _gpu_smoke._env_int("GPU_BENCH_TIMEOUT", 60, min_value=10, max_value=300)
_CONCURRENCY: int = _gpu_smoke._env_int("GPU_BENCH_CONCURRENCY", 4, min_value=1, max_value=16)
_WARMUP_ROUNDS: int = _gpu_smoke._env_int("GPU_BENCH_WARMUP_ROUNDS", 8, min_value=1, max_value=12)
_BENCH_ROUNDS: int = _gpu_smoke._env_int("GPU_BENCH_ROUNDS", 20, min_value=20, max_value=50)
_LATENCY_BUDGET_S: int = _gpu_smoke._env_int(
    "GPU_BENCH_LATENCY_BUDGET", 30, min_value=5, max_value=120
)
_MIN_TOKENS_PER_SEC: float = float(os.getenv("GPU_BENCH_MIN_TOKENS_PER_SEC", "10.0"))
_OLLAMA_BASE_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434").removesuffix("/api")
_OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m").strip()
_PREWARM_REQUESTS: int = _gpu_smoke._env_int(
    "GPU_BENCH_PREWARM_REQUESTS", 3, min_value=1, max_value=12
)
_PREWARM_CONCURRENCY: int = _gpu_smoke._env_int(
    "GPU_BENCH_PREWARM_CONCURRENCY",
    2,
    min_value=1,
    max_value=8,
)
_NUM_BATCH: int = _gpu_smoke._env_int("GPU_BENCH_NUM_BATCH", 512, min_value=1, max_value=4096)
_NUM_PREDICT: int = _gpu_smoke._env_int("GPU_BENCH_NUM_PREDICT", 128, min_value=8, max_value=1024)
_NUM_CTX: int = _gpu_smoke._env_int("GPU_BENCH_NUM_CTX", 2048, min_value=256, max_value=32768)
_TPS_BENCH_ROUNDS: int = _gpu_smoke._env_int("GPU_BENCH_TPS_ROUNDS", 20, min_value=20, max_value=50)
_GPU_BENCHMARK_PROFILE: str = os.getenv("RUN_GPU_BENCHMARKS", "smoke").strip().lower()
if _GPU_BENCHMARK_PROFILE not in {"smoke", "full"}:
    _GPU_BENCHMARK_PROFILE = "smoke"
_CONCURRENT_WARMUP_ROUNDS: int = _gpu_smoke._env_int(
    "GPU_BENCH_CONCURRENT_WARMUP_ROUNDS",
    1 if _GPU_BENCHMARK_PROFILE == "smoke" else _WARMUP_ROUNDS,
    min_value=1,
    max_value=8,
)
_CONCURRENT_BENCH_ROUNDS: int = _gpu_smoke._env_int(
    "GPU_BENCH_CONCURRENT_ROUNDS",
    # Smoke profili 10 → 15: önceki ölçümde StdDev 64 ms / IQR 94 ms ile rounds=10
    # istatistiksel olarak zayıftı; 15 tur ~%50 daha fazla örneklem ile regresyon
    # tespit hassasiyetini artırır. Pipeline'a eklediği ek süre tek koşum başına
    # ~5 round × ~7 s/round ≈ 35 s; smoke profilinde kabul edilebilir.
    15 if _GPU_BENCHMARK_PROFILE == "smoke" else _BENCH_ROUNDS,
    min_value=10,
    max_value=50,
)


def _env_float(name: str, default: float, *, min_value: float, max_value: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


_TTFT_BUDGET_S: float = _env_float(
    "GPU_BENCH_TTFT_BUDGET",
    10.0,
    min_value=0.05,
    max_value=60.0,
)
_MAX_VRAM_UTILIZATION: float = _env_float(
    "GPU_BENCH_MAX_VRAM_UTILIZATION",
    0.90,
    min_value=0.50,
    max_value=0.98,
)
_VRAM_SAMPLE_INTERVAL_S: float = _env_float(
    "GPU_BENCH_VRAM_SAMPLE_INTERVAL",
    0.05,
    min_value=0.01,
    max_value=0.05,
)


def _require_gpu_stress() -> None:
    if os.getenv("RUN_GPU_STRESS", "0") != "1":
        pytest.skip("GPU benchmark varsayılan olarak kapalıdır (RUN_GPU_STRESS=1 ayarlayın).")


def _ollama_num_parallel() -> int:
    """Ollama'nın eşzamanlı request işleme kapasitesi (server env üzerinden).

    Varsayılanı benchmark concurrency değeriyle hizalarız; böylece `.env` veya
    docker-compose varsayılanı kullanılmadığında testler gereksiz yere skip olmaz.
    """
    return _gpu_smoke._env_int(
        "OLLAMA_NUM_PARALLEL",
        _CONCURRENCY,
        min_value=1,
        max_value=64,
    )


def _make_ollama_client() -> OllamaClient:
    cfg = make_test_config(
        USE_GPU=True,
        OLLAMA_URL="http://localhost:11434",
        OLLAMA_TIMEOUT=_TIMEOUT,
        CODING_MODEL=_MODEL,
        OLLAMA_KEEP_ALIVE=_OLLAMA_KEEP_ALIVE,
    )
    return OllamaClient(cfg)


def _http_timeout() -> httpx.Timeout:
    return httpx.Timeout(_TIMEOUT, connect=10.0)


async def _prepare_client(client: OllamaClient, http: httpx.AsyncClient) -> None:
    """Ollama sağlık + model kontrolü yapar; ardından VRAM ısınması için tek istek atar.

    Bu istek benchmark ölçümlerine dahil edilmez.
    """
    if not await client.is_available():
        pytest.skip("Ollama servisine ulaşılamıyor.")
    if _MODEL not in await client.list_models():
        pytest.skip(f"{_MODEL} modeli yüklü değil.")
    warmup_prompt = "ısınma"
    await client.chat(
        messages=[{"role": "user", "content": warmup_prompt}], model=_MODEL, json_mode=False
    )

    # Tail latency'yi azaltmak için ek ön ısınma:
    # - ardışık çağrılar: model/runtime kod-path'i stabilize edilir
    # - eşzamanlı çağrılar: GPU scheduler + KV-cache tahsisi önceden tetiklenir
    for idx in range(_PREWARM_REQUESTS):
        await client.chat(
            messages=[{"role": "user", "content": f"{warmup_prompt}-{idx}"}],
            model=_MODEL,
            json_mode=False,
        )

    for _ in range(_PREWARM_CONCURRENCY):
        await asyncio.gather(
            *[
                _chat_content(f"{warmup_prompt}-concurrent-{idx}", http)
                for idx in range(_PREWARM_CONCURRENCY)
            ]
        )


def _apply_keep_alive(payload: dict[str, object]) -> dict[str, object]:
    if _OLLAMA_KEEP_ALIVE:
        payload["keep_alive"] = _OLLAMA_KEEP_ALIVE
    return payload


def _workload_shape_signature() -> str:
    """Tek satırlık, deterministik workload shape imzası.

    Trend karşılaştırıcı bu imzadan iki koşum arasında shape değişimini
    (örn. num_ctx 2048→4096) ayırt edebilir; aksi halde trend grafiğinde
    farklı profilleri aynı seriye sıkıştırırız.
    """
    return (
        f"concurrency={_CONCURRENCY}"
        f"|num_batch={_NUM_BATCH}"
        f"|num_ctx={_NUM_CTX}"
        f"|num_predict={_NUM_PREDICT}"
    )


def _record_runtime_options(benchmark) -> None:
    """Attach workload-shaping Ollama options so trend history compares like-for-like runs."""
    benchmark.extra_info["ollama_model"] = _MODEL
    benchmark.extra_info["ollama_keep_alive"] = _OLLAMA_KEEP_ALIVE or "disabled"
    benchmark.extra_info["ollama_num_batch"] = _NUM_BATCH
    benchmark.extra_info["ollama_num_predict"] = _NUM_PREDICT
    benchmark.extra_info["ollama_num_ctx"] = _NUM_CTX
    benchmark.extra_info["workload_shape"] = _workload_shape_signature()


def _record_vram_workload_shape(benchmark) -> None:
    """VRAM testine özgü shape parametrelerini ek olarak kaydet.

    `vram_workload_shape` anahtarı, VRAM tepe ölçümünü etkileyen tüm
    boyut/zamanlama parametrelerini tek satırda bir araya getirir. Trend
    karşılaştırıcı bu imzayı görerek shape değişikliklerini regresyon olarak
    yanlış raporlamaz. Üretim batch boyutu değiştiğinde bu env değerlerini
    güncellemek (örn. `GPU_BENCH_CONCURRENCY=8` veya `GPU_BENCH_NUM_PREDICT=256`)
    burada da otomatik yansır.
    """
    benchmark.extra_info["vram_workload_shape"] = (
        f"{_workload_shape_signature()}"
        f"|vram_sample_interval_s={_VRAM_SAMPLE_INTERVAL_S}"
        f"|vram_rounds={_BENCH_ROUNDS}"
        f"|vram_warmup_rounds={_WARMUP_ROUNDS}"
    )


def _ollama_options() -> dict[str, int | float]:
    """GPU throughput dalgalanmasını azaltmak için tek noktadan Ollama opsiyonları."""
    return {
        "temperature": 0.0,
        "num_gpu": -1,
        # num_batch, Ollama tarafında mikro-batch davranışını etkiler.
        # Düşük değerler throughput'u düşürüp tail latency dalgalanmasını artırabilir.
        "num_batch": _NUM_BATCH,
        # Üretim uzunluğunu sınırlamak benchmark toplam süresini (wall-clock) düşürür.
        "num_predict": _NUM_PREDICT,
        # Çok uzun context penceresi VRAM baskısını artırabilir; kontrollü tutuyoruz.
        "num_ctx": _NUM_CTX,
    }


async def _chat_content(prompt: str, http: httpx.AsyncClient) -> str:
    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": _ollama_options(),
    }
    resp = await http.post(f"{_OLLAMA_BASE_URL}/api/chat", json=_apply_keep_alive(payload))
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("message", {}).get("content", ""))


async def _model_runtime_profile(http: httpx.AsyncClient) -> dict[str, str]:
    """Model runtime profilini döndürür (quantization / attention mimarisi ipuçları)."""
    payload = {"name": _MODEL}
    resp = await http.post(f"{_OLLAMA_BASE_URL}/api/show", json=payload)
    resp.raise_for_status()
    data = resp.json()

    details = data.get("details") or {}
    model_info = data.get("model_info") or {}
    return {
        "quantization_level": str(details.get("quantization_level", "") or "unknown"),
        "architecture": str(model_info.get("general.architecture", "") or "unknown"),
    }


@dataclasses.dataclass(slots=True)
class _InferenceMetrics:
    """Ollama non-streaming yanıtından çekilen ham üretim metrikleri."""

    content: str
    eval_count: int  # üretilen token sayısı
    eval_duration_ns: int  # token üretim süresi (nanosaniye)

    @property
    def tokens_per_second(self) -> float:
        if self.eval_duration_ns == 0:
            return 0.0
        return self.eval_count / (self.eval_duration_ns / 1_000_000_000)


async def _chat_with_metrics(prompt: str, http: httpx.AsyncClient) -> _InferenceMetrics:
    """Ollama /api/chat (non-streaming) çağrısı; eval_count + eval_duration döndürür.

    OllamaClient yerine doğrudan httpx kullanılır; böylece API yanıt gövdesindeki
    ham metrik alanları kaybolmadan okunur.
    """
    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": _ollama_options(),
    }
    resp = await http.post(f"{_OLLAMA_BASE_URL}/api/chat", json=_apply_keep_alive(payload))
    resp.raise_for_status()
    data = resp.json()
    return _InferenceMetrics(
        content=data.get("message", {}).get("content", ""),
        eval_count=int(data.get("eval_count") or 0),
        eval_duration_ns=int(data.get("eval_duration") or 0),
    )


async def _first_token_seconds(prompt: str, http: httpx.AsyncClient) -> float:
    """Streaming mod ile İlk Token'a Kadar Geçen Süre'yi (TTFT) saniye cinsinden ölçer.

    İlk token alındıktan hemen sonra bağlantı kapatılır; bu sayede benchmark
    fonksiyonunun ölçülen çalışma süresi ≈ TTFT olur.
    """
    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "options": _ollama_options(),
    }
    started_at = time.perf_counter()
    async with http.stream(
        "POST", f"{_OLLAMA_BASE_URL}/api/chat", json=_apply_keep_alive(payload)
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            try:
                body = json.loads(line)
            except json.JSONDecodeError:
                continue
            if body.get("message", {}).get("content", ""):
                # İlk token geldi — bağlantıyı kapat ve TTFT'yi döndür.
                return time.perf_counter() - started_at
    return 0.0


@pytest.mark.benchmark(group="gpu", warmup=True, min_rounds=10)
@pytest.mark.gpu
@pytest.mark.gpu_stress
def test_gpu_single_inference_latency(benchmark) -> None:
    """Tek GPU inference isteğinin gecikme dağılımını ölçer.

    warmup_rounds ile VRAM model yükleme süresinin istatistikleri bozması engellenir;
    raporlanan mean/stddev yalnızca kararlı durumu (steady-state) yansıtır.

    Geçerli ortam değişkenleri:
      GPU_BENCH_WARMUP_ROUNDS  — pedantic warmup tur sayısı  (varsayılan: 8)
      GPU_BENCH_ROUNDS         — ölçüm tur sayısı            (varsayılan: 20)
      GPU_BENCH_LATENCY_BUDGET — maksimum kabul edilebilir gecikme (sn, varsayılan: 30)
    """
    _require_gpu_stress()
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    client = _make_ollama_client()
    loop = asyncio.new_event_loop()
    http = httpx.AsyncClient(timeout=_http_timeout())
    try:
        loop.run_until_complete(_prepare_client(client, http))

        prompt = "GPU benchmark: Türkiye'nin başkenti nedir? Tek cümle yanıt ver."

        def _single_call() -> str:
            return loop.run_until_complete(_chat_content(prompt, http))

        result: str = benchmark.pedantic(
            _single_call,
            warmup_rounds=_WARMUP_ROUNDS,
            rounds=_BENCH_ROUNDS,
            iterations=1,
        )
    finally:
        loop.run_until_complete(http.aclose())
        loop.close()

    assert isinstance(result, str) and result.strip(), "Benchmark yanıtı boş döndü."
    mean_s: float = benchmark.stats["mean"]
    assert (
        mean_s <= _LATENCY_BUDGET_S
    ), f"Ortalama gecikme bütçeyi aştı: {mean_s:.2f}s > {_LATENCY_BUDGET_S}s"
    stddev_s: float = benchmark.stats["stddev"]
    iqr_s: float = float(benchmark.stats.get("iqr", 0.0))
    _record_runtime_options(benchmark)
    benchmark.extra_info["latency_stddev_ms"] = round(stddev_s * 1000, 3)
    benchmark.extra_info["latency_iqr_ms"] = round(iqr_s * 1000, 3)
    if mean_s > 0:
        cv = stddev_s / mean_s
        benchmark.extra_info["latency_cv_percent"] = round(cv * 100, 3)
        assert cv < 0.30, f"Inference varyansı çok yüksek: CV={cv:.2%}"


@pytest.mark.benchmark(group="gpu", warmup=True, min_rounds=10)
@pytest.mark.gpu
@pytest.mark.gpu_stress
def test_gpu_concurrent_throughput(benchmark) -> None:
    """Eşzamanlı GPU isteklerinin toplam tur süresini ölçer.

    Her benchmark turu _CONCURRENCY adet isteği aynı anda gönderir.
    warmup_rounds ile CUDA context başlatma gecikmesi dışlanır.

    Geçerli ortam değişkenleri:
      GPU_BENCH_CONCURRENCY    — eşzamanlı istek sayısı      (varsayılan: 4)
      RUN_GPU_BENCHMARKS       — smoke|full profil seçimi    (varsayılan: smoke)
      GPU_BENCH_CONCURRENT_WARMUP_ROUNDS — eşzamanlı test ısınma turu (smoke: 1, full: 8)
      GPU_BENCH_CONCURRENT_ROUNDS — eşzamanlı test ölçüm turu (smoke: 10, full: 20)
      OLLAMA_NUM_PARALLEL      — Ollama paralel request limiti (öneri: >= GPU_BENCH_CONCURRENCY)
    """
    _require_gpu_stress()
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")
    num_parallel = _ollama_num_parallel()
    benchmark.extra_info["ollama_num_parallel"] = num_parallel
    _record_runtime_options(benchmark)
    benchmark.extra_info["benchmark_concurrency"] = _CONCURRENCY
    benchmark.extra_info["gpu_benchmark_profile"] = _GPU_BENCHMARK_PROFILE
    benchmark.extra_info["concurrent_warmup_rounds"] = _CONCURRENT_WARMUP_ROUNDS
    benchmark.extra_info["concurrent_benchmark_rounds"] = _CONCURRENT_BENCH_ROUNDS
    if _CONCURRENCY > 0:
        benchmark.extra_info["parallel_saturation_percent"] = round(
            (num_parallel / _CONCURRENCY) * 100, 3
        )
    if num_parallel < _CONCURRENCY:
        pytest.skip(
            "Gerçek paralellik için OLLAMA_NUM_PARALLEL değeri yetersiz: "
            f"{num_parallel} < {_CONCURRENCY}. "
            f"En az OLLAMA_NUM_PARALLEL={_CONCURRENCY} önerilir."
        )

    client = _make_ollama_client()
    loop = asyncio.new_event_loop()
    http = httpx.AsyncClient(timeout=_http_timeout())
    try:
        loop.run_until_complete(_prepare_client(client, http))

        prompt = "Evet veya Hayır: GPU paralel inference çalışıyor mu?"

        async def _concurrent_round() -> list[str]:
            return list(
                await asyncio.gather(*[_chat_content(prompt, http) for _ in range(_CONCURRENCY)])
            )

        def _run() -> list[str]:
            return loop.run_until_complete(_concurrent_round())

        results: list[str] = benchmark.pedantic(
            _run,
            warmup_rounds=_CONCURRENT_WARMUP_ROUNDS,
            rounds=_CONCURRENT_BENCH_ROUNDS,
            iterations=1,
        )
    finally:
        loop.run_until_complete(http.aclose())
        loop.close()

    assert len(results) == _CONCURRENCY, "Bazı eşzamanlı istekler yanıt döndürmedi."
    assert all(isinstance(r, str) and r.strip() for r in results), "Bazı yanıtlar boş döndü."


@pytest.mark.benchmark(group="gpu", warmup=True, min_rounds=10)
@pytest.mark.gpu
@pytest.mark.gpu_stress
def test_gpu_vram_peak_under_load(benchmark) -> None:
    """Benchmark döngüsü sırasında GPU VRAM tepe değerini gözlemler ve doğrular.

    Ölçüm: eşzamanlı istek paketi gönderilirken nvidia-smi varsayılan olarak her 50 ms'de
    bir örneklenir; her tur için tepe değer kaydedilir.

    Geçerli ortam değişkenleri:
      GPU_BENCH_CONCURRENCY    — eşzamanlı istek sayısı      (varsayılan: 4)
      GPU_BENCH_WARMUP_ROUNDS  — pedantic warmup tur sayısı  (varsayılan: 8)
      GPU_BENCH_ROUNDS         — ölçüm tur sayısı            (varsayılan: 20)
      GPU_BENCH_VRAM_SAMPLE_INTERVAL — VRAM örnekleme aralığı (sn, varsayılan: 0.05)
    """
    _require_gpu_stress()
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")
    num_parallel = _ollama_num_parallel()
    if num_parallel < _CONCURRENCY:
        pytest.skip(
            "VRAM yük testinde gerçek paralellik için OLLAMA_NUM_PARALLEL yetersiz: "
            f"{num_parallel} < {_CONCURRENCY}."
        )
    if _gpu_smoke._read_gpu_memory_used_mib() is None:
        pytest.skip("nvidia-smi VRAM ölçümü kullanılamıyor.")

    _record_runtime_options(benchmark)
    _record_vram_workload_shape(benchmark)

    client = _make_ollama_client()
    loop = asyncio.new_event_loop()
    http = httpx.AsyncClient(timeout=_http_timeout())
    observed_peaks: list[int] = []
    try:
        loop.run_until_complete(_prepare_client(client, http))

        prompt = "GPU VRAM stres testi. Kısa bir cümle yaz."

        async def _workload_with_vram_sampling() -> int:
            stop = asyncio.Event()
            round_peak: list[int] = [0]

            async def _sample() -> None:
                while not stop.is_set():
                    reading = _gpu_smoke._read_gpu_memory_used_mib()
                    if reading is not None:
                        round_peak[0] = max(round_peak[0], reading)
                    await asyncio.sleep(_VRAM_SAMPLE_INTERVAL_S)

            sampler = asyncio.create_task(_sample())
            try:
                await asyncio.gather(*[_chat_content(prompt, http) for _ in range(_CONCURRENCY)])
            finally:
                stop.set()
                await sampler

            return round_peak[0]

        def _run() -> int:
            peak = loop.run_until_complete(_workload_with_vram_sampling())
            observed_peaks.append(peak)
            return peak

        benchmark.pedantic(
            _run,
            warmup_rounds=_WARMUP_ROUNDS,
            rounds=_BENCH_ROUNDS,
            iterations=1,
        )
    finally:
        loop.run_until_complete(http.aclose())
        loop.close()

    assert observed_peaks, "VRAM örneklemesi hiç tamamlanamadı."
    assert max(observed_peaks) > 0, (
        "Beklenen VRAM kullanımı (>0 MiB) gözlemlenmedi; "
        "GPU aktif olmayabilir veya nvidia-smi yanıt vermedi."
    )
    total_vram = _gpu_smoke._read_gpu_memory_total_mib()
    if total_vram is not None:
        utilization_limit_mib = int(total_vram * _MAX_VRAM_UTILIZATION)
        assert max(observed_peaks) <= utilization_limit_mib, (
            "VRAM tepe kullanımı limiti aştı: "
            f"{max(observed_peaks)} MiB > {utilization_limit_mib} MiB "
            f"({_MAX_VRAM_UTILIZATION:.0%} of {total_vram} MiB)."
        )
    benchmark.extra_info["vram_peak_mib"] = int(max(observed_peaks))
    benchmark.extra_info["vram_peak_mean_mib"] = round(sum(observed_peaks) / len(observed_peaks), 3)


@pytest.mark.benchmark(group="gpu", warmup=True, min_rounds=10)
@pytest.mark.gpu
@pytest.mark.gpu_stress
def test_gpu_tokens_per_second(benchmark) -> None:
    """Token/Saniye üretim hızını Ollama'nın eval_count/eval_duration metadatasından ölçer.

    Ollama non-streaming yanıt gövdesindeki iki alan kullanılır:
      eval_count       — model tarafından üretilen token sayısı
      eval_duration    — üretim için harcanan süre (nanosaniye)

    tokens_per_second = eval_count / (eval_duration / 1_000_000_000)

    Bu değer GPU'nun gerçek üretim hızını yansıtır; toplam gecikmeyi değil.

    Geçerli ortam değişkenleri:
      GPU_BENCH_MIN_TOKENS_PER_SEC — minimum kabul edilebilir tok/sn (varsayılan: 10.0)
      GPU_BENCH_WARMUP_ROUNDS      — pedantic warmup tur sayısı    (varsayılan: 8)
      GPU_BENCH_TPS_ROUNDS         — ölçüm tur sayısı              (varsayılan: 20)
      GPU_BENCH_NUM_PREDICT        — yanıt token üst sınırı         (varsayılan: 128)
      GPU_BENCH_NUM_CTX            — context window                 (varsayılan: 2048)
    """
    _require_gpu_stress()
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    client = _make_ollama_client()
    loop = asyncio.new_event_loop()
    http = httpx.AsyncClient(timeout=_http_timeout())
    try:
        loop.run_until_complete(_prepare_client(client, http))

        runtime_profile = loop.run_until_complete(_model_runtime_profile(http))
        _record_runtime_options(benchmark)
        benchmark.extra_info["quantization_level"] = runtime_profile["quantization_level"]
        benchmark.extra_info["architecture"] = runtime_profile["architecture"]

        prompt = "GPU benchmark: Linked list nedir? En fazla iki cümlede açıkla."
        observed: list[_InferenceMetrics] = []

        def _run() -> _InferenceMetrics:
            metrics = loop.run_until_complete(_chat_with_metrics(prompt, http))
            observed.append(metrics)
            return metrics

        result: _InferenceMetrics = benchmark.pedantic(
            _run,
            warmup_rounds=_WARMUP_ROUNDS,
            rounds=_TPS_BENCH_ROUNDS,
            iterations=1,
        )
    finally:
        loop.run_until_complete(http.aclose())
        loop.close()

    assert result.content.strip(), "Benchmark yanıtı boş döndü."
    assert result.eval_count > 0, (
        "Ollama eval_count=0: token sayısı alınamadı. " "Model veya Ollama sürümünü kontrol edin."
    )
    tps = result.tokens_per_second
    benchmark.extra_info["tokens_per_second"] = round(tps, 3)
    tps_stddev_s: float = float(benchmark.stats.get("stddev", 0.0))
    tps_iqr_s: float = float(benchmark.stats.get("iqr", 0.0))
    tps_mean_s: float = float(benchmark.stats.get("mean", 0.0))
    benchmark.extra_info["tps_stddev_ms"] = round(tps_stddev_s * 1000, 3)
    benchmark.extra_info["tps_iqr_ms"] = round(tps_iqr_s * 1000, 3)
    if tps_mean_s > 0:
        benchmark.extra_info["tps_cv_percent"] = round((tps_stddev_s / tps_mean_s) * 100, 3)
    assert (
        tps >= _MIN_TOKENS_PER_SEC
    ), f"Token/sn bütçesinin altında: {tps:.1f} tok/s < {_MIN_TOKENS_PER_SEC:.1f} tok/s"


@pytest.mark.benchmark(group="gpu", warmup=True, min_rounds=20)
@pytest.mark.gpu
@pytest.mark.gpu_stress
def test_gpu_time_to_first_token(benchmark) -> None:
    """İlk Token'a Kadar Geçen Süre'yi (TTFT) ölçer.

    Streaming mod açılır; ilk içerikli chunk gelir gelmez bağlantı kapatılır.
    Bu sayede benchmark.pedantic'in ölçtüğü fonksiyon süresi ≈ TTFT olur.

    TTFT, toplam gecikmeyi değil, modelin "cevaplamaya başlama" hızını gösterir
    ve etkileşimli uygulamalar için en kritik GPU performans metriğidir.

    Geçerli ortam değişkenleri:
      GPU_BENCH_TTFT_BUDGET    — maksimum kabul edilebilir TTFT (sn, varsayılan: 10.0)
      GPU_BENCH_WARMUP_ROUNDS  — pedantic warmup tur sayısı     (varsayılan: 8)
      GPU_BENCH_ROUNDS         — ölçüm tur sayısı               (varsayılan: 20)
    """
    _require_gpu_stress()
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    client = _make_ollama_client()
    loop = asyncio.new_event_loop()
    http = httpx.AsyncClient(timeout=_http_timeout())
    try:
        loop.run_until_complete(_prepare_client(client, http))

        # Kısa, tek kelimelik yanıt beklenen prompt: TTFT ölçümü tam yanıt
        # süresinden bağımsız olmalıdır.
        prompt = "GPU TTFT benchmark: Evet mi Hayır mı? Tek kelime yaz."
        ttft_readings: list[float] = []

        def _run() -> float:
            ttft = loop.run_until_complete(_first_token_seconds(prompt, http))
            ttft_readings.append(ttft)
            return ttft

        result: float = benchmark.pedantic(
            _run,
            warmup_rounds=_WARMUP_ROUNDS,
            rounds=_BENCH_ROUNDS,
            iterations=1,
        )
    finally:
        loop.run_until_complete(http.aclose())
        loop.close()

    assert result > 0.0, "TTFT sıfır döndü; streaming yanıt alınamadı."
    mean_ttft: float = benchmark.stats["mean"]
    _record_runtime_options(benchmark)
    benchmark.extra_info["ttft_mean_ms"] = round(mean_ttft * 1000, 3)
    assert (
        mean_ttft <= _TTFT_BUDGET_S
    ), f"Ortalama TTFT bütçeyi aştı: {mean_ttft:.3f}s > {_TTFT_BUDGET_S}s"


def test_runtime_options_metadata_records_workload_shape() -> None:
    """Trend geçmişinin tuning değişikliklerini ayrı profil olarak izleyebilmesini doğrula."""

    class _BenchmarkStub:
        extra_info: dict[str, object] = {}

    benchmark = _BenchmarkStub()
    _record_runtime_options(benchmark)

    assert benchmark.extra_info == {
        "ollama_model": _MODEL,
        "ollama_keep_alive": _OLLAMA_KEEP_ALIVE or "disabled",
        "ollama_num_batch": _NUM_BATCH,
        "ollama_num_predict": _NUM_PREDICT,
        "ollama_num_ctx": _NUM_CTX,
        "workload_shape": _workload_shape_signature(),
    }


def test_vram_workload_shape_metadata_includes_vram_specific_dimensions() -> None:
    """VRAM testinin shape imzasının sampling ve tur sayısını da kapsamasını doğrula.

    Trend karşılaştırıcı VRAM tepe ölçümünü etkileyen tüm boyut/zamanlama
    parametrelerini bu tek anahtardan okur; aksi halde sample interval veya
    rounds değişimi gözden kaçar ve regresyon yanlış sınıflandırılır.
    """

    class _BenchmarkStub:
        extra_info: dict[str, object] = {}

    benchmark = _BenchmarkStub()
    _record_vram_workload_shape(benchmark)

    signature = benchmark.extra_info["vram_workload_shape"]
    assert isinstance(signature, str)
    # Genel shape (_workload_shape_signature) içeriği bu imzanın baş kısmı olmalı.
    assert signature.startswith(_workload_shape_signature())
    # VRAM'e özgü ek parametreler imzada görünmeli.
    assert "vram_sample_interval_s=" in signature
    assert f"vram_rounds={_BENCH_ROUNDS}" in signature
    assert f"vram_warmup_rounds={_WARMUP_ROUNDS}" in signature
