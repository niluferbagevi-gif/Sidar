"""Sidar Project - Agent Modülleri"""
from .definitions import SIDAR_KEYS, SIDAR_SYSTEM_PROMPT, SIDAR_WAKE_WORDS
from .sidar_agent import SidarAgent

# Tek kaynak: agent paketinden export edilecek semboller.
_EXPORTED_AGENT_SYMBOLS = {
    "SidarAgent": SidarAgent,
    "SIDAR_SYSTEM_PROMPT": SIDAR_SYSTEM_PROMPT,
    "SIDAR_KEYS": SIDAR_KEYS,
    "SIDAR_WAKE_WORDS": SIDAR_WAKE_WORDS,
}

__all__ = list(_EXPORTED_AGENT_SYMBOLS.keys())
