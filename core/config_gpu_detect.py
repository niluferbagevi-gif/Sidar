from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict


class GpuMemoryBudget(TypedDict):
    llm: float
    rag: float
    gpu: float
    total: float
    original_total: float
    normalized: bool


@dataclass
class HardwareInfo:
    has_cuda: bool
    gpu_name: str
    gpu_count: int = 0
    cpu_count: int = 0
    cuda_version: str = "N/A"
    driver_version: str = "N/A"
    gpu_vram_mb: int = 0


def is_wsl2() -> bool:
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except Exception:
        return False


def normalize_gpu_memory_fractions(
    llm_fraction: float,
    rag_fraction: float,
    *,
    target_total: float = 0.8,
    min_fraction: float = 0.05,
) -> GpuMemoryBudget:
    llm = float(llm_fraction or 0.0)
    rag = float(rag_fraction or 0.0)
    total = llm + rag
    safe_total = float(target_total)
    floor = max(0.0, float(min_fraction))
    if total <= 0:
        return {
            "llm": round(safe_total / 2, 4),
            "rag": round(safe_total / 2, 4),
            "gpu": round(safe_total, 4),
            "total": round(safe_total, 4),
            "original_total": round(total, 4),
            "normalized": True,
        }
    if total <= 1.0:
        return {
            "llm": round(llm, 4),
            "rag": round(rag, 4),
            "gpu": round(total, 4),
            "total": round(total, 4),
            "original_total": round(total, 4),
            "normalized": False,
        }
    scale = safe_total / total
    normalized_llm = max(floor, llm * scale)
    normalized_rag = max(floor, rag * scale)
    normalized_total = normalized_llm + normalized_rag
    if normalized_total > safe_total:
        second_scale = safe_total / normalized_total
        normalized_llm *= second_scale
        normalized_rag *= second_scale
    return {
        "llm": round(normalized_llm, 4),
        "rag": round(normalized_rag, 4),
        "gpu": round(safe_total, 4),
        "total": round(normalized_llm + normalized_rag, 4),
        "original_total": round(total, 4),
        "normalized": True,
    }


def resolve_adaptive_gpu_pool_size(
    info: HardwareInfo,
    *,
    get_int_env: Any,
    logger: Any,
    env_key: str = "OLLAMA_GPU_REQUEST_POOL_SIZE",
) -> int:
    """Resolve a safe local-LLM GPU request pool size from hardware and optional env."""
    explicit = int(get_int_env(env_key, 0) or 0)
    if explicit > 0:
        return max(1, min(explicit, 16))
    if not info.has_cuda or info.gpu_count <= 0:
        return 1

    vram_mb = max(0, int(getattr(info, "gpu_vram_mb", 0) or 0))
    if vram_mb >= 24 * 1024:
        per_gpu = 4
    elif vram_mb >= 16 * 1024:
        per_gpu = 3
    elif vram_mb >= 8 * 1024:
        per_gpu = 2
    else:
        per_gpu = 1

    cpu_cap = max(1, int(getattr(info, "cpu_count", 1) or 1) // 2)
    pool_size = max(1, min(per_gpu * max(1, int(info.gpu_count)), cpu_cap, 8))
    logger.info(
        "🎮 Adaptive GPU request pool size: %d (gpu_count=%d, vram_mb=%d, cpu_cap=%d)",
        pool_size,
        info.gpu_count,
        vram_mb,
        cpu_cap,
    )
    return pool_size


def detect_gpu(
    *, get_bool_env: Any, get_int_env: Any, get_float_env: Any, logger: Any
) -> HardwareInfo:
    info = HardwareInfo(has_cuda=False, gpu_name="N/A")
    try:
        import multiprocessing

        info.cpu_count = multiprocessing.cpu_count()
    except Exception:
        info.cpu_count = 1
    wsl2 = is_wsl2()
    if wsl2:
        logger.info("ℹ️  WSL2 ortamı tespit edildi — CUDA, Windows sürücüsü üzerinden erişilecek.")
    if not get_bool_env("USE_GPU", True):
        logger.info("ℹ️  GPU kullanımı .env ile devre dışı bırakıldı.")
        info.gpu_name = "Devre Dışı (Kullanıcı)"
        return info
    try:
        import torch

        if torch.cuda.is_available():
            info.has_cuda = True
            info.gpu_count = torch.cuda.device_count()
            info.gpu_name = torch.cuda.get_device_name(0)
            info.cuda_version = torch.version.cuda or "N/A"
            try:
                props = torch.cuda.get_device_properties(0)
                info.gpu_vram_mb = int(getattr(props, "total_memory", 0) or 0) // (1024 * 1024)
            except Exception:
                info.gpu_vram_mb = 0
            logger.info(
                "🚀 GPU Hızlandırma Aktif: %s  (%d GPU tespit edildi, CUDA %s)",
                info.gpu_name,
                info.gpu_count,
                info.cuda_version,
            )
        else:
            info.gpu_name = "CUDA Bulunamadı"
    except ImportError:
        logger.warning("⚠️  PyTorch kurulu değil; GPU kontrolü atlanıyor.")
        info.gpu_name = "PyTorch Yok"
    except Exception as exc:
        logger.warning("⚠️  Donanım kontrolü hatası: %s", exc)
        info.gpu_name = "Tespit Edilemedi"
    return info
