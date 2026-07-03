"""Import-contract tests for incrementally extracted compatibility facades."""

from __future__ import annotations

from pathlib import Path

import core.db as db
import core.rag as rag
from core.db import Database, _parse_asyncpg_affected_rows, _quote_sql_identifier
from core.db.engine import Database as EngineDatabase
from core.db.multitenant import AccessPolicyRecord
from core.db_components.dialect import parse_asyncpg_affected_rows, quote_sql_identifier
from core.rag import embeddings_wrapper
from core.rag.graph import LLM_ENTITY_EXTRACTION_TODO, GraphIndex
from core.rag.indexer import GraphIndex as IndexedGraphIndex
from core.rag.query import GraphRAGSearchPlan, build_query_candidates
from managers.code.lsp import (
    decode_lsp_stream,
    encode_lsp_message,
    file_uri_to_path,
    path_to_file_uri,
)
from managers.code.platform import candidate_lsp_executable_paths
from managers.code.pytest_parser import (
    command_invokes_pytest,
    command_requires_uv_tooling,
    extract_pytest_args,
)
from managers.code.runner import build_sanitized_shell_args


def test_rag_graph_and_query_facades_keep_stable_imports(tmp_path: Path) -> None:
    assert rag.GraphIndex is GraphIndex is IndexedGraphIndex
    assert GraphIndex(tmp_path).root_dir == tmp_path.resolve()
    assert GraphRAGSearchPlan(query="q", vector_backend="bm25").query == "q"
    assert rag.build_query_candidates("q") == ["q"]
    assert "LLM-assisted extractor" in LLM_ENTITY_EXTRACTION_TODO


def test_rag_query_expansion_keeps_original_fallback(caplog) -> None:
    assert build_query_candidates("kampanya", expander=lambda _q: ["campaign", "marketing"]) == [
        "campaign",
        "marketing",
        "kampanya",
    ]

    def _broken_expander(_query: str):
        raise RuntimeError("expansion failed")

    with caplog.at_level("WARNING", logger="core.rag.query"):
        assert build_query_candidates("orijinal", expander=_broken_expander) == ["orijinal"]
    assert "falling back to original query" in caplog.text


def test_rag_embedding_wrappers_delegate_lazily(monkeypatch) -> None:
    monkeypatch.setattr(rag, "build_embedding_function", lambda **kwargs: kwargs)
    monkeypatch.setattr(rag, "embed_texts_for_semantic_cache", lambda texts, cfg=None: [texts, cfg])

    assert embeddings_wrapper.build_embedding_function(use_gpu=True, cfg="cfg") == {
        "use_gpu": True,
        "gpu_device": 0,
        "mixed_precision": False,
        "cfg": "cfg",
    }
    assert embeddings_wrapper.embed_texts_for_semantic_cache(["a"], cfg="cfg") == [["a"], "cfg"]


def test_db_init_is_short_backward_compatible_facade() -> None:
    init_lines = Path("core/db/__init__.py").read_text(encoding="utf-8").splitlines()

    assert len(init_lines) <= 200
    assert db.Database is Database is EngineDatabase
    assert AccessPolicyRecord.__name__ == "AccessPolicyRecord"
    assert hasattr(db, "_ASYNCPG_COMMAND_TAG_COUNT_RE")


def test_db_dialect_facade_matches_extracted_helpers() -> None:
    assert _quote_sql_identifier("events") == quote_sql_identifier("events") == '"events"'
    assert _parse_asyncpg_affected_rows("UPDATE 7") == parse_asyncpg_affected_rows("UPDATE 7") == 7


def test_code_helper_modules_are_usable_without_code_manager(tmp_path: Path) -> None:
    assert extract_pytest_args("uv run pytest tests/unit -q") == ["tests/unit", "-q"]
    assert command_requires_uv_tooling("./run_tests.sh") is True
    assert command_invokes_pytest("python -m pytest -q") is True
    assert build_sanitized_shell_args(
        "echo ok", allow_shell_features=False, find_executable=lambda _name: None
    ) == ["echo", "ok"]

    uri = path_to_file_uri(tmp_path / "demo.py")
    assert file_uri_to_path(uri) == (tmp_path / "demo.py").resolve()
    assert decode_lsp_stream(encode_lsp_message({"id": 1})) == [{"id": 1}]

    candidates = candidate_lsp_executable_paths("pyright", base_dir=tmp_path, home_dir=tmp_path)
    assert tmp_path / ".venv" / "bin" / "pyright" in candidates

    windows_candidates = candidate_lsp_executable_paths(
        "ruff", base_dir=tmp_path, home_dir=tmp_path, os_name="nt"
    )
    assert [path.suffix for path in windows_candidates[:4]] == [".cmd", ".exe", ".bat", ""]
    assert tmp_path / ".venv" / "Scripts" / "ruff.cmd" in windows_candidates


def test_rag_session_document_helpers_select_and_format_documents() -> None:
    from core.rag.session_documents import (
        build_session_summary_lines,
        documents_for_session,
        format_document_listing,
        nightly_digest_document_ids,
        select_removable_session_documents,
    )

    index = {
        "recent": {"title": "Recent", "session_id": "s1", "created_at": 3, "size": 1024},
        "old": {
            "title": "Old",
            "session_id": "s1",
            "created_at": 1,
            "preview": "legacy",
            "size": 512,
        },
        "pinned": {"title": "Pinned", "session_id": "s1", "created_at": 0, "tags": ["pinned"]},
        "digest": {"title": "Digest", "session_id": "s1", "source": "memory://nightly-digest/1"},
        "other": {"title": "Other", "session_id": "s2"},
    }

    docs = documents_for_session(index, "s1")
    assert [doc_id for doc_id, _meta in docs] == ["recent", "old", "pinned", "digest"]
    assert [doc_id for doc_id, _meta in select_removable_session_documents(docs, keep_recent_docs=1)] == [
        "old",
        "digest",
    ]
    assert nightly_digest_document_ids(docs) == ["digest"]
    assert build_session_summary_lines("s1", [("old", index["old"])]) == [
        "Oturum: s1",
        "Konsolide edilen belge sayısı: 1",
        "Öne çıkan eski belge özetleri:",
        "- [old] Old :: legacy",
    ]
    assert "[Belge Deposu — 1 belge] (pgvector pasif)" in format_document_listing(
        {"old": index["old"]}, vector_backend="pgvector", pgvector_available=False
    )


def test_rag_graph_formatting_helpers_preserve_legacy_text_shape() -> None:
    from core.rag.graph_formatting import format_graph_impact_analysis, format_graph_search_results

    graph_text = format_graph_search_results(
        "auth",
        code_results=[{"id": "core/auth.py", "score": 3, "neighbors": {"core/db.py"}}],
        entity_results=[
            {
                "score": 2,
                "node": {"id": "entity:auth", "label": "Feature", "name": "Auth"},
                "relations": [
                    {"source": "entity:auth", "target": "entity:db", "relation": "USES"}
                ],
            }
        ],
        graph_nodes={"entity:auth": {"name": "Auth"}, "entity:db": {"name": "DB"}},
    )

    assert "[GraphRAG: auth]" in graph_text
    assert "Auth -[USES]-> DB" in graph_text
    assert "Komşular: core/db.py" in graph_text

    impact_text = format_graph_impact_analysis(
        {
            "target": "web_server.py",
            "node_type": "file",
            "risk_level": "high",
            "direct_dependents": ["tests/unit/root/test_web_server.py"],
            "dependency_paths": [["web_server.py", "web/routes/ws_chat.py"]],
        }
    )

    assert "[GraphRAG Impact] web_server.py" in impact_text
    assert "- Risk seviyesi: high" in impact_text
    assert "1. web_server.py -> web/routes/ws_chat.py" in impact_text
