"""Tests for the implementation behind the core.rag compatibility facade."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from core.rag.retrieval.store_registry import SharedStoreRegistry, build_store_cache_key


def test_store_cache_key_normalizes_backend_and_builder_identity(tmp_path) -> None:
    cfg = SimpleNamespace(RAG_VECTOR_BACKEND=" PGVECTOR ")
    builder = object()

    key = build_store_cache_key(
        store_dir=tmp_path / "store",
        cfg=cfg,
        initialize_vector=True,
        embedding_function_builder=builder,
    )

    assert key == (str((tmp_path / "store").resolve()), True, "pgvector", str(id(builder)))


def test_shared_store_registry_creates_once_under_concurrency() -> None:
    registry: SharedStoreRegistry[object] = SharedStoreRegistry()
    created: list[object] = []

    def factory() -> object:
        value = object()
        created.append(value)
        return value

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: registry.get_or_create(("x", False, "bm25", "default"), factory),
                range(24),
            )
        )

    assert len(created) == 1
    assert all(result is created[0] for result in results)
