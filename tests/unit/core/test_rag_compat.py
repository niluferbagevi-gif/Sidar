"""Compatibility import tests for modular RAG façade modules."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.rag import DocumentStore, _pgvector_failure_action_message, document_store
from core.rag.backends import BM25BackendMixin, KeywordBackendMixin
from core.rag.backends.pgvector import _pgvector_failure_action_message as pgvector_message


def test_backend_compatibility_exports_reference_document_store_contract() -> None:
    assert issubclass(BM25BackendMixin, DocumentStore)
    assert issubclass(KeywordBackendMixin, DocumentStore)
    assert pgvector_message is _pgvector_failure_action_message


def test_document_store_facade_status_embedding_and_cache_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passive_store = SimpleNamespace(
        status=lambda: "BM25 fallback aktif", _vector_backend="PGVECTOR", _pgvector_available=False
    )
    assert document_store.build_store_status_label(passive_store) == (
        "BM25 fallback aktif | pgvector (pasif)"
    )
    assert document_store.build_store_status_label(
        SimpleNamespace(status=lambda: "pgvector (pasif)", _vector_backend="pgvector")
    ) == "pgvector (pasif)"

    embedding = object()
    monkeypatch.setattr(document_store, "_build_embedding_function", lambda **_: embedding)
    assert document_store.embedding_device_info(use_gpu=True, gpu_device=2) == {
        "embedding_function": embedding,
        "device": "cuda:2",
    }
    assert document_store.embedding_device_info(use_gpu=False, gpu_device=0)["device"] == "cpu"

    monkeypatch.setattr(document_store, "embed_texts_for_semantic_cache", lambda *_args, **_kwargs: [])
    assert document_store.embed_texts_for_cache(["one", "two"]) == [[0.0], [0.0]]
    assert document_store.embed_texts_for_cache([]) == []
    monkeypatch.setattr(
        document_store, "embed_texts_for_semantic_cache", lambda *_args, **_kwargs: [[0.5]]
    )
    assert document_store.embed_texts_for_cache(["one"]) == [[0.5]]
