"""Supervisor/role arasında minimal bağlam taşıyan hafif bellek merkezi."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class RoleMemory:
    role: str
    notes: List[str] = field(default_factory=list)


class MemoryHub:
    """Global + role-local kısa ömürlü notları yönetir."""

    def __init__(self) -> None:
        self._global_notes: List[str] = []
        self._role_notes: Dict[str, RoleMemory] = defaultdict(lambda: RoleMemory(role="unknown"))

    def add_global(self, note: str) -> None:
        if note:
            self._global_notes.append(note)

    def add_role_note(self, role: str, note: str) -> None:
        if not note:
            return
        mem = self._role_notes.get(role)
        if mem is None or mem.role == "unknown":
            mem = RoleMemory(role=role)
            self._role_notes[role] = mem
        mem.notes.append(note)

    def global_context(self, limit: int = 5) -> List[str]:
        return self._global_notes[-max(1, limit):]

    def role_context(self, role: str, limit: int = 5) -> List[str]:
        mem = self._role_notes.get(role)
        if not mem:
            return []
        return mem.notes[-max(1, limit):]

    def aadd_global(self, note: str) -> None:
        self.add_global(note)

    def aadd_role_note(self, role: str, note: str) -> None:
        self.add_role_note(role, note)

    def aglobal_context(self, limit: int = 5) -> List[str]:
        return self.global_context(limit)

    def arole_context(self, role: str, limit: int = 5) -> List[str]:
        return self.role_context(role, limit)