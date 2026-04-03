from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from managers.todo_manager import TodoManager


def _cfg(base_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(BASE_DIR=base_dir)


def test_load_handles_invalid_json_gracefully(tmp_path: Path) -> None:
    (tmp_path / "todos.json").write_text("{broken", encoding="utf-8")

    manager = TodoManager(_cfg(tmp_path))

    assert len(manager) == 0
    assert manager.get_tasks() == []


def test_set_tasks_demotes_previous_in_progress_and_normalizes_limits(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))
    message = manager.set_tasks(
        [
            {"content": "ilk", "status": "in_progress"},
            {"content": "ikinci", "status": "in_progress"},
            {"content": "bitti", "status": "completed"},
        ]
    )

    assert "pending'e çekildi" in message
    active = manager.get_tasks(status="in_progress")
    assert len(active) == 1
    assert active[0]["content"] == "ikinci"

    limited = manager.get_tasks(limit="x")
    assert len(limited) == 3


def test_scan_project_todos_rejects_outside_dir_and_empty_extensions(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))

    outside_msg = manager.scan_project_todos(directory="/tmp", extensions=["py"])
    ext_msg = manager.scan_project_todos(directory=str(tmp_path), extensions=["", "   "])

    assert "Güvenlik ihlali" in outside_msg
    assert "geçerli dosya uzantısı" in ext_msg


def test_clear_completed_updates_backing_json(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))
    manager.add_task("a", status="completed")
    manager.add_task("b", status="pending")

    result = manager.clear_completed()
    payload = json.loads((tmp_path / "todos.json").read_text(encoding="utf-8"))

    assert "1 tamamlanmış" in result
    assert len(payload) == 1
    assert payload[0]["content"] == "b"
