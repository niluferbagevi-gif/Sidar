"""Lazy compatibility wrappers for RAG embedding helpers.

The facade import remains lazy so importing this module does not initialize the
large document-store module or introduce a circular import during startup.
"""

from __future__ import annotations

import builtins
from typing import Any


def build_embedding_function(
    use_gpu: bool = False,
    gpu_device: int = 0,
    mixed_precision: bool = False,
    *,
    cfg: Any | None = None,
) -> Any:
    from . import build_embedding_function as _build_embedding_function

    return _build_embedding_function(
        use_gpu=use_gpu,
        gpu_device=gpu_device,
        mixed_precision=mixed_precision,
        cfg=cfg,
    )


def embed_texts_for_semantic_cache(
    texts: builtins.list[str], cfg: Any | None = None
) -> builtins.list[builtins.list[float]]:
    from . import embed_texts_for_semantic_cache as _embed_texts_for_semantic_cache

    return _embed_texts_for_semantic_cache(texts, cfg=cfg)


__all__ = ["build_embedding_function", "embed_texts_for_semantic_cache"]
