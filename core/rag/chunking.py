"""Pure text chunking helpers for RAG document ingestion."""

from __future__ import annotations

import builtins
from collections.abc import Callable

DEFAULT_RECURSIVE_SEPARATORS = ["\nclass ", "\ndef ", "\n\n", "\n", " ", ""]


def recursive_chunk_text(
    text: str,
    size: int,
    overlap: int,
    separators: list[str] | None = None,
    list_factory: Callable[[str], builtins.list[str]] = builtins.list,
) -> builtins.list[str]:
    """Split text into recursive chunks while preserving the legacy overlap behavior."""
    if not text or size <= 0:
        return []
    overlap = max(0, int(overlap or 0))
    if overlap >= size:
        overlap = max(0, size - 1)

    split_separators = list(separators or DEFAULT_RECURSIVE_SEPARATORS)

    def _split(text_part: str, sep_idx: int) -> builtins.list[str]:
        if len(text_part) <= size:
            return [text_part]

        if sep_idx >= len(split_separators):
            step = max(1, size - overlap)
            return [text_part[i : i + size] for i in range(0, len(text_part), step)]

        sep = split_separators[sep_idx]
        if sep == "":
            parts = list_factory(text_part)
        else:
            raw_parts = text_part.split(sep)
            parts = [raw_parts[0]] + [sep + part for part in raw_parts[1:]] if raw_parts else []

        new_chunks: builtins.list[str] = []
        current_chunk = ""

        for part in parts:
            if len(part) > size:
                if current_chunk:
                    new_chunks.append(current_chunk)
                    current_chunk = ""
                new_chunks.extend(_split(part, sep_idx + 1))
                continue

            if len(current_chunk) + len(part) > size:
                new_chunks.append(current_chunk)
                overlap_len = min(len(current_chunk), overlap)
                current_chunk = current_chunk[-overlap_len:] + part
            else:
                current_chunk += part

        if current_chunk:
            new_chunks.append(current_chunk)

        return new_chunks

    return _split(text, 0)
