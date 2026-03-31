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
from unittest.mock import patch

import pytest


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


class TestTodoPersistenceErrors:
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
        return mgr

    def test_add_task_raises_when_save_fails_with_db_lock(self):
        mgr = self._make()
        with patch.object(mgr, "_save", side_effect=OSError("database is locked")):
            with pytest.raises(OSError):
                mgr.add_task("Kilitleme senaryosu")

# ===== MERGED FROM tests/test_managers_todo_extra.py =====

import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _get_todo_manager():
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        BASE_DIR = "/tmp/sidar_todo_test"

        def __getattr__(self, name):
            return None

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    if "managers.todo_manager" in sys.modules:
        del sys.modules["managers.todo_manager"]
    import managers.todo_manager as tm
    return tm


# ══════════════════════════════════════════════════════════════
# _load() — dosyadan yükleme (78-99)
# ══════════════════════════════════════════════════════════════

class Extra_TestLoad:
    def test_load_existing_file(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            todo_file = Path(tmpdir) / "todos.json"
            todo_file.write_text(
                json.dumps([
                    {"id": 1, "content": "Test görev", "status": "pending",
                     "created_at": 1000.0, "updated_at": 1000.0}
                ]),
                encoding="utf-8",
            )
            manager = tm.TodoManager(cfg)
            assert len(manager) == 1
            assert manager._tasks[0].content == "Test görev"

    def test_load_invalid_status_defaults_to_pending(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            todo_file = Path(tmpdir) / "todos.json"
            todo_file.write_text(
                json.dumps([{"id": 1, "content": "Görev", "status": "INVALID_STATUS"}]),
                encoding="utf-8",
            )
            manager = tm.TodoManager(cfg)
            assert manager._tasks[0].status == tm.STATUS_PENDING

    def test_load_filters_empty_content(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            todo_file = Path(tmpdir) / "todos.json"
            todo_file.write_text(
                json.dumps([
                    {"id": 1, "content": "", "status": "pending"},
                    {"id": 2, "content": "Geçerli", "status": "pending"},
                ]),
                encoding="utf-8",
            )
            manager = tm.TodoManager(cfg)
            assert len(manager) == 1
            assert manager._tasks[0].content == "Geçerli"

    def test_load_non_list_json_is_ignored(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            todo_file = Path(tmpdir) / "todos.json"
            todo_file.write_text(json.dumps({"key": "value"}), encoding="utf-8")
            manager = tm.TodoManager(cfg)
            assert len(manager) == 0

    def test_load_non_dict_items_are_skipped(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            todo_file = Path(tmpdir) / "todos.json"
            todo_file.write_text(json.dumps(["string_item", 42, {"id": 1, "content": "OK", "status": "pending"}]), encoding="utf-8")
            manager = tm.TodoManager(cfg)
            assert len(manager) == 1

    def test_load_sets_next_id_correctly(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            todo_file = Path(tmpdir) / "todos.json"
            todo_file.write_text(
                json.dumps([
                    {"id": 5, "content": "Görev5", "status": "pending"},
                    {"id": 3, "content": "Görev3", "status": "completed"},
                ]),
                encoding="utf-8",
            )
            manager = tm.TodoManager(cfg)
            assert manager._next_id == 6

    def test_load_corrupt_file_is_handled(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            todo_file = Path(tmpdir) / "todos.json"
            todo_file.write_text("BOZUK JSON {{{", encoding="utf-8")
            # Hata fırlatmamalı
            manager = tm.TodoManager(cfg)
            assert len(manager) == 0


# ══════════════════════════════════════════════════════════════
# set_tasks() — birden fazla in_progress (193→188, 199, 203, 207)
# ══════════════════════════════════════════════════════════════

class Extra_TestSetTasks:
    def _make_manager(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
        return tm, manager

    def test_set_tasks_basic(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.set_tasks([
                {"content": "Görev1", "status": "pending"},
                {"content": "Görev2", "status": "completed"},
            ])
            assert "2 görev" in result
            assert len(manager) == 2

    def test_set_tasks_non_list_returns_error(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.set_tasks("not a list")
            assert "⚠" in result

    def test_set_tasks_with_in_progress_demotes_others(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.set_tasks([
                {"content": "Görev1", "status": "in_progress"},
                {"content": "Görev2", "status": "in_progress"},
                {"content": "Görev3", "status": "pending"},
            ])
            in_progress_count = sum(1 for t in manager._tasks if t.status == tm.STATUS_IN_PROGRESS)
            assert in_progress_count == 1

    def test_set_tasks_demote_message_in_result(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.set_tasks([
                {"content": "Görev1", "status": "in_progress"},
                {"content": "Görev2", "status": "in_progress"},
            ])
            assert "pending'e çekildi" in result

    def test_set_tasks_clears_old_tasks(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Eski görev")
            manager.set_tasks([{"content": "Yeni görev", "status": "pending"}])
            assert len(manager) == 1
            assert manager._tasks[0].content == "Yeni görev"

    def test_set_tasks_skips_invalid_status(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.set_tasks([
                {"content": "Geçerli", "status": "pending"},
                {"content": "Geçersiz", "status": "YANLIS"},
            ])
            assert len(manager) == 1


# ══════════════════════════════════════════════════════════════
# update_task() — in_progress demote (233→232, 247)
# ══════════════════════════════════════════════════════════════

class Extra_TestUpdateTask:
    def test_update_task_to_in_progress_demotes_others(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Görev1", status=tm.STATUS_IN_PROGRESS)
            manager.add_task("Görev2")
            result = manager.update_task(manager._tasks[1].id, tm.STATUS_IN_PROGRESS)
            assert "pending'e çekildi" in result

    def test_update_task_not_found(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.update_task(999, tm.STATUS_COMPLETED)
            assert "⚠" in result

    def test_update_task_invalid_status(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Görev")
            result = manager.update_task(1, "YANLIS")
            assert "⚠" in result


# ══════════════════════════════════════════════════════════════
# list_tasks() — filtered empty (314-316)
# ══════════════════════════════════════════════════════════════

class Extra_TestListTasks:
    def test_list_filtered_status_no_results(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Sadece pending")
            result = manager.list_tasks(filter_status=tm.STATUS_COMPLETED)
            assert "görev yok" in result

    def test_list_empty(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.list_tasks()
            assert "boş" in result

    def test_list_shows_in_progress_first(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Pending görev")
            manager.add_task("Aktif görev", status=tm.STATUS_IN_PROGRESS)
            result = manager.list_tasks()
            assert "Devam Eden" in result


# ══════════════════════════════════════════════════════════════
# clear_completed() — (330→332)
# ══════════════════════════════════════════════════════════════

class Extra_TestClearCompleted:
    def test_clear_completed_removes_completed(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Görev1")
            manager.add_task("Görev2")
            manager.update_task(1, tm.STATUS_COMPLETED)
            result = manager.clear_completed()
            assert "1 tamamlanmış" in result
            assert len(manager) == 1

    def test_clear_completed_when_none(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Aktif görev")
            result = manager.clear_completed()
            assert "0 tamamlanmış" in result


# ══════════════════════════════════════════════════════════════
# get_tasks() — filtering (352-361)
# ══════════════════════════════════════════════════════════════

class Extra_TestGetTasks:
    def test_get_tasks_no_filter(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("G1")
            manager.add_task("G2", status=tm.STATUS_COMPLETED)
            tasks = manager.get_tasks()
            assert len(tasks) == 2

    def test_get_tasks_with_status_filter(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("G1")
            manager.add_task("G2", status=tm.STATUS_COMPLETED)
            tasks = manager.get_tasks(status=tm.STATUS_COMPLETED)
            assert len(tasks) == 1

    def test_get_tasks_returns_dict_list(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Görev")
            tasks = manager.get_tasks()
            assert "id" in tasks[0]
            assert "content" in tasks[0]
            assert "status" in tasks[0]

    def test_get_active_count(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("G1")
            manager.add_task("G2", status=tm.STATUS_COMPLETED)
            assert manager.get_active_count() == 1


# ══════════════════════════════════════════════════════════════
# scan_project_todos() (386-452)
# ══════════════════════════════════════════════════════════════

class Extra_TestScanProjectTodos:
    def test_scan_finds_todos(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            py_file = Path(tmpdir) / "test_code.py"
            py_file.write_text("# TODO: Bu bir test\nx = 1\n", encoding="utf-8")
            manager = tm.TodoManager(cfg)
            result = manager.scan_project_todos(directory=tmpdir)
            assert "TODO" in result

    def test_scan_no_todos_found(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            py_file = Path(tmpdir) / "clean_code.py"
            py_file.write_text("x = 1\ny = 2\n", encoding="utf-8")
            manager = tm.TodoManager(cfg)
            result = manager.scan_project_todos(directory=tmpdir)
            assert "bulunamadı" in result

    def test_scan_security_violation(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.scan_project_todos(directory="/etc")
            assert "⚠" in result or "Güvenlik" in result

    def test_scan_invalid_directory(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.scan_project_todos(directory=None)
            # None directory kullanır base_dir'i
            assert result is not None

    def test_scan_custom_extensions(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            js_file = Path(tmpdir) / "app.js"
            js_file.write_text("// TODO: Fix this\nconsole.log('test');\n", encoding="utf-8")
            manager = tm.TodoManager(cfg)
            result = manager.scan_project_todos(directory=tmpdir, extensions=[".js"])
            assert "TODO" in result

    def test_scan_empty_extensions_list(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.scan_project_todos(directory=tmpdir, extensions=[])
            assert isinstance(result, str)

    def test_scan_fixme_tag(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            py_file = Path(tmpdir) / "code.py"
            py_file.write_text("# FIXME: Düzelt bunu\nx = 1\n", encoding="utf-8")
            manager = tm.TodoManager(cfg)
            result = manager.scan_project_todos(directory=tmpdir)
            assert "FIXME" in result

    def test_scan_with_extension_without_dot(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            py_file = Path(tmpdir) / "script.py"
            py_file.write_text("# TODO: test\n", encoding="utf-8")
            manager = tm.TodoManager(cfg)
            # Extension without dot should still work
            result = manager.scan_project_todos(directory=tmpdir, extensions=["py"])
            assert "TODO" in result


# ══════════════════════════════════════════════════════════════
# Ek: TodoManager yardımcı metodları
# ══════════════════════════════════════════════════════════════

class Extra_TestTodoManagerHelpers:
    def test_add_task_in_progress_demotes_others(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Mevcut aktif", status=tm.STATUS_IN_PROGRESS)
            result = manager.add_task("Yeni aktif", status=tm.STATUS_IN_PROGRESS)
            assert "pending'e çekildi" in result

    def test_add_task_empty_content(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.add_task("")
            assert "⚠" in result

    def test_add_task_invalid_status(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            result = manager.add_task("Görev", status="geçersiz")
            assert "⚠" in result

    def test_mark_in_progress(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Görev")
            result = manager.mark_in_progress(1)
            assert "in_progress" in result

    def test_mark_completed(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("Görev")
            result = manager.mark_completed(1)
            assert "completed" in result

    def test_clear_all(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            manager.add_task("G1")
            manager.add_task("G2")
            result = manager.clear_all()
            assert len(manager) == 0
            assert "2" in result

    def test_repr(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            r = repr(manager)
            assert "TodoManager" in r

    def test_normalize_limit_invalid(self):
        tm = _get_todo_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.BASE_DIR = tmpdir
            manager = tm.TodoManager(cfg)
            assert manager._normalize_limit("invalid") == 50
            assert manager._normalize_limit(0) == 1
            assert manager._normalize_limit(999) == 200
