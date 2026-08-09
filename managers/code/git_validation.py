"""Shared git ref/branch name validation.

Single source of truth for validating a user-supplied string before it is
passed as an argv element to a ``git`` subprocess call (``shell=False``).
``shell=False`` with a list argv already prevents shell metacharacter
injection, but it does not stop git itself from interpreting a value that
starts with ``-`` as an option/flag instead of a ref name ("argument
injection"). This mirrors git's own ``git check-ref-format`` rules closely
enough to reject anything that could be misread as a flag or a malformed ref.
"""

from __future__ import annotations

import re

_FORBIDDEN_FRAGMENTS = ("..", "//", "@{")
_FORBIDDEN_CHARS = frozenset("~^:?*[\\]")
_CONTROL_OR_SPACE_RE = re.compile(r"[\x00-\x1f\x7f\s]")


def is_valid_git_ref_name(ref_name: str) -> bool:
    """Return whether ``ref_name`` is safe to pass as a git branch/ref argv element."""
    normalized = str(ref_name or "").strip()
    if not normalized or normalized.startswith("-") or normalized in {".", "..", "@"}:
        return False
    if normalized.endswith(("/", ".", ".lock")):
        return False
    if normalized.startswith(("/", ".")):
        return False
    if _CONTROL_OR_SPACE_RE.search(normalized):
        return False
    if any(fragment in normalized for fragment in _FORBIDDEN_FRAGMENTS):
        return False
    return not any(char in _FORBIDDEN_CHARS for char in normalized)


__all__ = ["is_valid_git_ref_name"]
