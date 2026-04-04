"""Sidar Project - Agent Modülleri"""

def __getattr__(name: str):
    """Ağır bağımlılıkları sadece gerektiğinde içe aktar."""
    if name == "SidarAgent":
        from .sidar_agent import SidarAgent

        return SidarAgent
    if name in {"AutoHandle", "AutoHandler"}:
        from .auto_handle import AutoHandle

        return AutoHandle
    if name == "roles":
        from . import roles as roles_module

        return roles_module
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
    "roles",
]
