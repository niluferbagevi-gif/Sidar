# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from pathlib import Path


def test_agent_init_uses_single_source_export_mapping():
    src = Path("agent/__init__.py").read_text(encoding="utf-8")
    assert "_EXPORTED_AGENT_SYMBOLS = {" in src
    assert "__all__ = list(_EXPORTED_AGENT_SYMBOLS.keys())" in src
    assert "SIDAR_WAKE_WORDS" in src


def test_agent_init_exports_auto_handle_aliases():
    src = Path("agent/__init__.py").read_text(encoding="utf-8")
    assert "from .auto_handle import AutoHandle" in src
    assert "AutoHandler = AutoHandle" in src
    assert '\"AutoHandle\": AutoHandle' in src
    assert '\"AutoHandler\": AutoHandler' in src