import ast
from pathlib import Path


def test_memory_save_supports_force_and_interval_gate():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    assert "def _save(self, force: bool = False)" in src
    assert "(now - self._last_saved_at) < self._save_interval_seconds" in src


def test_memory_has_broken_file_cleanup_retention():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    assert "def _cleanup_broken_files" in src
    assert "self._cleanup_broken_files()" in src


def test_memory_add_still_calls_save_for_persistence_flow():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ConversationMemory")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "add")
    fn_src = ast.get_source_segment(src, fn) or ""
    assert "self._save()" in fn_src

def test_memory_has_force_save_and_destructor_flush_hooks():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    assert "def force_save(self)" in src
    assert "def __del__(self)" in src
    assert "self.force_save()" in src


def test_memory_clear_marks_dirty_and_flushes_immediately():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ConversationMemory")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "clear")
    fn_src = ast.get_source_segment(src, fn) or ""
    assert "self._dirty = True" in fn_src
    assert "self.force_save()" in fn_src


def test_memory_fail_closed_encryption_behavior_present():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    assert "except ImportError as exc:" in src
    assert "raise ImportError(" in src
    assert "raise ValueError(" in src
    assert "Düz metin kullanılacak" not in src