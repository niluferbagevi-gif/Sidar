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
from core.rag.graph import GraphIndex
from core.rag.indexer import GraphIndex as IndexedGraphIndex
from core.rag.query import GraphRAGSearchPlan
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
