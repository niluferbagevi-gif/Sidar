import ast
from pathlib import Path


def _get_class_fn_src(module_path: str, class_name: str, fn_name: str) -> str:
    src = Path(module_path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    fn = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name)
    return ast.get_source_segment(src, fn) or ""


def test_docs_search_is_async_and_uses_to_thread():
    src = _get_class_fn_src("agent/auto_handle.py", "AutoHandle", "_try_docs_search")
    assert "async def _try_docs_search" in src
    assert "await asyncio.to_thread(self.docs.search" in src


def test_github_info_regex_requires_info_intent_keywords():
    src = _get_class_fn_src("agent/auto_handle.py", "AutoHandle", "_try_github_info")
    assert "bilgi|info|özet|durum|detay" in src
