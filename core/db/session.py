"""Session and conversation records for ``core.db``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionRecord:
    """Row of ``sessions``: one chat conversation owned by a user."""

    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


@dataclass
class MessageRecord:
    """Row of ``messages``: one chat message with its token usage."""

    id: int
    session_id: str
    role: str
    content: str
    tokens_used: int
    created_at: str


__all__ = ["MessageRecord", "SessionRecord"]
