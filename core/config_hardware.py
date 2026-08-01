"""Hardware detection and VRAM policy helpers for the Config facade."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any

from core.config_gpu_detect import HardwareInfo


def is_wsl2() -> bool:
    """Return whether the Linux kernel release identifies a WSL2 runtime."""
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except Exception:
        return False


def apply_vram_memory_fraction(
    info: HardwareInfo,
    *,
    is_wsl2_runtime: Callable[[], bool],
    stable_cuda_wheel_tags: tuple[str, ...],
    recommended_cuda_install_command: str,
    get_float_env: Callable[[str, float], float],
    get_bool_env: Callable[[str, bool], bool],
    get_int_env: Callable[[str, int], int],
    normalize_gpu_memory_fractions: Callable[[float, float], dict[str, Any]],
    log_first_load_info: Callable[..., None],
    logger: Any,
    environ: MutableMapping[str, str],
) -> None:
    """Apply the configured VRAM fraction after a shared GPU probe succeeds."""
    if not info.has_cuda:
        if is_wsl2_runtime() and info.gpu_name == "CUDA Bulunamadı":
            logger.warning(
                "⚠️  WSL2 — CUDA bulunamadı. Kontrol: Windows NVIDIA sürücüsü güncel mi? "
                "PyTorch resmi selector ile uyumlu CUDA wheel kurulumu yapıldı mı? "
                "Desteklenen stabil wheel etiketleri: %s. Örnek: %s",
                ", ".join(stable_cuda_wheel_tags),
                recommended_cuda_install_command,
            )
        return

    try:
        import torch
    except Exception as exc:
        logger.debug("VRAM fraksiyon ayarı için torch yeniden açılamadı: %s", exc)
        return

    legacy_frac = get_float_env("GPU_MEMORY_FRACTION", 0.8)
    llm_frac = get_float_env("LLM_GPU_MEMORY_FRACTION", legacy_frac)
    rag_frac = get_float_env(
        "RAG_GPU_MEMORY_FRACTION", max(0.1, min(0.5, legacy_frac * 0.35))
    )
    if "LLM_GPU_MEMORY_FRACTION" in environ or "RAG_GPU_MEMORY_FRACTION" in environ:
        vram_budget = normalize_gpu_memory_fractions(llm_frac, rag_frac)
        frac = float(vram_budget["gpu"] if vram_budget["normalized"] else vram_budget["total"])
        if vram_budget["normalized"]:
            logger.warning(
                "LLM/RAG VRAM fraksiyonları toplamı %.2f; donanım probu %.2f toplamına "
                "normalize edilmiş bütçeyi uyguluyor (LLM=%.2f, RAG=%.2f).",
                vram_budget["original_total"],
                vram_budget["gpu"],
                vram_budget["llm"],
                vram_budget["rag"],
            )
    else:
        frac = legacy_frac
    if not 0.1 <= frac < 1.0:
        logger.warning(
            "GPU bellek fraksiyonu=%.2f geçersiz aralık (0.1–0.99 bekleniyor, 1.0 "
            "dahil değil) — varsayılan 0.8 kullanılıyor.",
            frac,
        )
        frac = 0.8
    multi_gpu = get_bool_env("MULTI_GPU", False)
    target_device = max(0, get_int_env("GPU_DEVICE", 0))
    try:
        if multi_gpu and info.gpu_count > 1:
            for device_idx in range(info.gpu_count):
                torch.cuda.set_per_process_memory_fraction(frac, device=device_idx)
            log_first_load_info(
                "🔧 VRAM fraksiyonu tüm GPU'lara uygulandı: %.0f%% (%d cihaz)",
                frac * 100,
                info.gpu_count,
            )
        else:
            if info.gpu_count > 0:
                target_device = min(target_device, info.gpu_count - 1)
            torch.cuda.set_per_process_memory_fraction(frac, device=target_device)
            log_first_load_info(
                "🔧 VRAM fraksiyonu ayarlandı: %.0f%% (cuda:%d)", frac * 100, target_device
            )
    except Exception as exc:
        logger.debug("VRAM fraksiyon ayarı atlandı: %s", exc)


def check_hardware(
    *,
    gpu_detect_module: Any,
    is_wsl2_runtime: Callable[[], bool],
    apply_vram_policy: Callable[[HardwareInfo], None],
    get_bool_env: Callable[[str, bool], bool],
    get_int_env: Callable[[str, int], int],
    get_float_env: Callable[[str, float], float],
    logger: Any,
) -> HardwareInfo:
    """Detect GPU/CPU hardware, apply VRAM policy, and enrich optional NVML data."""
    original_is_wsl2 = gpu_detect_module.is_wsl2
    gpu_detect_module.is_wsl2 = is_wsl2_runtime
    try:
        info: HardwareInfo = gpu_detect_module.detect_gpu(
            get_bool_env=get_bool_env,
            get_int_env=get_int_env,
            get_float_env=get_float_env,
            logger=logger,
        )
    finally:
        gpu_detect_module.is_wsl2 = original_is_wsl2

    apply_vram_policy(info)
    try:
        import pynvml

        pynvml.nvmlInit()
        info.driver_version = pynvml.nvmlSystemGetDriverVersion()
        pynvml.nvmlShutdown()
    except Exception as exc:
        logger.debug(
            "NVML driver version okunamadı (opsiyonel bağımlılık/ortam kısıtı olabilir): %s",
            exc,
        )
    return info
