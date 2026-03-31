"""Sidar Project - Agent Modülleri"""

from .auto_handle import AutoHandle
from .definitions import SIDAR_KEYS, SIDAR_SYSTEM_PROMPT, SIDAR_WAKE_WORDS

# Geriye dönük uyumluluk: bazı entegrasyonlar AutoHandler adını bekleyebilir.
AutoHandler = AutoHandle

def __getattr__(name: str):
    """Ağır bağımlılıkları sadece gerektiğinde içe aktar."""
    if name == "SidarAgent":
        from .sidar_agent import SidarAgent

        return SidarAgent
    raise AttributeError(name)


__all__ = [
    "SidarAgent",
    "AutoHandle",
    "AutoHandler",
    "SIDAR_SYSTEM_PROMPT",
    "SIDAR_KEYS",
    "SIDAR_WAKE_WORDS",
]
