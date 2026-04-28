"""Sidar Project - Agent Modülleri"""

from importlib import import_module
from typing import Any


def __getattr__(name: str) -> Any:
    """Ağır bağımlılıkları sadece gerektiğinde içe aktar."""
    if name == "SidarAgent":
        from .sidar_agent import SidarAgent

        return SidarAgent
    if name in {"AutoHandle", "AutoHandler"}:
        from .auto_handle import AutoHandle

        return AutoHandle
    if name == "roles":
        return import_module(".roles", __name__)
    if name == "registry":
        return import_module(".registry", __name__)
    if name == "swarm":
        return import_module(".swarm", __name__)
    if name in {"SIDAR_SYSTEM_PROMPT", "SIDAR_KEYS", "SIDAR_WAKE_WORDS"}:
        from .definitions import SIDAR_KEYS, SIDAR_SYSTEM_PROMPT, SIDAR_WAKE_WORDS

        mapping = {
            "SIDAR_SYSTEM_PROMPT": SIDAR_SYSTEM_PROMPT,
            "SIDAR_KEYS": SIDAR_KEYS,
            "SIDAR_WAKE_WORDS": SIDAR_WAKE_WORDS,
        }
        return mapping[name]
    raise AttributeError(name)


__all__ = [
    "SidarAgent",
    "AutoHandle",
    "AutoHandler",
    "SIDAR_SYSTEM_PROMPT",
    "SIDAR_KEYS",
    "SIDAR_WAKE_WORDS",
]
