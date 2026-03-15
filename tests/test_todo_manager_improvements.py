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

def test_todo_manager_has_utf8_persistence_and_limits():
    src = Path("managers/todo_manager.py").read_text(encoding="utf-8")
    assert "with open(self.todo_path, \"r\", encoding=\"utf-8\")" in src
    assert "with open(self.todo_path, \"w\", encoding=\"utf-8\")" in src
    assert "json.dump(payload, f, ensure_ascii=False, indent=2)" in src
    assert "self.todo_path = base_dir / \"todos.json\"" in src
    assert "def list_tasks(self, filter_status: Optional[str] = None, limit: int = 50)" in src
    assert "def get_tasks(self, status: Optional[str] = None, limit: int = 50)" in src


def test_agent_passes_config_to_todo_manager():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8", errors="replace")
    assert "self.todo = TodoManager(self.cfg)" in src


def test_todo_manager_normalizes_invalid_limit_values():
    src = Path("managers/todo_manager.py").read_text(encoding="utf-8")
    assert "def _normalize_limit(self, limit: int, default: int = 50) -> int:" in src
    assert "except (TypeError, ValueError):" in src
    assert "limit = self._normalize_limit(limit)" in src

def test_todo_manager_can_scan_project_todo_fixme_markers():
    src = Path("managers/todo_manager.py").read_text(encoding="utf-8")
    assert "def scan_project_todos(self, directory: Optional[str] = None, extensions: Optional[List[str]] = None)" in src
    assert "⚠ Güvenlik ihlali: Sadece proje dizini taranabilir." in src
    assert "TODO:" in src and "FIXME:" in src
