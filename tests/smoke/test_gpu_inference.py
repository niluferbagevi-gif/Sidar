"""GPU-odaklı smoke testleri."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest

from core.config_env_helpers import get_int_env
from core.config_gpu_detect import HardwareInfo, resolve_adaptive_gpu_pool_size
from core.llm_client import OllamaClient
from tests.helpers import make_test_config

_logger = logging.getLogger(__name__)

# Fresh kurulumda installer'ın .env üzerinden hazırladığı model ile hizalı olsun.
# İhtiyaç halinde GPU_SMOKE_MODEL ile geçersiz kılınabilir.
MODEL_NAME = os.getenv("GPU_SMOKE_MODEL") or os.getenv("CODING_MODEL") or "qwen2.5-coder:7b"
_NVIDIA_SMI_TIMEOUT_S = 0.4
GPU_STRESS_DEFAULT_PROMPT_REPEAT = 128
GPU_STRESS_DEFAULT_NUM_BATCH = 2048
GPU_STRESS_DEFAULT_NUM_CTX = 4096


def _nvidia_smi_cmd() -> str | None:
    """Kullanılabilir nvidia-smi binary yolunu döndürür."""
    system_bin = shutil.which("nvidia-smi")
    if system_bin is not None:
        return system_bin
    wsl_bin = "/usr/lib/wsl/lib/nvidia-smi"
    if os.path.exists(wsl_bin):
        return wsl_bin
    return None


def is_gpu_available() -> bool:
    return _nvidia_smi_cmd() is not None


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
    nvidia_smi = _nvidia_smi_cmd()
    if nvidia_smi is None:
        return None
    try:
        output = subprocess.check_output(
            [
                nvidia_smi,
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
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
    nvidia_smi = _nvidia_smi_cmd()
    if nvidia_smi is None:
        return None
    try:
        output = subprocess.check_output(
            [
                nvidia_smi,
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
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


def _real_ollama_gpu_pool_size(cpu_count_hint: int) -> int:
    """Resolve the same adaptive GPU request pool size production would use here.

    Mirrors ``config.Config._ensure_hardware_info_loaded``'s call into
    ``resolve_adaptive_gpu_pool_size`` byte-for-byte (same helper, same
    env-override precedence via ``OLLAMA_GPU_REQUEST_POOL_SIZE``), driven by
    the VRAM this test already detects via ``nvidia-smi`` rather than a
    hand-picked constant. An 8 GB card resolves to 2, not the 4 the stress
    test's GPU_STRESS_CONCURRENCY default requests — production throttles
    concurrent GPU execution through this exact limiter, so mirroring it
    here is what makes "4 concurrent requests" a safe, representative
    client-level load instead of 4 uncapped simultaneous GPU generations.
    """
    vram_mib = _read_gpu_memory_total_mib() or 0
    info = HardwareInfo(
        has_cuda=True,
        gpu_name="detected",
        gpu_count=1,
        cpu_count=cpu_count_hint,
        gpu_vram_mb=vram_mib,
    )
    return resolve_adaptive_gpu_pool_size(info, get_int_env=get_int_env, logger=_logger)


def _torch_cuda_major(torch_module: Any) -> str | None:
    """Torch wheel'ının derlendiği CUDA major sürümünü döndürür."""
    cuda_version = getattr(getattr(torch_module, "version", SimpleNamespace()), "cuda", None)
    if not cuda_version:
        return None
    return str(cuda_version).split(".", maxsplit=1)[0]


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
def test_torch_cuda_major_is_supported_for_installed_driver() -> None:
    """CUDA 13 sürücülerde torch cu12/cu13 wheel uyumluluğunu fail-closed doğrular."""
    if "torch" in sys.modules:
        pytest.skip("torch zaten yüklü; çift kayıt önleniyor")

    torch = pytest.importorskip("torch")
    cuda_major = _torch_cuda_major(torch)
    assert cuda_major in {"12", "13"}, (
        "Torch CUDA wheel major sürümü desteklenen aralıkta olmalı; "
        f"torch.version.cuda={getattr(torch.version, 'cuda', None)!r}"
    )
    assert torch.cuda.is_available(), "NVIDIA GPU varken torch.cuda kullanılamıyor."

    device = torch.device("cuda")
    left = torch.eye(2, device=device)
    right = torch.ones((2, 2), device=device)
    result = torch.matmul(left, right)

    assert result.is_cuda
    assert result.shape == (2, 2)


@pytest.mark.gpu
@pytest.mark.gpu_stress
@pytest.mark.asyncio
async def test_real_gpu_inference_stress_vram_and_concurrency() -> None:
    """İsteğe bağlı GPU stres testi: eşzamanlı istek, gecikme ve bellek tepe değeri gözlemi."""
    if os.getenv("RUN_GPU_STRESS", "0") != "1":
        pytest.skip("GPU stres testi varsayılan olarak kapalıdır. (RUN_GPU_STRESS=1 ayarlayın).")
    if not shutil.which("ollama"):
        pytest.skip("Sistemde 'ollama' komutu bulunamadı.")

    # KRİTİK: make_test_config() bir MagicMock(spec_set=Config) döndürür; burada
    # açıkça set edilmeyen her attribute (ör. OLLAMA_GPU_REQUEST_POOL_SIZE) gerçek
    # Config().__init__()'in hardware-farkında resolve_adaptive_gpu_pool_size()
    # çağrısından hiç geçmez — MagicMock.__int__()'in varsayılan 1 döndürmesi
    # yüzünden core.llm_client._ollama_gpu_pool_size() sessizce 1'e düşer. Bu,
    # GPU_STRESS_CONCURRENCY kaç olursa olsun tüm istekleri fiilen seri hale
    # getirir — test hiçbir zaman gerçek eşzamanlı GPU yükünü sınamaz. Aynı
    # zamanda gerçek üretimin kendi 8 GB'lık kartlarda (per_gpu=2, bkz.
    # resolve_adaptive_gpu_pool_size) uyguladığı VRAM korumasını da atlar — sabit
    # concurrency=4'ü hiçbir throttle olmadan GPU'ya göndermek gerçek bir OOM
    # riski taşır. Üretimin kullanacağı gerçek değeri burada da hesaplayıp mock'a
    # açıkça geçiriyoruz; böylece "4 eşzamanlı istek" güvenli, temsili bir
    # istemci-seviyesi yük olur, GPU'ya giden fiili eşzamanlılık üretimdeki gibi
    # donanıma göre otomatik sınırlanır.
    gpu_pool_size = _real_ollama_gpu_pool_size(os.cpu_count() or 1)

    cfg = make_test_config(
        USE_GPU=True,
        OLLAMA_URL="http://localhost:11434",
        OLLAMA_TIMEOUT=_env_int("GPU_STRESS_TIMEOUT", 45, min_value=10, max_value=180),
        OLLAMA_NUM_BATCH=GPU_STRESS_DEFAULT_NUM_BATCH,
        OLLAMA_CODING_NUM_CTX=GPU_STRESS_DEFAULT_NUM_CTX,
        OLLAMA_GPU_REQUEST_POOL_SIZE=gpu_pool_size,
        CODING_MODEL=MODEL_NAME,
    )
    client = OllamaClient(cfg)

    if not await client.is_available():
        pytest.skip("Ollama servisine ulaşılamıyor.")
    if MODEL_NAME not in await client.list_models():
        pytest.skip(f"{MODEL_NAME} modeli yüklü değil.")

    concurrency = _env_int("GPU_STRESS_CONCURRENCY", 4, min_value=1, max_value=16)
    rounds = _env_int("GPU_STRESS_ROUNDS", 3, min_value=1, max_value=20)
    prompt_repeat = _env_int(
        "GPU_STRESS_PROMPT_REPEAT",
        GPU_STRESS_DEFAULT_PROMPT_REPEAT,
        min_value=64,
        max_value=4096,
    )
    latency_budget_seconds = _env_int("GPU_STRESS_LATENCY_BUDGET", 60, min_value=10, max_value=240)
    print(
        "GPU stress config: "
        f"prompt_repeat={prompt_repeat} (env GPU_STRESS_PROMPT_REPEAT), "
        f"num_batch={GPU_STRESS_DEFAULT_NUM_BATCH}, "
        f"num_ctx={GPU_STRESS_DEFAULT_NUM_CTX}, "
        f"concurrency={concurrency} istemci-seviyesi istek, rounds={rounds}, "
        f"gpu_request_pool_size={gpu_pool_size} (üretimin bu donanımda kullanacağı "
        "gerçek eşzamanlı GPU yürütme sınırı — bkz. resolve_adaptive_gpu_pool_size)"
    )

    prompt = "Aşağıdaki metni kısaca özetle ve sadece iki cümle döndür:\n" + (
        "GPU stres testi metni. " * prompt_repeat
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
