"""Shell-independent command argument construction helpers."""

from __future__ import annotations

import shlex
from collections.abc import Callable


def build_sanitized_shell_args(
    command: str,
    *,
    allow_shell_features: bool,
    find_executable: Callable[[str], str | None],
) -> list[str]:
    """Return a validated argv list without enabling subprocess shell parsing."""
    if "\x00" in command:
        raise ValueError("Komut NUL baytı içeremez.")

    if allow_shell_features:
        interpreter = find_executable("bash") or find_executable("sh")
        if not interpreter:
            raise ValueError("Shell özellikleri için bash/sh yorumlayıcısı bulunamadı.")
        return [interpreter, "-lc", command]

    args = shlex.split(command)
    if not args:
        raise ValueError("Komut bağımsız değişkenlere ayrıştırılamadı.")
    if any("\x00" in arg for arg in args):  # pragma: no cover - guarded above
        raise ValueError("Komut argümanları NUL baytı içeremez.")
    return args


__all__ = ["build_sanitized_shell_args"]
