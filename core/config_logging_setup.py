"""Backward-compatible logging setup helpers for the runtime config facade."""

from __future__ import annotations

import logging
from typing import Any

from core.logging_config import (
    LoggingConfigState,
    configure_noisy_dependency_loggers,
    configure_sidar_logging,
    get_sidar_locale,
    localized_log_message,
)


def log_first_load_info(
    logger: logging.Logger, first_config_load_logged: bool, message: str, *args: Any
) -> None:
    """Log config startup details as INFO once, then DEBUG on reloads."""
    if first_config_load_logged:
        logger.debug(message, *args)
    else:
        logger.info(message, *args)


__all__ = [
    "LoggingConfigState",
    "configure_noisy_dependency_loggers",
    "configure_sidar_logging",
    "get_sidar_locale",
    "localized_log_message",
    "log_first_load_info",
]
