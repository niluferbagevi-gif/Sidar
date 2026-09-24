"""Launcher wizard session cache (``.sidar_session.json``) persistence.

Extracted from ``main.py``; ``main`` keeps same-named wrappers that pass the
normalizer, session version and logger explicitly.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

SelectionNormalizer = Callable[[dict[str, object]], dict[str, Any]]


@contextlib.contextmanager
def session_lock(session_path: Path, *, exclusive: bool) -> Iterator[None]:
    """Lock launcher session cache access across concurrent terminal processes."""
    lock_path = session_path.with_suffix(session_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        with contextlib.suppress(OSError):
            os.chmod(lock_path, 0o600)
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_file.fileno(), operation)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def save_session(
    selection: dict[str, object],
    session_path: Path,
    *,
    normalize: SelectionNormalizer,
    version: int,
) -> Path:
    """Sihirbaz seçimlerini atomik şekilde session cache dosyasına yazar."""
    payload = {
        "version": version,
        "selection": normalize(selection),
    }
    session_path.parent.mkdir(parents=True, exist_ok=True)
    with session_lock(session_path, exclusive=True):
        tmp_path = session_path.with_suffix(f"{session_path.suffix}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # Session cache may contain provider/model choices and future auth/session metadata;
        # keep it readable only by the current user before and after the atomic replace.
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(session_path)
        os.chmod(session_path, 0o600)
    return session_path


def load_session(
    session_path: Path,
    *,
    normalize: SelectionNormalizer,
    version: int,
    logger_obj: logging.Logger,
) -> dict[str, Any] | None:
    """Son sihirbaz seçimlerini cache'den güvenli şekilde okur."""
    try:
        with session_lock(session_path, exclusive=False):
            payload = json.loads(session_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger_obj.debug(
            "Launcher oturum cache'i henüz yok (ilk çalıştırma olabilir): %s", session_path
        )
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger_obj.warning("Launcher oturum cache'i okunamadı (%s): %s", session_path, exc)
        return None

    if not isinstance(payload, dict) or payload.get("version") != version:
        logger_obj.warning("Launcher oturum cache'i desteklenmeyen biçimde: %s", session_path)
        return None

    selection = payload.get("selection")
    if not isinstance(selection, dict):
        logger_obj.warning("Launcher oturum cache'i seçim alanı içermiyor: %s", session_path)
        return None
    return normalize(selection)
