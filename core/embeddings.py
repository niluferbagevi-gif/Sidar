from __future__ import annotations

import logging
from typing import Any, List, Optional

from config import Config

logger = logging.getLogger(__name__)


def embed_texts_for_semantic_cache(texts: List[str], cfg: Optional[Config] = None) -> List[List[float]]:
    """Semantic cache için metinleri normalize edilmiş embedding vektörlerine dönüştürür."""
    if not texts:
        return []

    cfg = cfg or Config()
    model_name = str(getattr(cfg, "PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2") or "all-MiniLM-L6-v2")
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        vectors = model.encode(texts, normalize_embeddings=True)
        return vectors.tolist() if hasattr(vectors, "tolist") else [list(v) for v in vectors]
    except Exception as exc:
        logger.debug("Semantic cache embedding üretilemedi: %s", exc)
        return []
