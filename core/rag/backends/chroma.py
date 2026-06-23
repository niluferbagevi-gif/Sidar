"""ChromaDB vector backend helpers for the RAG document store."""

from __future__ import annotations

import logging
import os
from typing import Any, cast

logger = logging.getLogger(__name__)


def init_chroma(store: Any, *, build_embedding_function: Any) -> None:
    """Initialize ChromaDB persistent client and collection."""
    os.environ["CHROMA_TELEMETRY_DISABLED"] = "1"
    try:
        import chromadb
        from chromadb.config import Settings

        with store._scoped_hf_runtime_env():
            db_path = store.store_dir / "chroma_db"
            store.chroma_client = chromadb.PersistentClient(
                path=str(db_path),
                settings=Settings(anonymized_telemetry=False),
            )
            embedding_fn = build_embedding_function(
                use_gpu=store._use_gpu,
                gpu_device=store._gpu_device,
                mixed_precision=store._mixed_precision,
                cfg=store.cfg,
            )

        create_kwargs: dict[str, Any] = {"metadata": {"hnsw:space": "cosine"}}
        if embedding_fn is not None:
            create_kwargs["embedding_function"] = embedding_fn

        store.collection = store.chroma_client.get_or_create_collection(
            name="sidar_knowledge_base",
            **create_kwargs,
        )
        device_info = f"cuda:{store._gpu_device}" if store._use_gpu and embedding_fn else "cpu"
        logger.info("ChromaDB vektör veritabanı başlatıldı. Embedding device: %s", device_info)
    except Exception as exc:
        logger.error("ChromaDB başlatma hatası: %s", exc)
        store._chroma_available = False


def fetch_chroma(store: Any, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
    collection = store._require_chroma_collection()
    try:
        collection_size = collection.count()
    except Exception:
        collection_size = top_k * 2

    local_multiplier = max(
        1, int(getattr(store.cfg, "RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER", 1) or 1)
    )
    default_multiplier = 2
    multiplier = (
        local_multiplier if getattr(store, "_is_local_llm_provider", False) else default_multiplier
    )
    n_results = min(top_k * multiplier, max(collection_size, 1))

    results = collection.query(
        query_texts=[query], n_results=n_results, where={"session_id": session_id}
    )
    ids = results.get("ids") or []
    if not ids or not ids[0]:
        return []

    documents = results.get("documents") or [[]]
    metadatas = results.get("metadatas") or [[]]
    doc_ids = ids[0]
    doc_chunks = documents[0] if documents else []
    doc_metas = metadatas[0] if metadatas else []

    found_docs: list[dict[str, Any]] = []
    seen_parents: set[str] = set()
    for i, chunk_content in enumerate(doc_chunks):
        raw_meta = doc_metas[i] if i < len(doc_metas) else {}
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        parent_id = str(meta.get("parent_id") or (doc_ids[i] if i < len(doc_ids) else "") or "")
        if not parent_id:
            continue
        if parent_id in seen_parents and len(seen_parents) >= top_k:  # pragma: no cover
            continue
        seen_parents.add(parent_id)
        found_docs.append(
            {
                "id": parent_id,
                "title": str(meta.get("title", "?") or "?"),
                "source": str(meta.get("source", "") or ""),
                "snippet": str(chunk_content or ""),
                "score": 1.0,
            }
        )
        if len(found_docs) >= top_k:
            break
    return found_docs


def chroma_search(store: Any, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
    results = fetch_chroma(store, query, top_k, session_id)
    return cast(
        tuple[bool, str],
        store._format_results_from_struct(
            results, query, source_name="Vektör Arama (ChromaDB + Chunking)"
        ),
    )


__all__ = ["chroma_search", "fetch_chroma", "init_chroma"]
