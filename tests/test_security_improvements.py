import importlib.util
import sys
import types
from types import SimpleNamespace

from pathlib import Path


def test_access_level_is_normalized_to_known_values():
    src = Path("managers/security.py").read_text(encoding="utf-8")
    assert "def _normalize_level_name" in src
    assert "if level not in LEVEL_NAMES:" in src
    assert "return \"sandbox\"" in src


def test_write_guard_handles_empty_paths_and_windows_system_prefixes():
    src = Path("managers/security.py").read_text(encoding="utf-8")
    assert "if not path or not path.strip():" in src
    assert "windows|program files" in src
    assert "base = base.resolve()" in src

def test_security_manager_blocks_sensitive_runtime_paths():
    src = Path("managers/security.py").read_text(encoding="utf-8")
    assert "_BLOCKED_PATTERNS" in src
    assert r"\.env" in src
    assert "sessions" in src
    assert r"\.git" in src
    assert "__pycache__" in src


def test_security_manager_supports_config_based_initialization_and_safe_path_api():
    src = Path("managers/security.py").read_text(encoding="utf-8")
    assert "cfg: Optional[Config] = None" in src
    assert "self.base_dir: Path = Path(raw_base_dir).resolve()" in src
    assert "def is_safe_path(self, path_str: str) -> bool:" in src
    assert "except Exception:" in src
    assert "return False" in src


def test_sidar_agent_uses_config_driven_security_manager_init():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8", errors="replace")
    assert "self.security = SecurityManager(cfg=self.cfg)" in src

def test_security_manager_dynamic_level_change():
    src = Path("managers/security.py").read_text(encoding="utf-8")
    assert "def set_level(" in src
    assert "self.level = LEVEL_NAMES[normalized]" in src


def test_agent_dynamic_level_logs_to_memory():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8")
    assert "def set_access_level(" in src
    assert "[GÜVENLİK BİLDİRİMİ]" in src


def test_security_windows_like_paths_runtime(tmp_path):
    cfg = SimpleNamespace(BASE_DIR=tmp_path, ACCESS_LEVEL="sandbox")
    sec_mod = _load_security_runtime_module()
    sec = sec_mod.SecurityManager(cfg=cfg)

    # Windows benzeri absolute/system yolları güvenli olmamalı
    assert sec.is_safe_path(r"C:\Program Files\app") is False
    assert sec.can_read(r"D:\Secret\File.txt") is False
    assert sec.can_write(r"C:\Windows\System32\config.sys") is False

    # get_safe_write_path yalnızca dosya adını korumalı
    safe_path = sec.get_safe_write_path(r"C:\Windows\System32\config.sys")
    assert str(safe_path).endswith("config.sys")
    assert str(safe_path).startswith(str((tmp_path / "temp").resolve()))


def test_security_symlink_bypass_like_read_guard(tmp_path):
    cfg = SimpleNamespace(BASE_DIR=tmp_path, ACCESS_LEVEL="sandbox")
    sec_mod = _load_security_runtime_module()
    sec = sec_mod.SecurityManager(cfg=cfg)

    outside = tmp_path.parent / "outside_target.txt"
    outside.write_text("x", encoding="utf-8")

    # Base dışına işaret eden bir "realpath" sonucu gibi davranıldığında okuma reddedilmeli
    assert sec.can_read(str(outside)) is False



def _load_security_runtime_module():
    saved = {k: sys.modules.get(k) for k in ("dotenv", "config")}
    try:
        sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

        class _Cfg:
            ACCESS_LEVEL = "sandbox"
            BASE_DIR = Path(".")

        sys.modules["config"] = types.SimpleNamespace(Config=_Cfg)
        spec = importlib.util.spec_from_file_location("security_runtime_under_test", Path("managers/security.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old
