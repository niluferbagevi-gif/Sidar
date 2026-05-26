"""DocumentStore façade + compatibility helpers for modular RAG imports."""

from __future__ import annotations

from typing import Any

from . import DocumentStore, _build_embedding_function, embed_texts_for_semantic_cache


def build_store_status_label(store: Any) -> str:
    """Return a normalized status label including pgvector passive marker."""
    status = str(getattr(store, "status", lambda: "")() or "")
    backend = str(getattr(store, "_vector_backend", "") or "").lower()
    pgvector_available = bool(getattr(store, "_pgvector_available", False))
    if backend == "pgvector" and not pgvector_available and "pgvector (pasif)" not in status:
        status = (status + " | pgvector (pasif)").strip(" |")
    return status


def embedding_device_info(*, use_gpu: bool, gpu_device: int) -> dict[str, Any]:
    """Expose embed init result with explicit device metadata for readiness probes."""
    ef = _build_embedding_function(use_gpu=use_gpu, gpu_device=gpu_device)
    device = f"cuda:{gpu_device}" if use_gpu else "cpu"
    return {"embedding_function": ef, "device": device}


def embed_texts_for_cache(texts: list[str], cfg: Any | None = None) -> list[list[float]]:
    """Compatibility wrapper that never returns an empty payload for non-empty input."""
    vectors = embed_texts_for_semantic_cache(texts, cfg=cfg)
    if texts and not vectors:
        return [[0.0] for _ in texts]
    return vectors


__all__ = [
    "DocumentStore",
    "build_store_status_label",
    "embedding_device_info",
    "embed_texts_for_cache",
]
