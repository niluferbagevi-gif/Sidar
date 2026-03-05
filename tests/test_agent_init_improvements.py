from pathlib import Path


def test_agent_init_uses_single_source_export_mapping():
    src = Path("agent/__init__.py").read_text(encoding="utf-8")
    assert "_EXPORTED_AGENT_SYMBOLS = {" in src
    assert "__all__ = list(_EXPORTED_AGENT_SYMBOLS.keys())" in src
    assert "SIDAR_WAKE_WORDS" in src