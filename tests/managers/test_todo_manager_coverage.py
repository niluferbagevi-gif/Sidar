from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.todo_manager import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    TodoManager,
)


def _cfg(base_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(BASE_DIR=base_dir)


def test_load_handles_invalid_json_gracefully(tmp_path: Path) -> None:
    (tmp_path / "todos.json").write_text("{broken", encoding="utf-8")

    manager = TodoManager(_cfg(tmp_path))

    assert len(manager) == 0
    assert manager.get_tasks() == []


def test_load_skips_invalid_payload_entries_and_assigns_next_id(tmp_path: Path) -> None:
    payload = [
        "not-dict",
        {"id": 3, "content": "", "status": "pending"},
        {"id": 6, "content": " görev 1 ", "status": "invalid", "created_at": "1", "updated_at": "2"},
        {"content": "görev 2", "status": "completed"},
    ]
    (tmp_path / "todos.json").write_text(json.dumps(payload), encoding="utf-8")

    manager = TodoManager(_cfg(tmp_path))

    tasks = manager.get_tasks(limit=10)
    assert len(tasks) == 2
    assert tasks[0]["status"] == STATUS_PENDING
    assert tasks[1]["content"] == "görev 2"

    msg = manager.add_task("yeni")
    assert "#7" in msg


def test_load_returns_early_when_payload_not_list(tmp_path: Path) -> None:
    (tmp_path / "todos.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

    manager = TodoManager(_cfg(tmp_path))

    assert manager.get_tasks() == []


def test_add_task_rejects_invalid_inputs_and_demotes_existing_active(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))

    assert "boş olamaz" in manager.add_task("   ")
    assert "Geçersiz durum" in manager.add_task("x", status="unknown")

    manager.add_task("ilk", status=STATUS_IN_PROGRESS)
    result = manager.add_task("ikinci", status=STATUS_IN_PROGRESS)

    assert "pending'e çekildi" in result
    active = manager.get_tasks(status=STATUS_IN_PROGRESS)
    assert len(active) == 1
    assert active[0]["content"] == "ikinci"


def test_set_tasks_handles_non_list_and_filters_invalid_items(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))

    assert "liste formatında" in manager.set_tasks("not-a-list")

    message = manager.set_tasks([
        5,
        {"content": "   ", "status": "pending"},
        {"content": "ok", "status": "pending"},
        {"content": "bad", "status": "not-valid"},
    ])

    assert "1 görev" in message
    only = manager.get_tasks()
    assert len(only) == 1
    assert only[0]["content"] == "ok"


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


def test_update_task_invalid_missing_and_wrapper_methods(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))
    manager.set_tasks([
        {"content": "a", "status": STATUS_PENDING},
        {"content": "b", "status": STATUS_IN_PROGRESS},
    ])

    assert "Geçersiz durum" in manager.update_task(1, "x")
    assert "bulunamadı" in manager.update_task(99, STATUS_PENDING)

    msg = manager.mark_in_progress(1)
    assert "pending'e çekildi" in msg
    assert "Görev #1" in msg

    done = manager.mark_completed(1)
    assert "completed" in done


def test_list_tasks_formats_groups_and_filters(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))

    assert "boş" in manager.list_tasks()

    manager.set_tasks([
        {"content": "p1", "status": STATUS_PENDING},
        {"content": "ip", "status": STATUS_IN_PROGRESS},
        {"content": "c1", "status": STATUS_COMPLETED},
    ])

    filtered = manager.list_tasks(filter_status=STATUS_PENDING)
    assert "Bekleyen" in filtered
    assert "#1" in filtered

    manager.set_tasks([{"content": "c", "status": STATUS_COMPLETED}])
    none_msg = manager.list_tasks(filter_status=STATUS_PENDING)
    assert "görev yok" in none_msg

    full = manager.list_tasks(limit=999)
    assert "Tamamlanan" in full


def test_clear_completed_updates_backing_json_and_noop_branch(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))
    manager.add_task("a", status="completed")
    manager.add_task("b", status="pending")

    result = manager.clear_completed()
    payload = json.loads((tmp_path / "todos.json").read_text(encoding="utf-8"))

    assert "1 tamamlanmış" in result
    assert len(payload) == 1
    assert payload[0]["content"] == "b"

    old_payload = (tmp_path / "todos.json").read_text(encoding="utf-8")
    no_removed = manager.clear_completed()
    assert "0 tamamlanmış" in no_removed
    assert (tmp_path / "todos.json").read_text(encoding="utf-8") == old_payload


def test_clear_all_repr_len_and_active_count(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))
    manager.set_tasks([
        {"content": "a", "status": STATUS_PENDING},
        {"content": "b", "status": STATUS_IN_PROGRESS},
        {"content": "c", "status": STATUS_COMPLETED},
    ])

    assert manager.get_active_count() == 2
    assert "tasks=3" in repr(manager)

    msg = manager.clear_all()
    assert "3 görev" in msg
    assert len(manager) == 0


def test_scan_project_todos_rejects_outside_dir_and_empty_extensions(tmp_path: Path) -> None:
    manager = TodoManager(_cfg(tmp_path))

    outside_msg = manager.scan_project_todos(directory="/tmp", extensions=["py"])
    ext_msg = manager.scan_project_todos(directory=str(tmp_path), extensions=["", "   "])

    assert "Güvenlik ihlali" in outside_msg
    assert "geçerli dosya uzantısı" in ext_msg


def test_scan_project_todos_covers_findings_defaults_and_invalid_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = TodoManager(_cfg(tmp_path))
    src = tmp_path / "src"
    ignored = tmp_path / "node_modules"
    src.mkdir()
    ignored.mkdir()

    (src / "a.py").write_text("# TODO: do this\npass\n", encoding="utf-8")
    (src / "b.ts").write_text("// FIXME improve\n", encoding="utf-8")
    (src / "c.txt").write_text("TODO: txt should be ignored\n", encoding="utf-8")
    (ignored / "skip.py").write_text("# TODO: ignored\n", encoding="utf-8")

    assert "Geçersiz dizin" in manager.scan_project_todos(directory=object())

    found = manager.scan_project_todos()
    assert "TODO VE FIXME LİSTESİ" in found
    assert "a.py" in found
    assert "b.ts" in found
    assert "skip.py" not in found

    clean = manager.scan_project_todos(extensions=["md"])
    assert "herhangi bir TODO" in clean

    def boom_walk(_path):
        raise RuntimeError("walk failure")
        yield from []

    monkeypatch.setattr(os, "walk", boom_walk)
    err = manager.scan_project_todos(directory=str(tmp_path), extensions=["py"])
    assert "Tarama sırasında hata" in err


def test_scan_project_todos_ignores_read_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = TodoManager(_cfg(tmp_path))
    bad_file = tmp_path / "bad.py"
    good_file = tmp_path / "good.py"
    bad_file.write_text("# TODO: bad\n", encoding="utf-8")
    good_file.write_text("# TODO: good\n", encoding="utf-8")

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):
        if self.name == "bad.py":
            raise OSError("cannot read")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    result = manager.scan_project_todos(directory=str(tmp_path), extensions=["py"])

    assert "good.py" in result
    assert "bad.py" not in result
