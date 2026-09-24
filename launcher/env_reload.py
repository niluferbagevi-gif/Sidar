"""Doctor auto-fix environment reload helpers for the launcher.

Extracted from ``main.py``. Parses simple dotenv files without logging values and
re-applies Doctor-reported or database-related keys into ``os.environ``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

DATABASE_AUTO_FIX_ENV_KEYS = ("DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL", "POSTGRES_PASSWORD")


def parse_env_source_file(path: Path) -> dict[str, str]:
    """Parse simple dotenv assignments for Doctor source reloads without logging values."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def reload_env_source_definitions(details: dict[str, Any] | None) -> bool:
    """Best-effort reload of Doctor-reported dotenv source files into ``os.environ``."""
    if not isinstance(details, dict):
        return False
    definitions = details.get("env_source_definitions")
    if not isinstance(definitions, dict):
        return False

    applied = False
    for key, sources in definitions.items():
        if not isinstance(key, str) or not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            raw_path = str(source.get("path", "") or "").strip()
            if not raw_path:
                continue
            values = parse_env_source_file(Path(raw_path).expanduser())
            if key in values:
                os.environ[key] = values[key]
                applied = True
    return applied


def reload_database_env_from_dotenv_chain(
    config_module: Any, *, logger_obj: logging.Logger
) -> bool:
    """Force Doctor auto-fixed database keys from loaded dotenv files into this process."""
    if config_module is None or not hasattr(config_module, "get_dotenv_load_report"):
        return False

    try:
        events = config_module.get_dotenv_load_report()
    except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as exc:
        logger_obj.debug("Doctor auto-fix dotenv raporu okunamadı: %s", exc)
        return False

    effective_values: dict[str, str] = {}
    applied = False
    for event in events:
        if not event.get("loaded"):
            continue
        raw_path = str(event.get("path", "") or "").strip()
        if not raw_path:
            continue
        values = parse_env_source_file(Path(raw_path).expanduser())
        override = bool(event.get("override"))
        for key in DATABASE_AUTO_FIX_ENV_KEYS:
            if key not in values:
                continue
            if override or key not in effective_values:
                effective_values[key] = values[key]

    for key, value in effective_values.items():
        if os.environ.get(key) != value:
            os.environ[key] = value
            applied = True

    if applied and hasattr(config_module, "Config"):
        config_cls = config_module.Config
        if hasattr(config_module, "get_database_url"):
            config_cls.DATABASE_URL = config_module.get_database_url()
        if hasattr(config_module, "get_container_database_url"):
            config_cls.CONTAINER_DATABASE_URL = config_module.get_container_database_url()
    return applied
