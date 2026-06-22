"""Public RAG facade helpers extracted from ``core.rag``.

This Phase 1 module hosts pure embedding-wrapper construction helpers while
``core.rag`` remains the compatibility import surface for DocumentStore.
"""

from __future__ import annotations

import builtins
import functools
import importlib
import logging
import sys
from typing import Any

from config import Config
from core.embeddings import sentence_transformer_local_files_only

logger = logging.getLogger(__name__)


def embed_texts_for_semantic_cache(
    texts: builtins.list[str], cfg: Config | None = None
) -> builtins.list[builtins.list[float]]:
    from core.embeddings import embed_texts_for_semantic_cache as _embed

    return _embed(texts, cfg=cfg)


def build_embedding_function(
    use_gpu: bool = False,
    gpu_device: int = 0,
    mixed_precision: bool = False,
    cfg: Any | None = None,
) -> Any:
    """Public wrapper for backward-compatible embedding function construction."""
    return _build_embedding_function(
        use_gpu=use_gpu,
        gpu_device=gpu_device,
        mixed_precision=mixed_precision,
        cfg=cfg,
    )


def _build_embedding_function(
    use_gpu: bool = False,
    gpu_device: int = 0,
    mixed_precision: bool = False,
    cfg: Any | None = None,
) -> Any:
    """
    ChromaDB için GPU-farkında embedding fonksiyonu oluşturur.

    use_gpu=True  →  sentence-transformers all-MiniLM-L6-v2 CUDA üzerinde çalışır.
    use_gpu=False →  embedding fonksiyonu açıkça CPU device ile kurulur.

    Döndürülen nesne None ise ChromaDB kendi varsayılanını kullanır.
    """
    try:
        local_files_only = bool(
            sentence_transformer_local_files_only(cfg or Config, "all-MiniLM-L6-v2")
        )
        embedding_function_factory = _resolve_sentence_transformer_embedding_function()
        return _build_embedding_function_cached(
            use_gpu=use_gpu,
            gpu_device=gpu_device,
            mixed_precision=mixed_precision,
            local_files_only=local_files_only,
            embedding_function_factory=embedding_function_factory,
            embedding_function_factory_id=id(embedding_function_factory),
        )
    except Exception as exc:
        logger.warning("⚠️  GPU embedding başlatılamadı, CPU'ya dönülüyor: %s", exc)
        local_files_only = bool(
            sentence_transformer_local_files_only(cfg or Config, "all-MiniLM-L6-v2")
        )
        try:
            embedding_function_factory = _resolve_sentence_transformer_embedding_function()
            return _build_embedding_function_cached(
                use_gpu=False,
                gpu_device=0,
                mixed_precision=False,
                local_files_only=local_files_only,
                embedding_function_factory=embedding_function_factory,
                embedding_function_factory_id=id(embedding_function_factory),
            )
        except Exception as cpu_exc:
            logger.warning("⚠️  CPU embedding de başlatılamadı: %s", cpu_exc)
            return None


def _resolve_sentence_transformer_embedding_function() -> Any:
    embedding_module = sys.modules.get("chromadb.utils.embedding_functions")
    if embedding_module is None:
        embedding_module = importlib.import_module("chromadb.utils.embedding_functions")
    return embedding_module.SentenceTransformerEmbeddingFunction


@functools.lru_cache(maxsize=8)
def _build_embedding_function_cached(
    *,
    use_gpu: bool,
    gpu_device: int,
    mixed_precision: bool,
    local_files_only: bool,
    embedding_function_factory: Any,
    embedding_function_factory_id: int,
) -> Any:
    # Keep the resolved factory and its explicit identity in the cache key so a
    # runtime module/factory swap cannot return an instance built by stale code.
    del embedding_function_factory_id

    device = "cpu"
    torch: Any | None = None
    if use_gpu:
        import torch as _torch

        torch = _torch
        device = f"cuda:{gpu_device}" if torch.cuda.is_available() else "cpu"

    model_name = "all-MiniLM-L6-v2"
    ef = embedding_function_factory(
        model_name=model_name,
        device=device,
        local_files_only=local_files_only,
    )

    # Mixed precision: sentence-transformers encode sırasında half() uygula
    if mixed_precision and device.startswith("cuda"):
        if torch is not None and hasattr(torch, "autocast"):
            _orig_call = ef.__call__

            def _fp16_call(input: Any) -> Any:
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    return _orig_call(input)

            ef.__call__ = _fp16_call
        else:
            logging.warning(
                "⚠️  mixed_precision istendi ancak torch.autocast bulunamadı; FP16 devre dışı."
            )

    logger.info(
        "ChromaDB embedding fonksiyonu başlatıldı: device=%s  mixed_precision=%s",
        device,
        mixed_precision,
    )
    return ef
