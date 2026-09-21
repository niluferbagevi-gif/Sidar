"""Memory encryption (Fernet) settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MemorySecuritySettings:
    """Conversation-history-at-rest Fernet encryption key settings."""

    memory_encryption_key: str
    memory_encryption_key_previous: str


def load_memory_security_settings() -> MemorySecuritySettings:
    """Load memory encryption settings from environment variables."""
    return MemorySecuritySettings(
        memory_encryption_key=os.getenv("MEMORY_ENCRYPTION_KEY", ""),
        memory_encryption_key_previous=os.getenv("MEMORY_ENCRYPTION_KEY_PREVIOUS", ""),
    )
