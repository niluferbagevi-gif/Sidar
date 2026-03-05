from pathlib import Path


def test_todo_manager_enforces_single_in_progress_on_set_and_update():
    src = Path("managers/todo_manager.py").read_text(encoding="utf-8")
    assert "def _ensure_single_in_progress" in src
    assert "latest_in_progress_id" in src
    assert "if new_status == STATUS_IN_PROGRESS:" in src


def test_todo_manager_surfaces_demotion_message_when_single_active_rule_applies():
    src = Path("managers/todo_manager.py").read_text(encoding="utf-8")
    assert "Aynı anda tek aktif görev kuralı nedeniyle" in src
    assert "görev pending'e çekildi" in src