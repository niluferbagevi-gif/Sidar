"""Private, atomic writes for dotenv files containing credentials."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_private_env(path: Path, content: str) -> None:
    """Atomically replace ``path`` with UTF-8 content readable only by its owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if fd >= 0:
            os.close(fd)
        temporary.unlink(missing_ok=True)
        raise
