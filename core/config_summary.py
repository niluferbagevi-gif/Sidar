"""Read-only system info and console summary views of the Config facade.

`config.Config.get_system_info()` and `print_config_summary()` delegate here.
Both only read class attributes; hardware loading stays in the facade.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_system_info(config_cls: Any) -> dict[str, Any]:
    """Return the summary system info dict (without secrets or connection URLs)."""
    return {
        "project": config_cls.PROJECT_NAME,
        "version": config_cls.VERSION,
        "provider": config_cls.AI_PROVIDER,
        "access_level": config_cls.ACCESS_LEVEL,
        "gpu_enabled": config_cls.USE_GPU,
        "gpu_info": config_cls.GPU_INFO,
        "gpu_count": config_cls.GPU_COUNT,
        "gpu_device": config_cls.GPU_DEVICE,
        "cuda_version": config_cls.CUDA_VERSION,
        "driver_version": config_cls.DRIVER_VERSION,
        "multi_gpu": config_cls.MULTI_GPU,
        "gpu_mixed_precision": config_cls.GPU_MIXED_PRECISION,
        "gpu_memory_fraction": config_cls.GPU_MEMORY_FRACTION,
        "llm_gpu_memory_fraction": config_cls.LLM_GPU_MEMORY_FRACTION,
        "rag_gpu_memory_fraction": config_cls.RAG_GPU_MEMORY_FRACTION,
        "cpu_count": config_cls.CPU_COUNT,
        "debug_mode": config_cls.DEBUG_MODE,
        "web_port": config_cls.WEB_PORT,
        "web_gpu_port": config_cls.WEB_GPU_PORT,
        "hf_hub_offline": config_cls.HF_HUB_OFFLINE,
        "hf_use_local_cache_only": config_cls.HF_USE_LOCAL_CACHE_ONLY,
        "rate_limit_window": config_cls.RATE_LIMIT_WINDOW,
        "rate_limit_chat": config_cls.RATE_LIMIT_CHAT,
        "rate_limit_mutations": config_cls.RATE_LIMIT_MUTATIONS,
        "rate_limit_get_io": config_cls.RATE_LIMIT_GET_IO,
        "rate_limit_ws_connections": config_cls.RATE_LIMIT_WS_CONNECTIONS,
        # REDIS_URL burada yer almaz — host/port/kimlik bilgisi ifşasını önlemek için
        "enable_tracing": config_cls.ENABLE_TRACING,
        "otel_exporter_endpoint": config_cls.OTEL_EXPORTER_ENDPOINT,
        "enable_semantic_cache": config_cls.ENABLE_SEMANTIC_CACHE,
        "semantic_cache_threshold": config_cls.SEMANTIC_CACHE_THRESHOLD,
        "semantic_cache_ttl": config_cls.SEMANTIC_CACHE_TTL,
        "semantic_cache_max_items": config_cls.SEMANTIC_CACHE_MAX_ITEMS,
    }


def print_config_summary(config_cls: Any, *, base_dir: Path) -> None:
    """Print the configuration summary banner to stdout."""
    print("\n" + "═" * 62)
    print(f"  {config_cls.PROJECT_NAME} v{config_cls.VERSION} — Yapılandırma Özeti")
    print("═" * 62)
    print(f"  AI Sağlayıcı     : {config_cls.AI_PROVIDER.upper()}")
    if config_cls.USE_GPU:
        print(f"  GPU              : ✓ {config_cls.GPU_INFO}  (CUDA {config_cls.CUDA_VERSION})")
        print(f"  GPU Sayısı       : {config_cls.GPU_COUNT}")
        print(f"  Hedef Cihaz      : cuda:{config_cls.GPU_DEVICE}")
        print(f"  Mixed Precision  : {'Açık' if config_cls.GPU_MIXED_PRECISION else 'Kapalı'}")
        print(f"  LLM VRAM Payı    : {config_cls.LLM_GPU_MEMORY_FRACTION:.2f}")
        print(f"  RAG VRAM Payı    : {config_cls.RAG_GPU_MEMORY_FRACTION:.2f}")
        if config_cls.DRIVER_VERSION != "N/A":
            print(f"  Sürücü Sürümü    : {config_cls.DRIVER_VERSION}")
    else:
        print(f"  GPU              : ✗ CPU Modu  ({config_cls.GPU_INFO})")
    print(f"  CPU Çekirdek     : {config_cls.CPU_COUNT}")
    print(f"  Erişim Seviyesi  : {config_cls.ACCESS_LEVEL.upper()}")
    print(f"  Debug Modu       : {'Açık' if config_cls.DEBUG_MODE else 'Kapalı'}")
    if config_cls.AI_PROVIDER == "ollama":
        print(f"  CODING Modeli    : {config_cls.CODING_MODEL}")
        print(f"  TEXT Modeli      : {config_cls.TEXT_MODEL}")
    elif config_cls.AI_PROVIDER == "gemini":
        print(f"  Gemini Modeli    : {config_cls.GEMINI_MODEL}")
    elif config_cls.AI_PROVIDER == "openai":
        print(f"  OpenAI Modeli    : {config_cls.OPENAI_MODEL}")
    elif config_cls.AI_PROVIDER == "litellm":
        print(f"  LiteLLM Gateway  : {config_cls.LITELLM_GATEWAY_URL or '-'}")
        print(f"  LiteLLM Modeli   : {config_cls.LITELLM_MODEL or config_cls.OPENAI_MODEL}")
    else:
        print(f"  Anthropic Modeli : {config_cls.ANTHROPIC_MODEL}")
    print(f"  RAG Dizini       : {config_cls.RAG_DIR.relative_to(base_dir)}")
    enc_status = "Etkin (Fernet)" if config_cls.MEMORY_ENCRYPTION_KEY else "Devre Dışı"
    print(f"  Bellek Şifreleme : {enc_status}")
    print("═" * 62 + "\n")
