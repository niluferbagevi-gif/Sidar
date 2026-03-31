"""
Additional tests for managers/security.py to improve coverage.

Targets missing lines:
  108-109, 125-126, 129, 133-134, 142-152, 169, 172-173,
  176-177, 208, 211-212, 226-230
"""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch


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


# ══════════════════════════════════════════════════════════════
# _resolve_safe — lines 108-109
# ══════════════════════════════════════════════════════════════

class TestResolveSafe:
    def test_valid_path_returns_path_object(self):
        sec = _get_sec()
        result = sec.SecurityManager._resolve_safe("/tmp/some/path")
        assert result is not None
        assert isinstance(result, Path)

    def test_exception_returns_none(self):
        """Lines 108-109: exception during resolve → None."""
        sec = _get_sec()
        # Pass a type that will cause Path() to fail
        with patch("managers.security.Path", side_effect=Exception("bad path")):
            result = sec.SecurityManager._resolve_safe("anything")
        assert result is None


# ══════════════════════════════════════════════════════════════
# is_path_under — lines 125-126, 129, 133-134
# ══════════════════════════════════════════════════════════════

class TestIsPathUnder:
    def test_dangerous_pattern_returns_false(self):
        """Lines 125-126: dangerous pattern in path_str → False + warning log."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            result = sm.is_path_under("../../../etc/passwd", sm.base_dir)
        assert result is False

    def test_resolve_safe_returns_none_returns_false(self):
        """Line 129: _resolve_safe returns None → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            with patch.object(sec.SecurityManager, "_resolve_safe", return_value=None):
                result = sm.is_path_under("/some/path", sm.base_dir)
        assert result is False

    def test_path_outside_base_returns_false(self):
        """Lines 133-134: resolved path not relative to base → ValueError → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            # /tmp is outside tmpdir (resolved path won't be under base)
            result = sm.is_path_under("/var/log/syslog", sm.base_dir)
        assert result is False

    def test_path_inside_base_returns_true(self):
        """Lines 131-132: path inside base → True."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            inside = str(Path(tmpdir) / "subdir" / "file.txt")
            result = sm.is_path_under(inside, sm.base_dir)
        assert result is True


# ══════════════════════════════════════════════════════════════
# is_safe_path — lines 142-152
# ══════════════════════════════════════════════════════════════

class TestIsSafePath:
    def test_dangerous_pattern_returns_false(self):
        """Line 143-144: dangerous path pattern → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            assert sm.is_safe_path("../../../etc/passwd") is False

    def test_blocked_path_returns_false(self):
        """Lines 147-148: blocked pattern (e.g., .env) → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            # .env file in tmpdir
            env_path = str(Path(tmpdir) / ".env")
            assert sm.is_safe_path(env_path) is False

    def test_path_outside_base_returns_false(self):
        """Lines 149-150: path resolves outside base_dir → ValueError → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            assert sm.is_safe_path("/var/log/app.log") is False

    def test_valid_path_inside_base_returns_true(self):
        """Lines 149-150: path inside base → True."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            safe = str(Path(tmpdir) / "app" / "data.json")
            assert sm.is_safe_path(safe) is True

    def test_exception_during_resolve_returns_false(self):
        """Lines 151-152: any exception → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            # Pass something that causes an exception inside is_safe_path
            with patch("managers.security.Path", side_effect=Exception("path error")):
                result = sm.is_safe_path("/any/path")
        assert result is False

    def test_git_dir_blocked(self):
        """_is_blocked_path: .git directory → blocked."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            git_path = str(Path(tmpdir) / ".git" / "config")
            assert sm.is_safe_path(git_path) is False

    def test_sessions_dir_blocked(self):
        """_is_blocked_path: sessions directory → blocked."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            sessions_path = str(Path(tmpdir) / "sessions" / "data.json")
            assert sm.is_safe_path(sessions_path) is False


# ══════════════════════════════════════════════════════════════
# can_read — lines 169, 172-173, 176-177
# ══════════════════════════════════════════════════════════════

class TestCanRead:
    def test_resolve_safe_none_returns_false(self):
        """Line 169: _resolve_safe returns None → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            with patch.object(sec.SecurityManager, "_resolve_safe", return_value=None):
                result = sm.can_read("/some/bad/path")
        assert result is False

    def test_blocked_path_returns_false_with_warning(self):
        """Lines 172-173: resolved path matches blocked pattern → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            # Construct a __pycache__ path inside base_dir
            blocked = str(Path(tmpdir) / "__pycache__" / "module.pyc")
            result = sm.can_read(blocked)
        assert result is False

    def test_path_outside_base_dir_returns_false(self):
        """Lines 175-177: path not under base_dir → False + warning."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            # /var/log is outside the tmpdir
            result = sm.can_read("/var/log/messages")
        assert result is False

    def test_path_inside_base_dir_returns_true(self):
        """can_read: path inside base_dir and not blocked → True."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
            valid = str(Path(tmpdir) / "data" / "file.txt")
            result = sm.can_read(valid)
        assert result is True

    def test_empty_path_allowed(self):
        """can_read with empty string → True (early return)."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
            assert sm.can_read("") is True

    def test_dangerous_path_rejected(self):
        """can_read with dangerous path → False (lines 163-165)."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            assert sm.can_read("/proc/self/maps") is False


# ══════════════════════════════════════════════════════════════
# can_write — lines 208, 211-212, 226-230
# ══════════════════════════════════════════════════════════════

class TestCanWrite:
    def test_resolve_safe_none_returns_false(self):
        """Line 208: _resolve_safe returns None → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            with patch.object(sec.SecurityManager, "_resolve_safe", return_value=None):
                result = sm.can_write("/some/path")
        assert result is False

    def test_blocked_path_returns_false(self):
        """Lines 211-212: resolved path is blocked → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            blocked = str(Path(tmpdir) / ".env")
            result = sm.can_write(blocked)
        assert result is False

    def test_full_mode_outside_base_dir_returns_false(self):
        """Lines 226-230: FULL mode, path outside base_dir → False with warning."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            # /var/log/app.log is outside tmpdir
            result = sm.can_write("/var/log/app.log")
        assert result is False

    def test_full_mode_inside_base_dir_returns_true(self):
        """Lines 223-225: FULL mode, path inside base_dir → True."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            valid = str(Path(tmpdir) / "subdir" / "output.txt")
            result = sm.can_write(valid)
        assert result is True

    def test_sandbox_mode_in_temp_dir_returns_true(self):
        """Lines 214-219: SANDBOX, path in temp → True."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            temp_file = str(sm.temp_dir / "data.txt")
            result = sm.can_write(temp_file)
        assert result is True

    def test_sandbox_mode_outside_temp_returns_false(self):
        """Lines 219-220: SANDBOX, path outside temp → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            outside_temp = str(Path(tmpdir) / "outside.txt")
            result = sm.can_write(outside_temp)
        assert result is False

    def test_whitespace_only_path_returns_false(self):
        """Line 198-199: path is only whitespace → False."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            result = sm.can_write("   ")
        assert result is False

    def test_dangerous_pattern_returns_false(self):
        """Lines 202-204: dangerous pattern → False + warning."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            result = sm.can_write("../../etc/crontab")
        assert result is False


# ══════════════════════════════════════════════════════════════
# set_level additional paths
# ══════════════════════════════════════════════════════════════

class TestSetLevel:
    def test_set_level_to_restricted(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            changed = sm.set_level("restricted")
        assert changed is True
        assert sm.level == sec.RESTRICTED
        assert sm.level_name == "restricted"

    def test_set_level_to_full(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
            changed = sm.set_level("full")
        assert changed is True
        assert sm.level == sec.FULL

    def test_set_level_same_returns_false(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
            changed = sm.set_level("full")
        assert changed is False


# ══════════════════════════════════════════════════════════════
# status_report for all levels
# ══════════════════════════════════════════════════════════════

class TestStatusReportAllLevels:
    def test_restricted_status_report(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="restricted", base_dir=Path(tmpdir))
        report = sm.status_report()
        assert "RESTRICTED" in report
        assert "✗" in report  # no write, no terminal, no shell

    def test_sandbox_status_report(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
        report = sm.status_report()
        assert "SANDBOX" in report
        assert "/temp" in report

    def test_full_status_report(self):
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="full", base_dir=Path(tmpdir))
        report = sm.status_report()
        assert "FULL" in report
        assert "git" in report or "Shell" in report

    def test_get_safe_write_path_strips_directory_traversal(self):
        """get_safe_write_path: only uses filename component (no path traversal)."""
        sec = _get_sec()
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = sec.SecurityManager(access_level="sandbox", base_dir=Path(tmpdir))
            # Even if caller passes a relative path, only the name is used
            path = sm.get_safe_write_path("subdir/output.txt")
        assert path.name == "output.txt"
        assert path.parent == sm.temp_dir
