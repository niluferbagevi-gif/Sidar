"""
tests/test_managers_security.py
================================
managers/security.py — SecurityManager (OpenClaw) birim testleri.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

import pytest


def _fresh():
    """managers.security'yi managers.__init__ zinciri olmadan yükle."""
    # managers paketini stub'la — browser_manager, code_manager vb. ağır dep'leri tetiklememek için
    stub_managers = sys.modules.get("managers") or types.ModuleType("managers")
    sys.modules.setdefault("managers", stub_managers)
    sys.modules.pop("managers.security", None)
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "managers.security",
        os.path.join(os.path.dirname(__file__), "..", "managers", "security.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["managers.security"] = mod
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# Sabitler & modül-seviyesi değerler
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurityConstants:
    def setup_method(self):
        self.mod = _fresh()

    def test_seviye_sabitleri(self):
        assert self.mod.RESTRICTED == 0
        assert self.mod.SANDBOX == 1
        assert self.mod.FULL == 2

    def test_level_names_sozlugu(self):
        assert "restricted" in self.mod.LEVEL_NAMES
        assert "sandbox" in self.mod.LEVEL_NAMES
        assert "full" in self.mod.LEVEL_NAMES


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_level_name
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeLevelName:
    def setup_method(self):
        self.mod = _fresh()

    def test_gecerli_seviyeler(self):
        assert self.mod.SecurityManager._normalize_level_name("full") == "full"
        assert self.mod.SecurityManager._normalize_level_name("sandbox") == "sandbox"
        assert self.mod.SecurityManager._normalize_level_name("restricted") == "restricted"

    def test_buyuk_harf_normalizar(self):
        assert self.mod.SecurityManager._normalize_level_name("FULL") == "full"
        assert self.mod.SecurityManager._normalize_level_name("SANDBOX") == "sandbox"

    def test_bilinmeyen_seviye_sandbox_doner(self):
        assert self.mod.SecurityManager._normalize_level_name("admin") == "sandbox"
        assert self.mod.SecurityManager._normalize_level_name("") == "sandbox"

    def test_none_benzeri_bos_string_sandbox(self):
        assert self.mod.SecurityManager._normalize_level_name("   ") == "sandbox"


# ─────────────────────────────────────────────────────────────────────────────
# _has_dangerous_pattern
# ─────────────────────────────────────────────────────────────────────────────

class TestHasDangerousPattern:
    def setup_method(self):
        self.mod = _fresh()
        self.check = self.mod.SecurityManager._has_dangerous_pattern

    def test_path_traversal_tespit(self):
        assert self.check("../../etc/passwd") is True
        assert self.check("..\\windows\\system32") is True

    def test_etc_yolu_tehlikeli(self):
        assert self.check("/etc/passwd") is True
        assert self.check("/etc/shadow") is True

    def test_proc_yolu_tehlikeli(self):
        assert self.check("/proc/self/mem") is True

    def test_sys_yolu_tehlikeli(self):
        assert self.check("/sys/kernel/boot_params") is True

    def test_windows_yolu_tehlikeli(self):
        assert self.check("C:/windows/system32") is True
        assert self.check("C:/Program Files/malware") is True

    def test_guvenli_yol_tehlikeli_degil(self):
        assert self.check("/home/user/project/file.py") is False
        assert self.check("data/output.txt") is False


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_safe
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveSafe:
    def setup_method(self):
        self.mod = _fresh()
        self.resolve = self.mod.SecurityManager._resolve_safe

    def test_gecerli_yol_cozumler(self, tmp_path):
        result = self.resolve(str(tmp_path))
        assert result is not None
        assert isinstance(result, Path)

    def test_hatada_none_doner(self):
        # Path() None geçilirse hata
        result = self.resolve("\x00invalid\x00path")
        # None veya Path döner; önemli olan exception fırlamaması
        assert result is None or isinstance(result, Path)


# ─────────────────────────────────────────────────────────────────────────────
# SecurityManager.__init__
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurityManagerInit:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()

    def test_full_seviye_olusturulur(self):
        sm = self.mod.SecurityManager(access_level="full", base_dir=Path(self.tmp))
        assert sm.level == self.mod.FULL
        assert sm.level_name == "full"

    def test_sandbox_seviye_olusturulur(self):
        sm = self.mod.SecurityManager(access_level="sandbox", base_dir=Path(self.tmp))
        assert sm.level == self.mod.SANDBOX

    def test_restricted_seviye_olusturulur(self):
        sm = self.mod.SecurityManager(access_level="restricted", base_dir=Path(self.tmp))
        assert sm.level == self.mod.RESTRICTED

    def test_bilinmeyen_seviye_sandbox_olur(self):
        sm = self.mod.SecurityManager(access_level="admin", base_dir=Path(self.tmp))
        assert sm.level == self.mod.SANDBOX

    def test_base_dir_resolve_edilir(self):
        sm = self.mod.SecurityManager(access_level="full", base_dir=Path(self.tmp))
        assert sm.base_dir == Path(self.tmp).resolve()

    def test_temp_dir_olusturulur(self):
        sm = self.mod.SecurityManager(access_level="full", base_dir=Path(self.tmp))
        assert sm.temp_dir.exists()

    def test_repr(self):
        sm = self.mod.SecurityManager(access_level="full", base_dir=Path(self.tmp))
        assert "full" in repr(sm)


# ─────────────────────────────────────────────────────────────────────────────
# is_path_under
# ─────────────────────────────────────────────────────────────────────────────

class TestIsPathUnder:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()
        self.sm = self.mod.SecurityManager(access_level="full", base_dir=Path(self.tmp))

    def test_alt_yol_true(self, tmp_path):
        sub = tmp_path / "sub" / "file.txt"
        assert self.sm.is_path_under(str(sub), tmp_path) is True

    def test_dis_yol_false(self, tmp_path):
        other = Path("/tmp/other_dir_xyz")
        assert self.sm.is_path_under(str(other), tmp_path) is False

    def test_tehlikeli_yol_false(self):
        assert self.sm.is_path_under("../../etc/passwd", Path(self.tmp)) is False


# ─────────────────────────────────────────────────────────────────────────────
# _is_blocked_path
# ─────────────────────────────────────────────────────────────────────────────

class TestIsBlockedPath:
    def setup_method(self):
        self.mod = _fresh()
        self.check = self.mod.SecurityManager._is_blocked_path

    def test_env_dosyasi_bloklu(self):
        assert self.check("/project/.env") is True

    def test_sessions_bloklu(self):
        assert self.check("/project/sessions/data") is True

    def test_git_bloklu(self):
        assert self.check("/project/.git/config") is True

    def test_pycache_bloklu(self):
        assert self.check("/project/__pycache__/module.pyc") is True

    def test_guvenli_dosya_bloklu_degil(self):
        assert self.check("/project/main.py") is False
        assert self.check("/project/config.py") is False


# ─────────────────────────────────────────────────────────────────────────────
# is_safe_path
# ─────────────────────────────────────────────────────────────────────────────

class TestIsSafePath:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()
        self.sm = self.mod.SecurityManager(access_level="full", base_dir=Path(self.tmp))

    def test_proje_dosyasi_guvenli(self):
        safe = Path(self.tmp) / "main.py"
        assert self.sm.is_safe_path(str(safe)) is True

    def test_traversal_guvenli_degil(self):
        assert self.sm.is_safe_path("../../etc/passwd") is False

    def test_bloklu_yol_guvenli_degil(self):
        blocked = Path(self.tmp) / ".env"
        assert self.sm.is_safe_path(str(blocked)) is False

    def test_dis_yol_guvenli_degil(self):
        assert self.sm.is_safe_path("/tmp/outside_xyz") is False


# ─────────────────────────────────────────────────────────────────────────────
# can_read
# ─────────────────────────────────────────────────────────────────────────────

class TestCanRead:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()

    def _sm(self, level):
        return self.mod.SecurityManager(access_level=level, base_dir=Path(self.tmp))

    def test_yol_yok_true_doner(self):
        sm = self._sm("full")
        assert sm.can_read() is True

    def test_none_yol_true_doner(self):
        sm = self._sm("full")
        assert sm.can_read(None) is True

    def test_tehlikeli_yol_reddedilir(self):
        sm = self._sm("full")
        assert sm.can_read("../../etc/passwd") is False

    def test_bloklu_yol_reddedilir(self):
        sm = self._sm("full")
        blocked = str(Path(self.tmp) / ".env")
        assert sm.can_read(blocked) is False

    def test_guvenli_yol_kabul(self):
        sm = self._sm("full")
        safe = str(Path(self.tmp) / "file.py")
        assert sm.can_read(safe) is True

    def test_dis_yol_reddedilir(self):
        sm = self._sm("full")
        assert sm.can_read("/tmp/outside_xyz_abc") is False


# ─────────────────────────────────────────────────────────────────────────────
# can_write
# ─────────────────────────────────────────────────────────────────────────────

class TestCanWrite:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()

    def _sm(self, level):
        return self.mod.SecurityManager(access_level=level, base_dir=Path(self.tmp))

    def test_restricted_her_zaman_false(self):
        sm = self._sm("restricted")
        assert sm.can_write(str(Path(self.tmp) / "file.py")) is False

    def test_bos_yol_false(self):
        sm = self._sm("full")
        assert sm.can_write("") is False
        assert sm.can_write("   ") is False

    def test_full_proje_dosyasi_true(self):
        sm = self._sm("full")
        safe = str(Path(self.tmp) / "output.py")
        assert sm.can_write(safe) is True

    def test_full_dis_yol_false(self):
        sm = self._sm("full")
        assert sm.can_write("/tmp/outside_xyz_abc") is False

    def test_sandbox_temp_altina_true(self):
        sm = self._sm("sandbox")
        temp_file = str(sm.temp_dir / "output.txt")
        assert sm.can_write(temp_file) is True

    def test_sandbox_proje_koku_false(self):
        sm = self._sm("sandbox")
        proje_dosyasi = str(Path(self.tmp) / "main.py")
        assert sm.can_write(proje_dosyasi) is False

    def test_traversal_reddedilir(self):
        sm = self._sm("full")
        assert sm.can_write("../../etc/shadow") is False

    def test_bloklu_yol_reddedilir(self):
        sm = self._sm("full")
        blocked = str(Path(self.tmp) / ".env")
        assert sm.can_write(blocked) is False


# ─────────────────────────────────────────────────────────────────────────────
# can_execute & can_run_shell
# ─────────────────────────────────────────────────────────────────────────────

class TestPermissions:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()

    def _sm(self, level):
        return self.mod.SecurityManager(access_level=level, base_dir=Path(self.tmp))

    def test_restricted_execute_false(self):
        assert self._sm("restricted").can_execute() is False

    def test_sandbox_execute_true(self):
        assert self._sm("sandbox").can_execute() is True

    def test_full_execute_true(self):
        assert self._sm("full").can_execute() is True

    def test_restricted_shell_false(self):
        assert self._sm("restricted").can_run_shell() is False

    def test_sandbox_shell_false(self):
        assert self._sm("sandbox").can_run_shell() is False

    def test_full_shell_true(self):
        assert self._sm("full").can_run_shell() is True


# ─────────────────────────────────────────────────────────────────────────────
# get_safe_write_path
# ─────────────────────────────────────────────────────────────────────────────

class TestGetSafeWritePath:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()
        self.sm = self.mod.SecurityManager(access_level="sandbox", base_dir=Path(self.tmp))

    def test_dosya_adi_temp_altinda(self):
        result = self.sm.get_safe_write_path("output.py")
        assert result.parent == self.sm.temp_dir
        assert result.name == "output.py"

    def test_path_traversal_dosya_adi_temizlenir(self):
        result = self.sm.get_safe_write_path("../../etc/output.py")
        # Path.name → sadece dosya adı bileşeni
        assert result.name == "output.py"


# ─────────────────────────────────────────────────────────────────────────────
# set_level
# ─────────────────────────────────────────────────────────────────────────────

class TestSetLevel:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()
        self.sm = self.mod.SecurityManager(access_level="sandbox", base_dir=Path(self.tmp))

    def test_seviye_degistirilir(self):
        result = self.sm.set_level("full")
        assert result is True
        assert self.sm.level == self.mod.FULL
        assert self.sm.level_name == "full"

    def test_ayni_seviye_false_doner(self):
        result = self.sm.set_level("sandbox")
        assert result is False

    def test_restricted_e_gecis(self):
        self.sm.set_level("restricted")
        assert self.sm.level == self.mod.RESTRICTED


# ─────────────────────────────────────────────────────────────────────────────
# status_report
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusReport:
    def setup_method(self):
        self.mod = _fresh()
        self.tmp = tempfile.mkdtemp()

    def _sm(self, level):
        return self.mod.SecurityManager(access_level=level, base_dir=Path(self.tmp))

    def test_full_rapor_icerigi(self):
        report = self._sm("full").status_report()
        assert "FULL" in report
        assert "Okuma" in report
        assert "Yazma" in report
        assert "Terminal" in report
        assert "Shell" in report

    def test_sandbox_rapor_icerigi(self):
        report = self._sm("sandbox").status_report()
        assert "SANDBOX" in report

    def test_restricted_rapor_icerigi(self):
        report = self._sm("restricted").status_report()
        assert "RESTRICTED" in report

    def test_openclaw_etiketi(self):
        report = self._sm("full").status_report()
        assert "OpenClaw" in report