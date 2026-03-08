import ast
from pathlib import Path


def test_rag_uses_sqlite_fts_for_bm25():
    src = Path("core/rag.py").read_text(encoding="utf-8")
    assert "def _init_fts" in src
    assert "CREATE VIRTUAL TABLE IF NOT EXISTS bm25_index USING fts5" in src
    assert "self._bm25_available = True" in src
    assert "self._init_fts()" in src
    assert "bm25(bm25_index) as score" in src


def test_rag_reads_hf_and_rag_limits_from_config():
    src = Path("core/rag.py").read_text(encoding="utf-8")
    assert "def _apply_hf_runtime_env" in src
    assert "os.environ[\"HF_TOKEN\"] = hf_token" in src
    assert "os.environ[\"HUGGING_FACE_HUB_TOKEN\"] = hf_token" in src
    assert "os.environ[\"HF_HUB_OFFLINE\"] = \"1\"" in src
    assert "os.environ[\"TRANSFORMERS_OFFLINE\"] = \"1\"" in src
    assert "self.default_top_k = top_k if top_k is not None else getattr(self.cfg, \"RAG_TOP_K\", 3)" in src
    assert "def _chunk_text(" in src
    assert "getattr(self.cfg, \"RAG_CHUNK_SIZE\"" in src
    assert "getattr(self.cfg, \"RAG_CHUNK_OVERLAP\"" in src


def test_agent_docs_search_uses_to_thread():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)

    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SidarAgent")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_tool_docs_search")
    fn_src = ast.get_source_segment(src, fn) or ""

    assert "await asyncio.to_thread(self.docs.search" in fn_src