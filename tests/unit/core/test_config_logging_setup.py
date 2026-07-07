"""Tests for backward-compatible logging setup re-exports."""

from __future__ import annotations

import logging

from core import config_logging_setup
from core.logging_config import configure_noisy_dependency_loggers


def test_config_logging_setup_reexports_noisy_dependency_helper() -> None:
    """Legacy import path should expose the canonical noisy logger helper."""
    assert config_logging_setup.__all__ == ["configure_noisy_dependency_loggers"]
    assert config_logging_setup.configure_noisy_dependency_loggers is configure_noisy_dependency_loggers


def test_config_logging_setup_helper_controls_named_logger() -> None:
    """The re-exported helper should retain the canonical logger side effects."""
    logger = logging.getLogger("sidar.tests.noisy_dependency_compat")
    handler = logging.NullHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    config_logging_setup.configure_noisy_dependency_loggers((logger.name,), verbose_http=False)

    assert logger.level == logging.WARNING
    assert logger.propagate is True
    assert logger.handlers == []
