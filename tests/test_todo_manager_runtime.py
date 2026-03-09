import importlib.util
import json
import sys
import types
from pathlib import Path


if "config" not in sys.modules:
    class _DummyConfig:
        BASE_DIR = Path(".")

    sys.modules["config"] = types.SimpleNamespace(Config=_DummyConfig)


def _load_todo_module():
    spec = importlib.util.spec_from_file_location("todo_manager_under_test", Path("managers/todo_manager.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


TM = _load_todo_module()


class Cfg:
    def __init__(self, base_dir: Path):
        self.BASE_DIR = base_dir


def test_add_update_list_get_and_len_repr(tmp_path):
    mgr = TM.TodoManager(cfg=Cfg(tmp_path))

    assert mgr.add_task(" ") == "⚠ Görev açıklaması boş olamaz."
    assert "Geçersiz durum" in mgr.add_task("x", status="bad")

    msg1 = mgr.add_task("ilk", status=TM.STATUS_PENDING)
    assert "Görev eklendi" in msg1

    msg2 = mgr.add_task("aktif", status=TM.STATUS_IN_PROGRESS)
    assert "Görev eklendi" in msg2

    msg3 = mgr.add_task("aktif2", status=TM.STATUS_IN_PROGRESS)
    assert "pending'e çekildi" in msg3

    assert len(mgr) == 3
    assert "TodoManager" in repr(mgr)

    listed = mgr.list_tasks()
    assert "Görev Listesi" in listed
    assert "Devam Eden" in listed

    in_prog = mgr.list_tasks(filter_status=TM.STATUS_IN_PROGRESS)
    assert "aktif2" in in_prog

    none_done = mgr.list_tasks(filter_status=TM.STATUS_COMPLETED)
    assert "durumunda görev yok" in none_done

    updated = mgr.update_task(1, TM.STATUS_COMPLETED)
    assert "güncellendi" in updated

    assert "Geçersiz durum" in mgr.update_task(1, "bad")
    assert "bulunamadı" in mgr.update_task(999, TM.STATUS_PENDING)

    assert "güncellendi" in mgr.mark_in_progress(2)
    assert "güncellendi" in mgr.mark_completed(2)

    task_dicts = mgr.get_tasks(limit=2)
    assert len(task_dicts) == 2
    assert all("content" in t for t in task_dicts)

    assert mgr.get_active_count() >= 0


def test_set_tasks_clear_methods_and_persistence(tmp_path):
    mgr = TM.TodoManager(cfg=Cfg(tmp_path))

    assert "liste formatında" in mgr.set_tasks("not-list")

    result = mgr.set_tasks(
        [
            {"content": "A", "status": TM.STATUS_PENDING},
            {"content": "B", "status": TM.STATUS_IN_PROGRESS},
            {"content": "C", "status": TM.STATUS_IN_PROGRESS},
            {"content": "", "status": TM.STATUS_PENDING},
            {"content": "D", "status": "bad"},
        ]
    )
    assert "güncellendi" in result
    assert "pending'e çekildi" in result

    done = mgr.mark_completed(1)
    assert "güncellendi" in done

    removed = mgr.clear_completed()
    assert "tamamlanmış görev silindi" in removed

    all_cleared = mgr.clear_all()
    assert "Tüm görevler temizlendi" in all_cleared
    assert len(mgr) == 0

    # persistence/load path including invalid entries
    todo_path = tmp_path / "todos.json"
    todo_path.write_text(
        json.dumps([
            {"id": 1, "content": " persisted ", "status": "pending"},
            {"id": 2, "content": "", "status": "pending"},
            {"id": 3, "content": "bad status", "status": "unknown"},
            "not-dict",
        ]),
        encoding="utf-8",
    )

    mgr2 = TM.TodoManager(cfg=Cfg(tmp_path))
    tasks = mgr2.get_tasks(limit=50)
    assert len(tasks) == 2
    assert tasks[1]["status"] == TM.STATUS_PENDING


def test_scan_project_todos_and_limit_normalization(tmp_path):
    mgr = TM.TodoManager(cfg=Cfg(tmp_path))

    (tmp_path / "a.py").write_text("# TODO: fix this\nprint('x')\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("FIXME: docs\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("TODO: ignore\n", encoding="utf-8")

    scan = mgr.scan_project_todos()
    assert "TODO VE FIXME" in scan
    assert "a.py" in scan
    assert "b.md" in scan

    # extension normalization path
    scan2 = mgr.scan_project_todos(extensions=["py", "md"])
    assert "TODO VE FIXME" in scan2

    no_ext = mgr.scan_project_todos(extensions=["", " "])
    assert "geçerli dosya uzantısı" in no_ext

    outside = mgr.scan_project_todos(directory="/")
    assert "Güvenlik ihlali" in outside

    invalid_dir = mgr.scan_project_todos(directory="\0")
    assert "Geçersiz dizin" in invalid_dir or "Güvenlik ihlali" in invalid_dir

    # list/get uses normalized limit boundaries
    mgr.set_tasks([{"content": "x", "status": TM.STATUS_PENDING}] * 5)
    assert len(mgr.get_tasks(limit=-10)) == 1
    assert "Toplam" in mgr.list_tasks(limit="bad")


def test_todo_manager_load_edge_cases(tmp_path):
    todo_path = tmp_path / "todos.json"

    # 1. JSON valid ama liste degil (örn dict)
    todo_path.write_text(json.dumps({"dict": "value"}), encoding="utf-8")
    mgr1 = TM.TodoManager(cfg=Cfg(tmp_path))
    assert len(mgr1) == 0

    # 2. JSON bozuk (Exception yola dusurur)
    todo_path.write_text("{bad json", encoding="utf-8")
    mgr2 = TM.TodoManager(cfg=Cfg(tmp_path))
    assert len(mgr2) == 0


def test_todo_manager_scan_project_todos_edge_cases(tmp_path):
    mgr = TM.TodoManager(cfg=Cfg(tmp_path))

    # Dizin cozme (resolve) hatasi
    class BadDir:
        def __fspath__(self):
            raise RuntimeError("fspath error")

    assert "Geçersiz dizin parametresi" in mgr.scan_project_todos(directory=BadDir())

    # extensions None fallback
    (tmp_path / "test.py").write_text("# TODO: fix", encoding="utf-8")
    scan1 = mgr.scan_project_todos(extensions=None)
    assert "test.py" in scan1

    # boss uzanti (empty string) in list
    scan2 = mgr.scan_project_todos(extensions=["", "py"])
    assert "test.py" in scan2


def test_todo_manager_list_and_get_tasks_filters(tmp_path):
    mgr = TM.TodoManager(cfg=Cfg(tmp_path))
    mgr.set_tasks([
        {"content": "P1", "status": TM.STATUS_PENDING},
        {"content": "P2", "status": TM.STATUS_PENDING},
    ])
    # in_progress ve completed bos oldugu icin "if pending" bloguna girer
    listed = mgr.list_tasks()
    assert "Bekleyen:" in listed
    assert "Devam Eden:" not in listed
    assert "Tamamlanan:\n" not in listed

    # get_tasks ile gecerli status filtreleme
    tasks = mgr.get_tasks(status=TM.STATUS_PENDING)
    assert len(tasks) == 2