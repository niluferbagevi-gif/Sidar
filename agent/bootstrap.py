from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_sidar_agent_startup(version: str, cfg: Any) -> None:
    """Centralized SidarAgent startup logging."""
    memory_backend = str(getattr(cfg, "MEMORY_BACKEND", "unknown")).strip() or "unknown"
    runtime_mode = str(getattr(cfg, "RUNTIME_MODE", "unknown")).strip() or "unknown"
    logger.info(
        "SidarAgent v%s başlatıldı — sağlayıcı=%s model=%s erişim=%s (memory=%s runtime=%s)",
        version,
        getattr(cfg, "AI_PROVIDER", "unknown"),
        getattr(cfg, "CODING_MODEL", "unknown"),
        getattr(cfg, "ACCESS_LEVEL", "unknown"),
        memory_backend,
        runtime_mode,
    )
