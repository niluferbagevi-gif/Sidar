"""Supervisor/role arasında minimal bağlam taşıyan hafif bellek merkezi."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RoleMemory:
    """Notes remembered for a single agent role."""

    role: str
    notes: list[str] = field(default_factory=list)


class MemoryHub:
    """Global + role-local kısa ömürlü notları yönetir."""

    def __init__(self) -> None:
        """Start with empty global and per-role note lists."""
        self._global_notes: list[str] = []
        self._role_notes: dict[str, RoleMemory] = defaultdict(lambda: RoleMemory(role="unknown"))

    def add_global(self, note: str) -> None:
        """Append a non-empty note shared with every role."""
        if note:
            self._global_notes.append(note)

    def add_role_note(self, role: str, note: str) -> None:
        """Append a non-empty note visible to ``role`` only."""
        if not note:
            return
        mem = self._role_notes.get(role)
        if mem is None or mem.role == "unknown":
            mem = RoleMemory(role=role)
            self._role_notes[role] = mem
        mem.notes.append(note)

    def global_context(self, limit: int = 5) -> list[str]:
        """Return the last ``limit`` global notes (at least one)."""
        return self._global_notes[-max(1, limit) :]

    def role_context(self, role: str, limit: int = 5) -> list[str]:
        """Return the last ``limit`` notes of ``role`` (at least one)."""
        mem = self._role_notes.get(role)
        if not mem:
            return []
        return mem.notes[-max(1, limit) :]

    def aadd_global(self, note: str) -> None:
        """Alias of ``add_global`` kept for async-named call sites."""
        self.add_global(note)

    def aadd_role_note(self, role: str, note: str) -> None:
        """Alias of ``add_role_note`` kept for async-named call sites."""
        self.add_role_note(role, note)

    def aglobal_context(self, limit: int = 5) -> list[str]:
        """Alias of ``global_context`` kept for async-named call sites."""
        return self.global_context(limit)

    def arole_context(self, role: str, limit: int = 5) -> list[str]:
        """Alias of ``role_context`` kept for async-named call sites."""
        return self.role_context(role, limit)
