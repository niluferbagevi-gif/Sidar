from pathlib import Path


def test_memory_db_mode_compatibility_shims_exist():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    assert "def _save(self, force: bool = False)" in src
    assert "def force_save(self)" in src
    assert "def _cleanup_broken_files" in src


def test_memory_sync_wrappers_delegate_to_async_methods():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    assert "self._run_coro_sync(self.aadd(role, content))" in src
    assert "self._run_coro_sync(self.aget_history(n_last))" in src
    assert "self._run_coro_sync(self.acreate_session(title))" in src


def test_memory_clear_and_summary_keep_db_consistency_hooks():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    assert "self._run_coro_sync(self.db.delete_session(sid, self.active_user_id))" in src
    assert "self.create_session(title)" in src
    assert "self._run_coro_sync(self.db.delete_session(sid, uid))" in src


def test_memory_token_estimation_has_tiktoken_fallback():
    src = Path("core/memory.py").read_text(encoding="utf-8")
    assert "import tiktoken" in src
    assert "except ImportError:" in src
    assert "return int(len(total_text) / 3.5)" in src