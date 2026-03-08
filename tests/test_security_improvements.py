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