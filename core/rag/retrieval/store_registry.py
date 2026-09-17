"""Thread-safe shared document-store lifecycle management."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Generic, TypeVar

StoreT = TypeVar("StoreT")
StoreKey = tuple[str, bool, str, str]


def build_store_cache_key(
    *,
    store_dir: Path | str,
    cfg: Any,
    initialize_vector: bool,
    embedding_function_builder: Callable[..., Any] | None,
) -> StoreKey:
    """Build the stable cache identity used for process-shared RAG stores."""
    backend = str(getattr(cfg, "RAG_VECTOR_BACKEND", "chroma") or "chroma").strip().lower()
    builder_identity = (
        str(id(embedding_function_builder)) if embedding_function_builder is not None else "default"
    )
    return (
        str(Path(store_dir).resolve()),
        bool(initialize_vector),
        backend,
        builder_identity,
    )


class SharedStoreRegistry(Generic[StoreT]):
    """Own shared-store caching without depending on the DocumentStore implementation."""

    def __init__(
        self,
        stores: dict[StoreKey, StoreT] | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self.stores: dict[StoreKey, StoreT] = stores if stores is not None else {}
        self._lock = lock or threading.Lock()

    def get_or_create(self, key: StoreKey, factory: Callable[[], StoreT]) -> StoreT:
        """Return the cached store or atomically create it with the supplied factory."""
        with self._lock:
            store = self.stores.get(key)
            if store is None:
                store = factory()
                self.stores[key] = store
            return store
