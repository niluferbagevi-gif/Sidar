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