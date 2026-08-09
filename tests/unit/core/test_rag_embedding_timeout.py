"""Regression tests for bounded RAG embedding model loading."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import core.embeddings as embeddings


class _SlowSentenceTransformer:
    def __init__(self, *_args, **_kwargs) -> None:
        time.sleep(0.05)


class _FastSentenceTransformer:
    def __init__(self, *_args, **_kwargs) -> None:
        self.loaded = True


def test_sentence_transformer_load_timeout(monkeypatch) -> None:
    embeddings.clear_model_cache()
    monkeypatch.setattr(
        embeddings, "_load_sentence_transformer_class", lambda: _SlowSentenceTransformer
    )
    monkeypatch.setattr(embeddings, "sentence_transformer_local_files_only", lambda *_args: True)
    cfg = SimpleNamespace(USE_GPU=False, RAG_EMBEDDING_LOAD_TIMEOUT_SECONDS=0.001)

    with pytest.raises(embeddings.EmbeddingModelLoadTimeout):
        embeddings.get_sentence_transformer_model("slow-model", cfg)

    assert embeddings._MODEL_CACHE == {}


def test_sentence_transformer_load_timeout_disabled_allows_normal_load(monkeypatch) -> None:
    embeddings.clear_model_cache()
    monkeypatch.setattr(
        embeddings, "_load_sentence_transformer_class", lambda: _FastSentenceTransformer
    )
    monkeypatch.setattr(embeddings, "sentence_transformer_local_files_only", lambda *_args: True)
    cfg = SimpleNamespace(USE_GPU=False, RAG_EMBEDDING_LOAD_TIMEOUT_SECONDS=0)

    model = embeddings.get_sentence_transformer_model("fast-model", cfg)

    assert model.loaded is True
