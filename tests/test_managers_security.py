"""
managers/security.py için birim testleri.
SecurityManager: seviye normalizasyonu, yol güvenlik kontrolleri,
okuma/yazma/çalıştırma izinleri, set_level, status_report.
"""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path


def _get_sec():
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        ACCESS_LEVEL = "sandbox"
        BASE_DIR = "."

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    if "managers.security" in sys.modules:
        del sys.modules["managers.security"]
    import managers.security as sec
    return sec


def _make_sm(level="sandbox", **kwargs):
    sec = _get_sec()
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = sec.SecurityManager(access_level=level, base_dir=Path(tmpdir), **kwargs)
    return sm, sec, tmpdir


# ══════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════

class TestConstants:
    def test_levels_defined(self):
        sec = _get_sec()
        assert sec.RESTRICTED == 0
        assert sec.SANDBOX == 1
        assert sec.FULL == 2

    def test_level_names_map(self):
        sec = _get_sec()
        assert sec.LEVEL_NAMES["restricted"] == sec.RESTRICTED
        assert sec.LEVEL_NAMES["sandbox"] == sec.SANDBOX
        assert sec.LEVEL_NAMES["full"] == sec.FULL


# ══════════════════════════════════════════════════════════════
# _normalize_level_name
# ══════════════════════════════════════════════════════════════

class TestNormalizeLevelName:
    def test_sandbox_normalized(self):
        sec = _get_sec()
        assert sec.SecurityManager._normalize_level_name("sandbox") == "sandbox"

    def test_uppercase_normalized(self):
        sec = _get_sec()
        assert sec.SecurityManager._normalize_level_name("FULL") == "full"

    def test_restricted_normalized(self):
        sec = _get_sec()
        assert sec.SecurityManager._normalize_level_name("restricted") == "restricted"

    def test_unknown_returns_sandbox(self):
        sec = _get_sec()
        assert sec.SecurityManager._normalize_level_name("superadmin") == "sandbox"

    def test_empty_returns_sandbox(self):
        sec = _get_sec()
        assert sec.SecurityManager._normalize_level_name("") == "sandbox"

    def test_none_like_empty_returns_sandbox(self):
        sec = _get_sec()
        assert sec.SecurityManager._normalize_level_name("  ") == "sandbox"


# ══════════════════════════════════════════════════════════════
# _has_dangerous_pattern
# ══════════════════════════════════════════════════════════════

class TestHasDangerousPattern:
    def test_dotdot_slash_is_dangerous(self):
        sec = _get_sec()
        assert sec.SecurityManager._has_dangerous_pattern("../etc/passwd") is True

    def test_etc_prefix_is_dangerous(self):
        sec = _get_sec()
        assert sec.SecurityManager._has_dangerous_pattern("/etc/passwd") is True

    def test_proc_is_dangerous(self):
        sec = _get_sec()
        assert sec.SecurityManager._has_dangerous_pattern("/proc/self/mem") is True

    def test_sys_is_dangerous(self):
        sec = _get_sec()
        assert sec.SecurityManager._has_dangerous_pattern("/sys/kernel") is True

    def test_normal_path_not_dangerous(self):
        sec = _get_sec()
        assert sec.SecurityManager._has_dangerous_pattern("/home/user/project/file.py") is False

    def test_relative_safe_path(self):
        sec = _get_sec()
        assert sec.SecurityManager._has_dangerous_pattern("data/file.txt") is False


# ══════════════════════════════════════════════════════════════
# SecurityManager init
# ══════════════════════════════════════════════════════════════

class TestSecurityManagerInit:
    def test_sandbox_level_numeric(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
        assert sm.level == sec.SANDBOX

    def test_restricted_level(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
        assert sm.level == sec.RESTRICTED

    def test_full_level(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
        assert sm.level == sec.FULL

    def test_level_name_stored(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
        assert sm.level_name == "full"

    def test_temp_dir_created(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            assert sm.temp_dir.exists()

    def test_repr_contains_level(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
        assert "sandbox" in repr(sm)


# ══════════════════════════════════════════════════════════════
# can_execute / can_run_shell
# ══════════════════════════════════════════════════════════════

class TestExecutePermissions:
    def test_restricted_cannot_execute(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
        assert sm.can_execute() is False

    def test_sandbox_can_execute(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
        assert sm.can_execute() is True

    def test_full_can_execute(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
        assert sm.can_execute() is True

    def test_restricted_cannot_run_shell(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
        assert sm.can_run_shell() is False

    def test_sandbox_cannot_run_shell(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
        assert sm.can_run_shell() is False

    def test_full_can_run_shell(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
        assert sm.can_run_shell() is True


# ══════════════════════════════════════════════════════════════
# can_write
# ══════════════════════════════════════════════════════════════

class TestCanWrite:
    def test_restricted_cannot_write(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
            assert sm.can_write(str(Path(tmpdir) / "file.txt")) is False

    def test_sandbox_can_write_to_temp(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            safe_path = str(sm.temp_dir / "output.txt")
            assert sm.can_write(safe_path) is True

    def test_sandbox_cannot_write_outside_temp(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            outside = str(Path(tmpdir) / "outside.txt")
            assert sm.can_write(outside) is False

    def test_full_can_write_in_base_dir(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            path = str(Path(tmpdir) / "subdir" / "file.txt")
            assert sm.can_write(path) is True

    def test_dangerous_path_rejected(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            assert sm.can_write("../../../etc/passwd") is False

    def test_empty_path_rejected(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            assert sm.can_write("") is False


# ══════════════════════════════════════════════════════════════
# can_read
# ══════════════════════════════════════════════════════════════

class TestCanRead:
    def test_none_path_allowed(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
            assert sm.can_read(None) is True

    def test_dangerous_path_rejected(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            assert sm.can_read("/etc/passwd") is False

    def test_base_dir_path_allowed(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            path = str(Path(tmpdir) / "readme.txt")
            assert sm.can_read(path) is True


# ══════════════════════════════════════════════════════════════
# set_level
# ══════════════════════════════════════════════════════════════

class TestSetLevel:
    def test_level_changed(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            changed = sm.set_level("full")
            assert changed is True
            assert sm.level == sec.FULL

    def test_same_level_returns_false(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            assert sm.set_level("sandbox") is False

    def test_unknown_level_falls_back_to_sandbox(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            sm.set_level("unknown")
            assert sm.level_name == "sandbox"


# ══════════════════════════════════════════════════════════════
# status_report
# ══════════════════════════════════════════════════════════════

class TestStatusReport:
    def test_contains_level_name(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
        report = sm.status_report()
        assert "FULL" in report

    def test_returns_string(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
        assert isinstance(sm.status_report(), str)

    def test_get_safe_write_path_in_temp(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            path = sm.get_safe_write_path("output.txt")
            assert path.parent == sm.temp_dir
            assert path.name == "output.txt"
