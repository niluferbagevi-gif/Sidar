from __future__ import annotations

import logging


def configure_noisy_dependency_loggers(
    logger_names: tuple[str, ...], *, verbose_http: bool
) -> None:
    """Set noisy dependency logger levels consistently for runtime config."""
    target_level = logging.NOTSET if verbose_http else logging.WARNING
    for logger_name in logger_names:
        logging.getLogger(logger_name).setLevel(target_level)
