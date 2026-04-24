"""GPU-odaklı smoke testleri."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time

import pytest

from core.llm_client import OllamaClient
from tests.helpers import make_test_config


# Fresh kurulumda installer'ın .env üzerinden hazırladığı model ile hizalı olsun.
# İhtiyaç halinde GPU_SMOKE_MODEL ile geçersiz kılınabilir.
MODEL_NAME = os.getenv("GPU_SMOKE_MODEL") or os.getenv("CODING_MODEL") or "qwen2.5-coder:3b"


def is_gpu_available() -> bool:
    if shutil.which("nvidia-smi") is not None:
        return True
    # WSL2 özel CUDA yolu kontrolü
    if os.path.exists("/usr/lib/wsl/lib/nvidia-smi"):
        return True
    return False


def _env_int(name: str, default: int, min_value: int = 1, max_value: int = 256) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, parsed))


def _read_gpu_memory_used_mib() -> int | None:
    """nvidia-smi ile toplam kullanılan GPU belleğini MiB cinsinden döndürür."""
    if not is_gpu_available():
        return None
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    values: list[int] = []
    for line in output.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            values.append(int(value))
        except ValueError:
            continue
    if not values:
        return None
    return sum(values)


def _read_gpu_memory_total_mib() -> int | None:
    """nvidia-smi ile toplam GPU belleğini MiB cinsinden döndürür."""
    if not is_gpu_available():
        return None
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    values: list[int] = []
    for line in output.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            values.append(int(value))
        except ValueError:
            continue
    if not values:
        return None
    return sum(values)


pytestmark = pytest.mark.skipif(
    not is_gpu_available(),
    reason="Sistemde veya WSL2 katmanında NVIDIA GPU bulunamadı, GPU smoke testi atlanıyor.",
)


@pytest.mark.gpu
@pytest.mark.asyncio
async def test_real_gpu_inference_smoke() -> None:
    """GPU mevcutsa, Ollama çağrısının GPU bayrağı ile temel yanıt döndürdüğünü doğrular."""
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    cfg = make_test_config(
        USE_GPU=True,
        OLLAMA_URL="http://localhost:11434",
        OLLAMA_TIMEOUT=30,
        CODING_MODEL=MODEL_NAME,
    )
    client = OllamaClient(cfg)

    is_available = await client.is_available()
    if not is_available:
        pytest.skip("Ollama servisine ulaşılamıyor.")

    installed_models = await client.list_models()
    if MODEL_NAME not in installed_models:
        pytest.skip(f"{MODEL_NAME} modeli yüklü değil.")

    response = await client.chat(
        messages=[{"role": "user", "content": "Sadece 'GPU Çalışıyor' yaz."}],
        model=MODEL_NAME,
        json_mode=False,
    )

    assert isinstance(response, str)
    assert len(response.strip()) > 0


@pytest.mark.gpu
@pytest.mark.gpu_stress
@pytest.mark.asyncio
async def test_real_gpu_inference_stress_vram_and_concurrency() -> None:
    """İsteğe bağlı GPU stres testi: eşzamanlı istek, gecikme ve bellek tepe değeri gözlemi."""
    if os.getenv("RUN_GPU_STRESS", "0") != "1":
        pytest.skip("GPU stres testi varsayılan olarak kapalıdır. (RUN_GPU_STRESS=1 ayarlayın).")
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    cfg = make_test_config(
        USE_GPU=True,
        OLLAMA_URL="http://localhost:11434",
        OLLAMA_TIMEOUT=_env_int("GPU_STRESS_TIMEOUT", 45, min_value=10, max_value=180),
        CODING_MODEL=MODEL_NAME,
    )
    client = OllamaClient(cfg)

    if not await client.is_available():
        pytest.skip("Ollama servisine ulaşılamıyor.")
    if MODEL_NAME not in await client.list_models():
        pytest.skip(f"{MODEL_NAME} modeli yüklü değil.")

    concurrency = _env_int("GPU_STRESS_CONCURRENCY", 4, min_value=1, max_value=16)
    rounds = _env_int("GPU_STRESS_ROUNDS", 3, min_value=1, max_value=20)
    prompt_repeat = _env_int("GPU_STRESS_PROMPT_REPEAT", 256, min_value=64, max_value=4096)
    latency_budget_seconds = _env_int("GPU_STRESS_LATENCY_BUDGET", 60, min_value=10, max_value=240)

    prompt = (
        "Aşağıdaki metni kısaca özetle ve sadece iki cümle döndür:\n"
        + ("GPU stres testi metni. " * prompt_repeat)
    )

    max_gpu_memory_mib = _read_gpu_memory_used_mib()
    stop_monitor = asyncio.Event()

    async def _gpu_monitor() -> None:
        nonlocal max_gpu_memory_mib
        while not stop_monitor.is_set():
            current = _read_gpu_memory_used_mib()
            if current is not None:
                if max_gpu_memory_mib is None:
                    max_gpu_memory_mib = current
                else:
                    max_gpu_memory_mib = max(max_gpu_memory_mib, current)
            await asyncio.sleep(0.2)

    async def _single_call() -> tuple[float, str]:
        started_at = time.perf_counter()
        response = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME,
            json_mode=False,
        )
        elapsed = time.perf_counter() - started_at
        return elapsed, response

    monitor_task = asyncio.create_task(_gpu_monitor())
    try:
        durations: list[float] = []
        for _ in range(rounds):
            results = await asyncio.gather(*[_single_call() for _ in range(concurrency)])
            durations.extend(duration for duration, _ in results)
            assert all(isinstance(response, str) and response.strip() for _, response in results)
    finally:
        stop_monitor.set()
        await monitor_task

    assert durations, "Stres testi sırasında en az bir istek üretilmelidir."
    assert max(durations) <= latency_budget_seconds
    if max_gpu_memory_mib is not None:
        assert max_gpu_memory_mib > 0
