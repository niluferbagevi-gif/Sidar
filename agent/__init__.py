# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

"""Sidar Project - Agent Modülleri"""

from .auto_handle import AutoHandle
from .definitions import SIDAR_KEYS, SIDAR_SYSTEM_PROMPT, SIDAR_WAKE_WORDS
from .sidar_agent import SidarAgent

# Geriye dönük uyumluluk: bazı entegrasyonlar AutoHandler adını bekleyebilir.
AutoHandler = AutoHandle

# Tek kaynak: agent paketinden export edilecek semboller.
_EXPORTED_AGENT_SYMBOLS = {
    "SidarAgent": SidarAgent,
    "AutoHandle": AutoHandle,
    "AutoHandler": AutoHandler,
    "SIDAR_SYSTEM_PROMPT": SIDAR_SYSTEM_PROMPT,
    "SIDAR_KEYS": SIDAR_KEYS,
    "SIDAR_WAKE_WORDS": SIDAR_WAKE_WORDS,
}

__all__ = list(_EXPORTED_AGENT_SYMBOLS.keys())