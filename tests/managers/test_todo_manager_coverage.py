from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from managers.todo_manager import STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_PENDING, TodoManager


def _manager(tmp_path: Path) -> TodoManager:
    cfg = SimpleNamespace(BASE_DIR=tmp_path)
    return TodoManager(cfg=cfg)


def test_load_handles_invalid_payload_and_add_task_validations(tmp_path: Path) -> None:
    todo_path = tmp_path / "todos.json"
    todo_path.write_text('{"invalid": true}', encoding="utf-8")

    manager = _manager(tmp_path)

    assert len(manager) == 0
    assert "boş olamaz" in manager.add_task("   ")
    assert "Geçersiz durum" in manager.add_task("iş", status="unknown")


def test_set_tasks_and_update_task_enforce_single_in_progress(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    msg = manager.set_tasks(
        [
            {"content": "A", "status": STATUS_IN_PROGRESS},
            {"content": "B", "status": STATUS_IN_PROGRESS},
            {"content": "C", "status": STATUS_PENDING},
            {"content": " ", "status": STATUS_COMPLETED},
        ]
    )

    assert "pending'e çekildi" in msg
    tasks = manager.get_tasks()
    in_progress = [t for t in tasks if t["status"] == STATUS_IN_PROGRESS]
    assert len(in_progress) == 1

    update_msg = manager.update_task(in_progress[0]["id"], STATUS_COMPLETED)
    assert "güncellendi" in update_msg
    assert "Geçersiz durum" in manager.update_task(1, "bad")
    assert "bulunamadı" in manager.update_task(999, STATUS_PENDING)


def test_list_clear_scan_and_repr_paths(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.add_task("ilk", status=STATUS_PENDING)
    manager.add_task("aktif", status=STATUS_IN_PROGRESS)
    manager.add_task("bitti", status=STATUS_COMPLETED)

    listed = manager.list_tasks(limit="bad")
    assert "Görev Listesi" in listed
    assert "Devam Eden" in listed

    assert manager.get_active_count() == 2
    assert "tasks=" in repr(manager)

    removed_msg = manager.clear_completed()
    assert "tamamlanmış görev" in removed_msg

    all_cleared = manager.clear_all()
    assert "Tüm görevler temizlendi" in all_cleared

    project_file = tmp_path / "module.py"
    project_file.write_text("# TODO: add tests\nprint('ok')\n", encoding="utf-8")

    scan_msg = manager.scan_project_todos(str(tmp_path), ["py"])
    assert "TODO VE FIXME" in scan_msg

    outside = manager.scan_project_todos("/tmp", ["py"])
    assert "Güvenlik ihlali" in outside

    assert "geçerli dosya uzantısı" in manager.scan_project_todos(str(tmp_path), ["", "  "])

    persisted = json.loads((tmp_path / "todos.json").read_text(encoding="utf-8"))
    assert isinstance(persisted, list)
