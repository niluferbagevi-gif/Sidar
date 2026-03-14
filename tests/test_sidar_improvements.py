# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from pathlib import Path


def test_test_sidar_web_search_status_tests_use_monkeypatch_for_ddg():
    src = Path("tests/test_sidar.py").read_text(encoding="utf-8")
    assert "def test_web_search_status_without_engines_is_deterministic" in src
    assert "def test_web_search_status_with_ddg_available_is_deterministic" in src
    assert "monkeypatch.setattr(WebSearchManager, \"_check_ddg\"" in src