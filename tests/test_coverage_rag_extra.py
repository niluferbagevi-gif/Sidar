"""
Coverage tests for core/rag.py missing lines:
  32-33, 40-53: embed_texts_for_semantic_cache
  280, 284: _normalize_pg_url, _format_vector_for_sql
  293-327: _init_pgvector
  330-333: _pgvector_embed_texts
  344-389: _upsert_pgvector_chunks
  392-403: _delete_pgvector_parent
  555, 582, 585, 588-589, 593, 596: add_document_from_url / _validate_url_safe
  686-687: delete_document with pgvector
  740-741: _search_sync pgvector branch
  798-837: _fetch_pgvector
  840-841: _pgvector_search
  1061: status with pgvector
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import tempfile
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call

import pytest

from core.rag import embed_texts_for_semantic_cache, DocumentStore as RagStore


# ── embed_texts_for_semantic_cache (lines 40-53) ─────────────────────────────

def test_embed_texts_empty_returns_empty():
    """Line 40: empty texts returns []."""
    result = embed_texts_for_semantic_cache([])
    assert result == []


def test_embed_texts_sentence_transformers_failure():
    """Lines 51-53: returns [] when SentenceTransformer fails."""
    import sys
    with patch.dict(sys.modules, {"sentence_transformers": None}):
        result = embed_texts_for_semantic_cache(["test text"])
    assert result == []


def test_embed_texts_with_mock_model():
    """Lines 45-50: returns vectors when SentenceTransformer succeeds."""
    import numpy as np

    mock_model = MagicMock()
    mock_vectors = np.array([[0.1, 0.2, 0.3]])
    mock_model.encode = MagicMock(return_value=mock_vectors)

    mock_st = MagicMock()
    mock_st.SentenceTransformer = MagicMock(return_value=mock_model)

    with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
        result = embed_texts_for_semantic_cache(["hello world"])

    assert len(result) == 1
    assert len(result[0]) == 3


# ── RagStore helper methods ───────────────────────────────────────────────────

class _Cfg:
    RAG_DIR = Path(tempfile.mkdtemp())
    RAG_VECTOR_BACKEND = "chromadb"
    PGVECTOR_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    PGVECTOR_TABLE = "rag_embeddings"
    PGVECTOR_EMBEDDING_DIM = 384
    USE_GPU = False
    GPU_DEVICE = 0
    GPU_MIXED_PRECISION = False
    DATABASE_URL = ""
    HF_HUB_OFFLINE = False
    RAG_TOP_K = 3
    RAG_CHUNK_SIZE = 500
    RAG_CHUNK_OVERLAP = 50
    CHROMA_PERSIST_PATH = ""


def _make_rag(tmp_path: Path) -> RagStore:
    cfg = _Cfg()
    cfg.RAG_DIR = tmp_path / "rag"
    cfg.RAG_DIR.mkdir(parents=True, exist_ok=True)
    rag = RagStore.__new__(RagStore)
    rag.cfg = cfg
    rag.rag_dir = cfg.RAG_DIR
    rag.store_dir = cfg.RAG_DIR / "store"
    rag.store_dir.mkdir(parents=True, exist_ok=True)
    rag.index_file = cfg.RAG_DIR / "index.json"
    rag._index = {}
    rag._chroma_available = False
    rag.collection = None
    rag._bm25_available = False
    rag.fts_conn = None
    rag._pgvector_available = False
    rag.pg_engine = None
    rag._vector_backend = "chromadb"
    rag._use_gpu = False
    rag._gpu_device = 0
    rag._pg_table = "rag_embeddings"
    rag._pg_embedding_dim = 384
    rag._pg_embedding_model_name = "all-MiniLM-L6-v2"
    rag._pg_embedding_model = None
    rag.default_top_k = 3
    rag.chunk_size = 500
    rag.chunk_overlap = 50
    import threading
    rag._write_lock = threading.Lock()
    return rag


# ── _normalize_pg_url (line 280) ─────────────────────────────────────────────

def test_normalize_pg_url_removes_asyncpg():
    """Line 280: removes +asyncpg from URL."""
    rag = _make_rag(Path(tempfile.mkdtemp()))
    url = "postgresql+asyncpg://user:pass@localhost/db"
    result = rag._normalize_pg_url(url)
    assert "+asyncpg" not in result
    assert "postgresql://user:pass@localhost/db" == result


def test_normalize_pg_url_passthrough():
    """Line 280: passthrough for URLs without asyncpg."""
    rag = _make_rag(Path(tempfile.mkdtemp()))
    url = "postgresql://user:pass@localhost/db"
    result = rag._normalize_pg_url(url)
    assert result == url


# ── _format_vector_for_sql (line 284) ─────────────────────────────────────────

def test_format_vector_for_sql():
    """Line 284: correctly formats vector as SQL string."""
    rag = _make_rag(Path(tempfile.mkdtemp()))
    vec = [0.1, 0.2, 0.3]
    result = rag._format_vector_for_sql(vec)
    assert result.startswith("[")
    assert result.endswith("]")
    assert "0.10000000" in result


# ── _init_pgvector — no postgresql url ──────────────────────────────────────

def test_init_pgvector_no_postgresql_url(tmp_path):
    """Lines 289-291: warns and returns when no postgresql URL."""
    rag = _make_rag(tmp_path)
    rag.cfg.DATABASE_URL = "sqlite:///test.db"
    # Should not raise
    rag._init_pgvector()
    assert not rag._pgvector_available


def test_init_pgvector_missing_packages(tmp_path):
    """Lines 293-295: warns when sqlalchemy/pgvector not installed."""
    rag = _make_rag(tmp_path)
    rag.cfg.DATABASE_URL = "postgresql://localhost/testdb"

    with patch.object(rag, "_check_import", return_value=False):
        rag._init_pgvector()
    assert not rag._pgvector_available


def test_init_pgvector_connection_error(tmp_path):
    """Lines 325-327: sets pgvector_available=False on error."""
    import sys

    rag = _make_rag(tmp_path)
    rag.cfg.DATABASE_URL = "postgresql://localhost/testdb"

    mock_sa = MagicMock()
    mock_sa.create_engine = MagicMock(side_effect=Exception("connection error"))
    mock_st = MagicMock()

    with patch.object(rag, "_check_import", return_value=True):
        with patch.object(rag, "_apply_hf_runtime_env"):
            with patch.dict(sys.modules, {
                "sqlalchemy": mock_sa,
                "sentence_transformers": mock_st,
            }):
                rag._init_pgvector()

    assert not rag._pgvector_available


# ── _pgvector_embed_texts (lines 330-333) ────────────────────────────────────

def test_pgvector_embed_texts_no_model(tmp_path):
    """Line 330-331: returns [] when no model loaded."""
    rag = _make_rag(tmp_path)
    rag._pg_embedding_model = None
    result = rag._pgvector_embed_texts(["test"])
    assert result == []


def test_pgvector_embed_texts_with_model(tmp_path):
    """Lines 332-333: returns vectors from model.encode."""
    import numpy as np

    rag = _make_rag(tmp_path)
    mock_model = MagicMock()
    mock_model.encode = MagicMock(return_value=np.array([[0.1, 0.2]]))
    rag._pg_embedding_model = mock_model

    result = rag._pgvector_embed_texts(["hello"])
    assert len(result) == 1
    assert len(result[0]) == 2


# ── _upsert_pgvector_chunks (lines 344-389) ──────────────────────────────────

def test_upsert_pgvector_chunks_not_available(tmp_path):
    """Line 344: returns early when pgvector not available."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = False
    # Should not raise
    rag._upsert_pgvector_chunks("doc1", "parent1", "global", "Title", "src", ["chunk"])


def test_upsert_pgvector_chunks_no_chunks(tmp_path):
    """Line 344: returns early when chunks is empty."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = True
    rag.pg_engine = MagicMock()
    rag._upsert_pgvector_chunks("doc1", "parent1", "global", "Title", "src", [])


def test_upsert_pgvector_chunks_success(tmp_path):
    """Lines 347-388: upserts chunks via sqlalchemy."""
    import numpy as np

    rag = _make_rag(tmp_path)
    rag._pgvector_available = True

    mock_model = MagicMock()
    mock_model.encode = MagicMock(return_value=np.array([[0.1, 0.2]]))
    rag._pg_embedding_model = mock_model

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(return_value=mock_conn)
    rag.pg_engine = mock_engine

    with patch("sqlalchemy.text") as mock_text:
        rag._upsert_pgvector_chunks("doc1", "parent1", "global", "Title", "src", ["chunk text"])

    mock_conn.execute.assert_called()


def test_upsert_pgvector_chunks_exception(tmp_path):
    """Line 388-389: exception is logged but doesn't raise."""
    import numpy as np

    rag = _make_rag(tmp_path)
    rag._pgvector_available = True

    mock_model = MagicMock()
    mock_model.encode = MagicMock(return_value=np.array([[0.1, 0.2]]))
    rag._pg_embedding_model = mock_model

    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(side_effect=Exception("db error"))
    rag.pg_engine = mock_engine

    with patch("sqlalchemy.text"):
        rag._upsert_pgvector_chunks("doc1", "parent1", "global", "Title", "src", ["chunk"])


# ── _delete_pgvector_parent (lines 392-403) ──────────────────────────────────

def test_delete_pgvector_parent_not_available(tmp_path):
    """Line 392: returns early when pgvector not available."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = False
    rag._delete_pgvector_parent("parent1", "global")  # should not raise


def test_delete_pgvector_parent_success(tmp_path):
    """Lines 395-402: deletes via sqlalchemy."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = True

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(return_value=mock_conn)
    rag.pg_engine = mock_engine

    with patch("sqlalchemy.text"):
        rag._delete_pgvector_parent("parent1", "global")

    mock_conn.execute.assert_called_once()


def test_delete_pgvector_parent_exception(tmp_path):
    """Line 402-403: exception is logged but doesn't raise."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = True

    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(side_effect=Exception("db error"))
    rag.pg_engine = mock_engine

    with patch("sqlalchemy.text"):
        rag._delete_pgvector_parent("parent1", "global")


# ── _validate_url_safe (lines 582, 585, 588-589, 593, 596) ──────────────────

def test_validate_url_safe_valid_public_url(tmp_path):
    """No exception for valid public URL."""
    rag = _make_rag(tmp_path)
    rag._validate_url_safe("https://example.com/page")


def test_validate_url_safe_non_http_scheme(tmp_path):
    """Line 582: non-http/https scheme raises ValueError."""
    rag = _make_rag(tmp_path)
    with pytest.raises(ValueError, match="http"):
        rag._validate_url_safe("ftp://example.com/file")


def test_validate_url_safe_no_hostname(tmp_path):
    """Line 585: URL without hostname raises ValueError."""
    rag = _make_rag(tmp_path)
    with pytest.raises(ValueError):
        rag._validate_url_safe("http:///path")


def test_validate_url_safe_private_ip(tmp_path):
    """Lines 588-589: private IP raises ValueError."""
    rag = _make_rag(tmp_path)
    with pytest.raises(ValueError, match="İç ağ"):
        rag._validate_url_safe("http://192.168.1.1/api")


def test_validate_url_safe_loopback(tmp_path):
    """Lines 588-589: loopback raises ValueError."""
    rag = _make_rag(tmp_path)
    with pytest.raises(ValueError, match="İç ağ"):
        rag._validate_url_safe("http://127.0.0.1/page")


def test_validate_url_safe_blocked_host(tmp_path):
    """Line 596: blocked hostname raises ValueError."""
    rag = _make_rag(tmp_path)
    with pytest.raises(ValueError, match="localhost"):
        rag._validate_url_safe("http://localhost/api")


def test_validate_url_safe_metadata_server(tmp_path):
    """Line 596: GCP metadata server raises ValueError."""
    rag = _make_rag(tmp_path)
    with pytest.raises(ValueError):
        rag._validate_url_safe("http://metadata.google.internal/computeMetadata/v1/")


# ── _fetch_pgvector (lines 798-837) ──────────────────────────────────────────

def test_fetch_pgvector_not_available(tmp_path):
    """Lines 798-799: returns [] when pgvector not available."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = False
    result = rag._fetch_pgvector("query", 3, "global")
    assert result == []


def test_fetch_pgvector_success(tmp_path):
    """Lines 800-834: fetches results from postgres."""
    import numpy as np

    rag = _make_rag(tmp_path)
    rag._pgvector_available = True

    mock_model = MagicMock()
    mock_model.encode = MagicMock(return_value=np.array([[0.1, 0.2]]))
    rag._pg_embedding_model = mock_model

    mock_row = MagicMock()
    mock_row.parent_id = "parent1"
    mock_row.title = "Doc Title"
    mock_row.source = "http://source.com"
    mock_row.chunk_content = "Chunk content"
    mock_row.distance = 0.1

    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=[mock_row])

    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=mock_result)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(return_value=mock_conn)
    rag.pg_engine = mock_engine

    with patch("sqlalchemy.text"):
        results = rag._fetch_pgvector("test query", 3, "global")

    assert len(results) == 1
    assert results[0]["id"] == "parent1"
    assert results[0]["score"] == pytest.approx(0.9, abs=0.01)


def test_fetch_pgvector_exception(tmp_path):
    """Lines 835-837: exception returns []."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = True

    mock_model = MagicMock()
    mock_model.encode = MagicMock(side_effect=Exception("embed error"))
    rag._pg_embedding_model = mock_model

    result = rag._fetch_pgvector("query", 3, "global")
    assert result == []


# ── _pgvector_search (lines 840-841) ─────────────────────────────────────────

def test_pgvector_search_delegates_to_fetch(tmp_path):
    """Lines 840-841: _pgvector_search calls _fetch_pgvector and formats."""
    rag = _make_rag(tmp_path)

    with patch.object(rag, "_fetch_pgvector", return_value=[]) as mock_fetch:
        with patch.object(rag, "_format_results_from_struct", return_value=(False, "no results")) as mock_format:
            result = rag._pgvector_search("query", 3, "global")

    mock_fetch.assert_called_once_with("query", 3, "global")
    mock_format.assert_called_once()


# ── _search_sync pgvector branch (lines 739-741) ─────────────────────────────

def test_search_sync_pgvector_branch(tmp_path):
    """Lines 739-741: pgvector_search is called in auto mode when available."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = True
    rag._bm25_available = False

    # Add a doc to index so session_docs is non-empty
    rag._index["doc1"] = {"session_id": "global", "title": "Test", "source": ""}

    with patch.object(rag, "_pgvector_search", return_value=(True, "results")) as mock_pgvec:
        result = rag._search_sync("query", mode="auto", session_id="global")

    mock_pgvec.assert_called()


def test_search_sync_vector_mode_pgvector(tmp_path):
    """Lines 722-723: vector mode with pgvector."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = True
    rag._index["doc1"] = {"session_id": "global", "title": "T", "source": ""}

    with patch.object(rag, "_pgvector_search", return_value=(True, "ok")) as mock_pgvec:
        ok, result = rag._search_sync("q", mode="vector", session_id="global")

    assert ok is True
    mock_pgvec.assert_called_once()


# ── status with pgvector (line 1061) ─────────────────────────────────────────

def test_status_with_pgvector(tmp_path):
    """Line 1061: status includes 'pgvector' when available."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = True

    status = rag.status()
    assert "pgvector" in status


def test_status_pgvector_passive(tmp_path):
    """Lines 1062-1063: status shows 'pgvector (pasif)' when backend is pgvector but not active."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = False
    rag._vector_backend = "pgvector"

    status = rag.status()
    assert "pgvector" in status


# ── delete_document with pgvector (lines 685-687) ────────────────────────────

def test_delete_document_with_pgvector(tmp_path):
    """Lines 685-687: delete_document calls _delete_pgvector_parent when pgvector available."""
    rag = _make_rag(tmp_path)
    rag._pgvector_available = True

    doc_id = "doc_to_delete"
    rag._index[doc_id] = {
        "title": "Test Doc",
        "parent_id": "parent_of_doc",
        "session_id": "global",
        "source": "",
    }
    doc_file = rag.store_dir / f"{doc_id}.txt"
    doc_file.write_text("content", encoding="utf-8")

    with patch.object(rag, "_delete_pgvector_parent") as mock_delete:
        with patch.object(rag, "_save_index"):
            with patch.object(rag, "_update_bm25_cache_on_delete"):
                result = rag.delete_document(doc_id, session_id="global")

    mock_delete.assert_called_once_with("parent_of_doc", "global")
    assert "silindi" in result
