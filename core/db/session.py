"""Session and conversation record boundary for the phased ``core.db`` split (Phase 2).

This module now contains the actual definitions of SessionRecord and MessageRecord.
"""

from __future__ import annotations

from dataclasses import dataclass

@dataclass
class SessionRecord:
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str

@dataclass
class MessageRecord:
    id: int
    session_id: str
    role: str
    content: str
    tokens_used: int
    created_at: str

__all__ = ["SessionRecord", "MessageRecord"]
