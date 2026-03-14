# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

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


def test_auto_handle_adds_dot_command_support_and_async_blocking_wrapper():
    src = Path("agent/auto_handle.py").read_text(encoding="utf-8")
    assert "_DOT_CMD_RE = re.compile" in src
    assert "async def _try_dot_command" in src
    assert "await self._run_blocking(self.health.full_report)" in src
    assert "await self._run_blocking(self.health.optimize_gpu_memory)" in src
    assert 'await self._run_blocking(self.code.audit_project, ".")' in src


def test_auto_handle_clear_regex_accepts_dot_clear():
    src = _get_class_fn_src("agent/auto_handle.py", "AutoHandle", "_try_clear_memory")
    assert r"^\.clear\b" in src