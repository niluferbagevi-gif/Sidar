from pathlib import Path


def test_search_uses_structured_no_result_marker_instead_of_hata_string_matching():
    src = Path("managers/web_search.py").read_text(encoding="utf-8")
    assert "_NO_RESULTS_PREFIX = \"[NO_RESULTS]\"" in src
    assert "def _is_actionable_result" in src
    assert "def _normalize_result_text" in src
    assert '"[HATA]" not in res' not in src


def test_clean_html_uses_html_unescape_and_result_count_is_safely_clamped():
    src = Path("managers/web_search.py").read_text(encoding="utf-8")
    assert "from html import unescape" in src
    assert "clean = unescape(clean)" in src
    assert "except (TypeError, ValueError):" in src
    assert "n = max(1, min(n, 10))" in src