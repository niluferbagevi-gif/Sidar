from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.todo_manager import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    Task,
    TodoManager,
)


@pytest.fixture()
def manager(tmp_path: Path) -> TodoManager:
    cfg = SimpleNamespace(BASE_DIR=tmp_path)
    return TodoManager(cfg=cfg)


def test_task_update_status_changes_timestamp(monkeypatch):
    task = Task(id=1, content="x")
    monkeypatch.setattr("managers.todo_manager.time.time", lambda: 1234.0)
    task.update_status(STATUS_COMPLETED)
    assert task.status == STATUS_COMPLETED
    assert task.updated_at == 1234.0


def test_add_task_validations_and_invalid_status(manager: TodoManager):
    assert "boş olamaz" in manager.add_task("   ")
    assert "Geçersiz durum" in manager.add_task("iş", status="bad")
    ok_msg = manager.add_task("normal pending", status=STATUS_PENDING)
    assert "Görev eklendi" in ok_msg
    assert "tek aktif görev" not in ok_msg


def test_add_task_in_progress_demotes_existing(manager: TodoManager):
    manager.add_task("a", status=STATUS_IN_PROGRESS)
    msg = manager.add_task("b", status=STATUS_IN_PROGRESS)
    assert "tek aktif görev" in msg

    tasks = manager.get_tasks(limit=10)
    assert tasks[0]["status"] == STATUS_PENDING
    assert tasks[1]["status"] == STATUS_IN_PROGRESS


def test_set_tasks_validation_and_single_in_progress_rule(manager: TodoManager):
    assert "liste formatında" in manager.set_tasks("bad")

    msg = manager.set_tasks(
        [
            {"content": "a", "status": STATUS_IN_PROGRESS},
            {"content": "b", "status": STATUS_IN_PROGRESS},
            {"content": "c", "status": STATUS_PENDING},
            {"content": "", "status": STATUS_PENDING},  # skip empty
            "invalid",  # skip non-dict
        ]
    )
    assert "3 görev" in msg
    assert "tek aktif görev" in msg

    items = manager.get_tasks(limit=10)
    assert [i["status"] for i in items] == [STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_PENDING]


def test_update_task_paths_and_shortcuts(manager: TodoManager):
    manager.set_tasks([{"content": "a", "status": STATUS_PENDING}])

    assert "Geçersiz durum" in manager.update_task(1, "wrong")
    assert "bulunamadı" in manager.update_task(99, STATUS_COMPLETED)

    in_progress_msg = manager.mark_in_progress(1)
    assert "güncellendi" in in_progress_msg
    completed_msg = manager.mark_completed(1)
    assert "completed" in completed_msg


def test_update_task_in_progress_appends_demoted_info(manager: TodoManager):
    manager.set_tasks(
        [
            {"content": "a", "status": STATUS_IN_PROGRESS},
            {"content": "b", "status": STATUS_PENDING},
        ]
    )

    msg = manager.update_task(2, STATUS_IN_PROGRESS)
    assert "tek aktif görev" in msg
    items = manager.get_tasks(limit=10)
    assert [i["status"] for i in items] == [STATUS_PENDING, STATUS_IN_PROGRESS]


def test_list_tasks_variants_and_limit_normalization(manager: TodoManager):
    assert "boş" in manager.list_tasks()

    manager.set_tasks(
        [
            {"content": "a", "status": STATUS_PENDING},
            {"content": "b", "status": STATUS_IN_PROGRESS},
            {"content": "c", "status": STATUS_COMPLETED},
        ]
    )

    listed = manager.list_tasks(limit="2")
    assert "Toplam: 2" in listed
    assert "Devam Eden" in listed

    manager.set_tasks([{"content": "only done", "status": STATUS_COMPLETED}])
    assert "görev yok" in manager.list_tasks(filter_status=STATUS_PENDING, limit=1)
    assert "Tamamlanan" in manager.list_tasks(filter_status=STATUS_COMPLETED)


def test_get_tasks_limit_and_counts_repr_len(manager: TodoManager):
    manager.set_tasks(
        [
            {"content": "a", "status": STATUS_PENDING},
            {"content": "b", "status": STATUS_COMPLETED},
            {"content": "c", "status": STATUS_IN_PROGRESS},
        ]
    )

    all_items = manager.get_tasks(limit=500)
    assert len(all_items) == 3  # capped but still includes all
    assert manager.get_active_count() == 2
    assert len(manager) == 3
    assert "tasks=3" in repr(manager)
    # valid status should filter
    assert len(manager.get_tasks(status=STATUS_PENDING, limit=10)) == 1
    # invalid status should not filter
    assert len(manager.get_tasks(status="not-valid", limit=10)) == 3
    # non-int limit should fallback to default=50 and include all current tasks
    assert len(manager.get_tasks(limit="abc")) == 3


def test_clear_completed_and_clear_all(manager: TodoManager):
    manager.set_tasks(
        [
            {"content": "a", "status": STATUS_COMPLETED},
            {"content": "b", "status": STATUS_PENDING},
        ]
    )
    msg = manager.clear_completed()
    assert "1 tamamlanmış" in msg
    assert len(manager) == 1

    msg2 = manager.clear_all()
    assert "1 görev silindi" in msg2
    assert len(manager) == 0
    msg3 = manager.clear_completed()
    assert "0 tamamlanmış" in msg3


def test_load_with_existing_json_and_invalid_entries(tmp_path: Path):
    payload = [
        {"id": 1, "content": "a", "status": "unknown"},
        {"id": 2, "content": " ", "status": STATUS_PENDING},  # removed after strip
        "not-a-dict",
        {"id": 3, "content": "b", "status": STATUS_COMPLETED},
    ]
    (tmp_path / "todos.json").write_text(json.dumps(payload), encoding="utf-8")

    m = TodoManager(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    items = m.get_tasks(limit=10)
    assert len(items) == 2
    assert items[0]["status"] == STATUS_PENDING
    assert items[1]["id"] == 3


def test_load_handles_non_list_json_and_decode_error(tmp_path: Path):
    (tmp_path / "todos.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    m = TodoManager(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    assert len(m) == 0

    (tmp_path / "todos.json").write_text("{broken", encoding="utf-8")
    m2 = TodoManager(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    assert len(m2) == 0


def test_load_handles_locked_todo_file(tmp_path: Path, monkeypatch):
    todo_file = tmp_path / "todos.json"
    todo_file.write_text("[]", encoding="utf-8")

    real_open = open

    def _open_with_lock(path, mode="r", *args, **kwargs):
        if str(path).endswith("todos.json") and "r" in mode:
            raise PermissionError("file is locked")
        return real_open(path, mode, *args, **kwargs)

    probe = tmp_path / "probe.txt"
    probe.write_text("ok", encoding="utf-8")
    with _open_with_lock(probe, "r", encoding="utf-8") as handle:
        assert handle.read() == "ok"
    monkeypatch.setattr("builtins.open", _open_with_lock)
    manager = TodoManager(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    assert len(manager) == 0


def test_add_task_raises_when_todo_file_not_writable(manager: TodoManager, monkeypatch):
    real_open = open

    def _open_readonly(path, mode="r", *args, **kwargs):
        if str(path).endswith("todos.json") and "w" in mode:
            raise PermissionError("readonly filesystem")
        return real_open(path, mode, *args, **kwargs)

    manager.todo_path.write_text("[]", encoding="utf-8")
    with _open_readonly(manager.todo_path, "r", encoding="utf-8") as handle:
        assert handle.read() == "[]"
    monkeypatch.setattr("builtins.open", _open_readonly)
    with pytest.raises(PermissionError):
        manager.add_task("persist me", status=STATUS_PENDING)


def test_scan_project_todos_branches(manager: TodoManager, tmp_path: Path):
    # invalid directory input
    assert "Geçersiz dizin" in manager.scan_project_todos(directory="\0bad")

    # security violation: outside of base dir
    outside = tmp_path.parent
    assert "Güvenlik ihlali" in manager.scan_project_todos(directory=str(outside))

    # invalid extension set
    assert "geçerli dosya uzantısı" in manager.scan_project_todos(extensions=["", "   "])

    # no todo found path
    safe_file = tmp_path / "a.py"
    safe_file.write_text("print('ok')\n", encoding="utf-8")
    assert "TODO veya FIXME" in manager.scan_project_todos()

    # found todos path
    todo_file = tmp_path / "b.py"
    todo_file.write_text("# TODO: test\n# FIXME critical\n", encoding="utf-8")
    non_target = tmp_path / "note.txt"
    non_target.write_text("TODO: ignored due to extension filter\n", encoding="utf-8")
    found = manager.scan_project_todos(extensions=["py"])
    assert "TODO VE FIXME" in found
    assert "b.py" in found
    assert "note.txt" not in found


def test_scan_project_todos_handles_walk_exception(manager: TodoManager, monkeypatch):
    def _boom(_path):
        raise RuntimeError("walk-fail")

    monkeypatch.setattr("os.walk", _boom)
    msg = manager.scan_project_todos()
    assert "hata oluştu" in msg


def test_scan_project_todos_ignores_file_read_errors(
    manager: TodoManager, tmp_path: Path, monkeypatch
):
    p = tmp_path / "bad.py"
    p.write_text("# TODO: x", encoding="utf-8")

    real_read_text = Path.read_text

    def _read_text(self, *args, **kwargs):
        if self.name == "bad.py":
            raise OSError("cannot read")
        return real_read_text(self, *args, **kwargs)

    ok_file = tmp_path / "ok.py"
    ok_file.write_text("# noop", encoding="utf-8")
    assert _read_text(ok_file, encoding="utf-8") == "# noop"
    monkeypatch.setattr(Path, "read_text", _read_text)
    msg = manager.scan_project_todos(extensions=[".py"])
    assert "TODO veya FIXME" in msg


def test_todo_manager_isolated(tmp_path):
    todo = TodoManager(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    assert "eklendi" in todo.add_task("kritik test görevi")
