from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_sidar_agent_startup(version: str, cfg: Any) -> None:
    """Centralized SidarAgent startup logging."""
    logger.info(
        "SidarAgent v%s başlatıldı — sağlayıcı=%s model=%s erişim=%s (VECTOR MEMORY + ASYNC)",
        version,
        getattr(cfg, "AI_PROVIDER", "unknown"),
        getattr(cfg, "CODING_MODEL", "unknown"),
        getattr(cfg, "ACCESS_LEVEL", "unknown"),
    )

