"""Collaboration runtime helpers kept outside the monolithic web server module."""

from __future__ import annotations


def iter_stream_chunks(text: str, *, size: int = 180) -> list[str]:
    """Split collaboration assistant streaming text into stable chunks."""
    clean = str(text or "")
    if not clean:
        return []
    return [clean[index : index + size] for index in range(0, len(clean), size)]
