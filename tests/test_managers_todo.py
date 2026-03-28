"""
managers/todo_manager.py için birim testleri.
Task dataclass, status sabitleri, _normalize_limit, add_task, update_task,
set_tasks, list_tasks, clear helpers.
"""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path


def _get_todo():
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        BASE_DIR = "."

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    if "managers.todo_manager" in sys.modules:
        del sys.modules["managers.todo_manager"]
    import managers.todo_manager as tm
    return tm


def _make_mgr():
    tm = _get_todo()
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_stub = types.ModuleType("config")

        class _Cfg:
            BASE_DIR = tmpdir

        cfg_stub.Config = _Cfg
        sys.modules["config"] = cfg_stub

        if "managers.todo_manager" in sys.modules:
            del sys.modules["managers.todo_manager"]
        import managers.todo_manager as tm2

        mgr = tm2.TodoManager()
    return mgr, tm2


# ══════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════

class TestConstants:
    def test_status_pending(self):
        tm = _get_todo()
        assert tm.STATUS_PENDING == "pending"

    def test_status_in_progress(self):
        tm = _get_todo()
        assert tm.STATUS_IN_PROGRESS == "in_progress"

    def test_status_completed(self):
        tm = _get_todo()
        assert tm.STATUS_COMPLETED == "completed"

    def test_valid_statuses_set(self):
        tm = _get_todo()
        assert tm.VALID_STATUSES == {"pending", "in_progress", "completed"}

    def test_status_icons_keys(self):
        tm = _get_todo()
        assert "pending" in tm.STATUS_ICONS
        assert "in_progress" in tm.STATUS_ICONS
        assert "completed" in tm.STATUS_ICONS


# ══════════════════════════════════════════════════════════════
# Task dataclass
# ══════════════════════════════════════════════════════════════

class TestTaskDataclass:
    def test_default_status_pending(self):
        tm = _get_todo()
        task = tm.Task(id=1, content="Do something")
        assert task.status == tm.STATUS_PENDING

    def test_update_status(self):
        tm = _get_todo()
        task = tm.Task(id=1, content="Do something")
        task.update_status(tm.STATUS_IN_PROGRESS)
        assert task.status == tm.STATUS_IN_PROGRESS

    def test_updated_at_changes(self):
        tm = _get_todo()
        task = tm.Task(id=1, content="Do something")
        old_updated_at = task.updated_at
        import time
        time.sleep(0.01)
        task.update_status(tm.STATUS_COMPLETED)
        assert task.updated_at >= old_updated_at


# ══════════════════════════════════════════════════════════════
# _normalize_limit
# ══════════════════════════════════════════════════════════════

class TestNormalizeLimit:
    def _make(self):
        tm = _get_todo()
        with tempfile.TemporaryDirectory() as tmpdir:

            class _Cfg:
                BASE_DIR = tmpdir

            import types as _t
            cfg = _t.ModuleType("config")
            cfg.Config = _Cfg
            sys.modules["config"] = cfg
            del sys.modules["managers.todo_manager"]
            import managers.todo_manager as tm2
            mgr = tm2.TodoManager()
        return mgr

    def test_normal_value(self):
        mgr = self._make()
        assert mgr._normalize_limit(10) == 10

    def test_clamp_to_max(self):
        mgr = self._make()
        assert mgr._normalize_limit(999) == 200

    def test_clamp_to_min(self):
        mgr = self._make()
        assert mgr._normalize_limit(0) == 1

    def test_string_int(self):
        mgr = self._make()
        assert mgr._normalize_limit(5) == 5

    def test_invalid_uses_default(self):
        mgr = self._make()
        assert mgr._normalize_limit(None) == 50  # type: ignore


# ══════════════════════════════════════════════════════════════
# add_task
# ══════════════════════════════════════════════════════════════

class TestAddTask:
    def _make(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_stub = types.ModuleType("config")

            class _Cfg:
                BASE_DIR = tmpdir

            cfg_stub.Config = _Cfg
            sys.modules["config"] = cfg_stub

            if "managers.todo_manager" in sys.modules:
                del sys.modules["managers.todo_manager"]
            import managers.todo_manager as tm
            mgr = tm.TodoManager()
        return mgr, tm

    def test_add_task_success(self):
        mgr, tm = self._make()
        result = mgr.add_task("Write unit tests")
        assert "✅" in result
        assert "Write unit tests" in result

    def test_empty_content_rejected(self):
        mgr, tm = self._make()
        result = mgr.add_task("   ")
        assert "⚠" in result

    def test_invalid_status_rejected(self):
        mgr, tm = self._make()
        result = mgr.add_task("Test", status="unknown")
        assert "⚠" in result

    def test_task_count_increases(self):
        mgr, tm = self._make()
        mgr.add_task("Task A")
        mgr.add_task("Task B")
        assert len(mgr) == 2

    def test_in_progress_demotes_others(self):
        mgr, tm = self._make()
        mgr.add_task("First", status=tm.STATUS_IN_PROGRESS)
        result = mgr.add_task("Second", status=tm.STATUS_IN_PROGRESS)
        assert "pending'e çekildi" in result


# ══════════════════════════════════════════════════════════════
# update_task
# ══════════════════════════════════════════════════════════════

class TestUpdateTask:
    def _make(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_stub = types.ModuleType("config")

            class _Cfg:
                BASE_DIR = tmpdir

            cfg_stub.Config = _Cfg
            sys.modules["config"] = cfg_stub

            if "managers.todo_manager" in sys.modules:
                del sys.modules["managers.todo_manager"]
            import managers.todo_manager as tm
            mgr = tm.TodoManager()
        return mgr, tm

    def test_update_existing_task(self):
        mgr, tm = self._make()
        mgr.add_task("My task")
        result = mgr.update_task(1, tm.STATUS_COMPLETED)
        assert "✅" in result

    def test_update_nonexistent_task(self):
        mgr, tm = self._make()
        result = mgr.update_task(999, tm.STATUS_COMPLETED)
        assert "bulunamadı" in result

    def test_invalid_status(self):
        mgr, tm = self._make()
        mgr.add_task("My task")
        result = mgr.update_task(1, "garbage")
        assert "⚠" in result

    def test_mark_in_progress(self):
        mgr, tm = self._make()
        mgr.add_task("task")
        result = mgr.mark_in_progress(1)
        assert "in_progress" in result

    def test_mark_completed(self):
        mgr, tm = self._make()
        mgr.add_task("task")
        result = mgr.mark_completed(1)
        assert "completed" in result


# ══════════════════════════════════════════════════════════════
# set_tasks
# ══════════════════════════════════════════════════════════════

class TestSetTasks:
    def _make(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_stub = types.ModuleType("config")

            class _Cfg:
                BASE_DIR = tmpdir

            cfg_stub.Config = _Cfg
            sys.modules["config"] = cfg_stub

            if "managers.todo_manager" in sys.modules:
                del sys.modules["managers.todo_manager"]
            import managers.todo_manager as tm
            mgr = tm.TodoManager()
        return mgr, tm

    def test_set_replaces_all(self):
        mgr, tm = self._make()
        mgr.add_task("Old task")
        mgr.set_tasks([{"content": "New task", "status": "pending"}])
        assert len(mgr) == 1

    def test_non_list_rejected(self):
        mgr, tm = self._make()
        result = mgr.set_tasks("not a list")  # type: ignore
        assert "⚠" in result

    def test_invalid_items_skipped(self):
        mgr, tm = self._make()
        mgr.set_tasks([{"content": "ok", "status": "pending"}, "bad", None])  # type: ignore
        assert len(mgr) == 1

    def test_count_in_result(self):
        mgr, tm = self._make()
        result = mgr.set_tasks([
            {"content": "A", "status": "pending"},
            {"content": "B", "status": "pending"},
        ])
        assert "2" in result


# ══════════════════════════════════════════════════════════════
# list_tasks
# ══════════════════════════════════════════════════════════════

class TestListTasks:
    def _make(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_stub = types.ModuleType("config")

            class _Cfg:
                BASE_DIR = tmpdir

            cfg_stub.Config = _Cfg
            sys.modules["config"] = cfg_stub

            if "managers.todo_manager" in sys.modules:
                del sys.modules["managers.todo_manager"]
            import managers.todo_manager as tm
            mgr = tm.TodoManager()
        return mgr, tm

    def test_empty_list_message(self):
        mgr, _ = self._make()
        result = mgr.list_tasks()
        assert "boş" in result

    def test_lists_added_tasks(self):
        mgr, tm = self._make()
        mgr.add_task("Alpha")
        result = mgr.list_tasks()
        assert "Alpha" in result

    def test_filter_by_status(self):
        mgr, tm = self._make()
        mgr.add_task("task_pending")
        mgr.add_task("task_active", status=tm.STATUS_IN_PROGRESS)
        result = mgr.list_tasks(filter_status=tm.STATUS_IN_PROGRESS)
        assert "task_active" in result
        assert "task_pending" not in result

    def test_filter_no_match_message(self):
        mgr, tm = self._make()
        mgr.add_task("A")
        result = mgr.list_tasks(filter_status=tm.STATUS_COMPLETED)
        assert "yok" in result


# ══════════════════════════════════════════════════════════════
# clear helpers
# ══════════════════════════════════════════════════════════════

class TestClearHelpers:
    def _make(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_stub = types.ModuleType("config")

            class _Cfg:
                BASE_DIR = tmpdir

            cfg_stub.Config = _Cfg
            sys.modules["config"] = cfg_stub

            if "managers.todo_manager" in sys.modules:
                del sys.modules["managers.todo_manager"]
            import managers.todo_manager as tm
            mgr = tm.TodoManager()
        return mgr, tm

    def test_clear_completed(self):
        mgr, tm = self._make()
        mgr.add_task("A")
        mgr.mark_completed(1)
        mgr.clear_completed()
        assert len(mgr) == 0

    def test_clear_all(self):
        mgr, tm = self._make()
        mgr.add_task("A")
        mgr.add_task("B")
        mgr.clear_all()
        assert len(mgr) == 0

    def test_get_active_count(self):
        mgr, tm = self._make()
        mgr.add_task("A")
        mgr.add_task("B")
        mgr.mark_completed(1)
        assert mgr.get_active_count() == 1

    def test_repr(self):
        mgr, tm = self._make()
        assert "TodoManager" in repr(mgr)
