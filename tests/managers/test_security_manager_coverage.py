from __future__ import annotations

from pathlib import Path

from managers.security import FULL, RESTRICTED, SANDBOX, SecurityManager


class _Cfg:
    ACCESS_LEVEL = "sandbox"

    def __init__(self, base_dir: Path) -> None:
        self.BASE_DIR = base_dir


def test_security_manager_path_and_permission_matrix(tmp_path: Path) -> None:
    cfg = _Cfg(tmp_path)
    manager = SecurityManager(access_level="unknown", base_dir=tmp_path, cfg=cfg)

    assert manager.level == SANDBOX
    assert manager.level_name == "sandbox"

    safe_file = manager.temp_dir / "a.txt"
    project_file = tmp_path / "notes.txt"

    assert manager.can_read() is True
    assert manager.can_read(str(project_file)) is True
    assert manager.can_read("../etc/passwd") is False
    assert manager.can_read(str(tmp_path / ".env")) is False

    assert manager.can_write(str(safe_file)) is True
    assert manager.can_write(str(project_file)) is False

    manager.level = RESTRICTED
    assert manager.can_write(str(safe_file)) is False
    assert manager.can_execute() is False
    assert manager.can_run_shell() is False

    manager.level = FULL
    manager.level_name = "full"
    assert manager.can_write(str(project_file)) is True
    assert manager.can_write(str(tmp_path.parent / "outside.txt")) is False
    assert manager.can_execute() is True
    assert manager.can_run_shell() is True


def test_security_manager_helpers_and_status(tmp_path: Path) -> None:
    manager = SecurityManager(access_level="sandbox", base_dir=tmp_path, cfg=_Cfg(tmp_path))

    assert manager.is_path_under(str(tmp_path / "temp" / "a.py"), tmp_path) is True
    assert manager.is_path_under("../secret.txt", tmp_path) is False
    assert manager.is_safe_path(str(tmp_path / "temp" / "safe.md")) is True
    assert manager.is_safe_path(str(tmp_path / "sessions" / "a.json")) is False

    write_path = manager.get_safe_write_path("../../dangerous.txt")
    assert write_path == manager.temp_dir / "dangerous.txt"

    assert manager.set_level("sandbox") is False
    assert manager.set_level("full") is True
    assert "FULL" in manager.status_report()
    assert "SecurityManager" in repr(manager)
