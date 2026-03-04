import ast
from pathlib import Path


def test_rag_has_bm25_cache_and_invalidation_hooks():
    src = Path("core/rag.py").read_text(encoding="utf-8")
    assert "def _ensure_bm25_index" in src
    assert "self._bm25_index = BM25Okapi(corpus_tokens) if corpus_tokens else None" in src
    assert "self._invalidate_bm25_cache()" in src


def test_agent_docs_search_uses_to_thread():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)

    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SidarAgent")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_tool_docs_search")
    fn_src = ast.get_source_segment(src, fn) or ""

    assert "await asyncio.to_thread(self.docs.search" in fn_src
