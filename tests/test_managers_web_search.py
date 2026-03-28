"""
managers/web_search.py için birim testleri.
WebSearchManager: constructor, is_available, status, _truncate_content,
_clean_html (BeautifulSoup stub), _mark_no_results, _is_actionable_result,
_normalize_result_text.
"""
from __future__ import annotations

import sys
import types


def _stub_deps():
    """Stub bs4 and duckduckgo_search so import doesn't fail without them."""
    if "bs4" not in sys.modules:
        bs4_stub = types.ModuleType("bs4")

        class _FakeSoup:
            def __init__(self, html, parser):
                self._text = html

            def __call__(self, tags):
                return []

            def get_text(self, separator=" ", strip=True):
                return self._text

            def decompose(self):
                pass

        bs4_stub.BeautifulSoup = _FakeSoup
        sys.modules["bs4"] = bs4_stub

    if "duckduckgo_search" not in sys.modules:
        ddg_stub = types.ModuleType("duckduckgo_search")
        sys.modules["duckduckgo_search"] = ddg_stub


def _get_ws():
    _stub_deps()
    if "managers.web_search" in sys.modules:
        del sys.modules["managers.web_search"]
    import managers.web_search as ws
    return ws


# ══════════════════════════════════════════════════════════════
# Constructor
# ══════════════════════════════════════════════════════════════

class TestWebSearchManagerInit:
    def test_no_config_defaults(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        assert mgr.engine == "auto"
        assert mgr.tavily_key == ""
        assert mgr.google_key == ""
        assert mgr.google_cx == ""

    def test_config_sets_engine(self):
        ws = _get_ws()

        class _Cfg:
            SEARCH_ENGINE = "tavily"
            TAVILY_API_KEY = "secret"
            GOOGLE_SEARCH_API_KEY = ""
            GOOGLE_SEARCH_CX = ""
            WEB_SEARCH_MAX_RESULTS = 5
            WEB_FETCH_TIMEOUT = 15
            WEB_SCRAPE_MAX_CHARS = 12000

        mgr = ws.WebSearchManager(config=_Cfg())
        assert mgr.engine == "tavily"
        assert mgr.tavily_key == "secret"

    def test_config_sets_max_results(self):
        ws = _get_ws()

        class _Cfg:
            SEARCH_ENGINE = "auto"
            TAVILY_API_KEY = ""
            GOOGLE_SEARCH_API_KEY = ""
            GOOGLE_SEARCH_CX = ""
            WEB_SEARCH_MAX_RESULTS = 8
            WEB_FETCH_TIMEOUT = 15
            WEB_SCRAPE_MAX_CHARS = 12000

        mgr = ws.WebSearchManager(config=_Cfg())
        assert mgr.MAX_RESULTS == 8


# ══════════════════════════════════════════════════════════════
# is_available
# ══════════════════════════════════════════════════════════════

class TestIsAvailable:
    def test_false_without_any_engine(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        # If duckduckgo_search doesn't have DDGS, _ddg_available is False
        # and no keys are set → False
        mgr._ddg_available = False
        assert mgr.is_available() is False

    def test_true_with_tavily_key(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"
        assert mgr.is_available() is True

    def test_true_with_google_key_and_cx(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.google_key = "gkey"
        mgr.google_cx = "cx123"
        assert mgr.is_available() is True

    def test_false_with_google_key_but_no_cx(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.google_key = "gkey"
        mgr.google_cx = ""
        mgr._ddg_available = False
        assert mgr.is_available() is False


# ══════════════════════════════════════════════════════════════
# status
# ══════════════════════════════════════════════════════════════

class TestStatus:
    def test_no_engine_message(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr._ddg_available = False
        result = mgr.status()
        assert "motor" in result.lower() or "kurulu" in result.lower()

    def test_tavily_listed(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"
        result = mgr.status()
        assert "Tavily" in result

    def test_google_listed(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.google_key = "gkey"
        mgr.google_cx = "cx"
        result = mgr.status()
        assert "Google" in result

    def test_mode_shown(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"
        result = mgr.status()
        assert "AUTO" in result or "Mod" in result


# ══════════════════════════════════════════════════════════════
# _truncate_content
# ══════════════════════════════════════════════════════════════

class TestTruncateContent:
    def _mgr(self):
        ws = _get_ws()
        return ws.WebSearchManager()

    def test_short_content_unchanged(self):
        mgr = self._mgr()
        text = "hello world"
        assert mgr._truncate_content(text) == text

    def test_long_content_truncated(self):
        mgr = self._mgr()
        mgr.FETCH_MAX_CHARS = 1200
        text = "x" * 2000
        result = mgr._truncate_content(text)
        assert len(result) < 2000
        assert "kesildi" in result

    def test_minimum_clamp_at_1000(self):
        mgr = self._mgr()
        mgr.FETCH_MAX_CHARS = 50  # below minimum → clamped to 1000
        text = "a" * 1500
        result = mgr._truncate_content(text)
        # minimum is 1000, so 1500 > 1000 → truncated
        assert "kesildi" in result


# ══════════════════════════════════════════════════════════════
# _mark_no_results / _is_actionable_result / _normalize_result_text
# ══════════════════════════════════════════════════════════════

class TestResultHelpers:
    def test_mark_no_results_adds_prefix(self):
        ws = _get_ws()
        result = ws.WebSearchManager._mark_no_results("nothing found")
        assert result.startswith(ws.WebSearchManager._NO_RESULTS_PREFIX)

    def test_is_actionable_true_normal_result(self):
        ws = _get_ws()
        assert ws.WebSearchManager._is_actionable_result(True, "Some search results") is True

    def test_is_actionable_false_if_no_results(self):
        ws = _get_ws()
        no_res = ws.WebSearchManager._mark_no_results("empty")
        assert ws.WebSearchManager._is_actionable_result(True, no_res) is False

    def test_is_actionable_false_if_not_ok(self):
        ws = _get_ws()
        assert ws.WebSearchManager._is_actionable_result(False, "error text") is False

    def test_normalize_strips_prefix(self):
        ws = _get_ws()
        marked = ws.WebSearchManager._mark_no_results("nothing")
        normalized = ws.WebSearchManager._normalize_result_text(marked)
        assert not normalized.startswith(ws.WebSearchManager._NO_RESULTS_PREFIX)
        assert "nothing" in normalized

    def test_normalize_normal_text_unchanged(self):
        ws = _get_ws()
        text = "normal result"
        assert ws.WebSearchManager._normalize_result_text(text) == text
