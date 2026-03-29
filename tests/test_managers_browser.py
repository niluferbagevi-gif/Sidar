"""
managers/browser_manager.py için birim testleri.
BrowserManager: _is_high_risk_click, _summarize_value, _validate_url,
constructor, _record_audit_event, summarize_audit_log.
"""
from __future__ import annotations

import sys
import types


def _get_bm():
    # Stub config and core.hitl
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        BROWSER_PROVIDER = "auto"
        BROWSER_HEADLESS = True
        BROWSER_TIMEOUT_MS = 15000
        BROWSER_ALLOWED_DOMAINS = []

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    hitl_stub = types.ModuleType("core.hitl")
    hitl_stub.get_hitl_gate = lambda: None
    sys.modules["core.hitl"] = hitl_stub

    if "managers.browser_manager" in sys.modules:
        del sys.modules["managers.browser_manager"]
    import managers.browser_manager as bm
    return bm


# ══════════════════════════════════════════════════════════════
# _is_high_risk_click
# ══════════════════════════════════════════════════════════════

class TestIsHighRiskClick:
    def test_submit_is_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("submit") is True

    def test_delete_is_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("#delete-button") is True

    def test_confirm_is_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("btn-confirm") is True

    def test_normal_selector_not_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("#next") is False

    def test_empty_not_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("") is False

    def test_publish_is_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("publish-post") is True

    def test_case_insensitive(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("SUBMIT") is True


# ══════════════════════════════════════════════════════════════
# _summarize_value
# ══════════════════════════════════════════════════════════════

class TestSummarizeValue:
    def test_empty_string_returns_empty(self):
        bm = _get_bm()
        assert bm.BrowserManager._summarize_value("") == ""

    def test_short_value_masked(self):
        bm = _get_bm()
        result = bm.BrowserManager._summarize_value("1234")
        assert result == "****"

    def test_long_value_shows_prefix_suffix(self):
        bm = _get_bm()
        result = bm.BrowserManager._summarize_value("supersecretpassword")
        assert "***" in result
        assert "len=" in result

    def test_none_like_empty_handled(self):
        bm = _get_bm()
        result = bm.BrowserManager._summarize_value(None)  # type: ignore
        assert result == ""


# ══════════════════════════════════════════════════════════════
# Constructor
# ══════════════════════════════════════════════════════════════

class TestBrowserManagerInit:
    def test_default_provider_auto(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr.provider == "auto"

    def test_default_headless_true(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr.default_headless is True

    def test_empty_sessions_on_init(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr._sessions == {}

    def test_empty_audit_log_on_init(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr._audit_log == []

    def test_artifact_dir_exists(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr.artifact_dir.exists()


# ══════════════════════════════════════════════════════════════
# _record_audit_event / list_audit_log
# ══════════════════════════════════════════════════════════════

class TestAuditLog:
    def _mgr(self):
        bm = _get_bm()
        return bm.BrowserManager()

    def test_record_adds_entry(self):
        mgr = self._mgr()
        mgr._record_audit_event(
            session_id="s1",
            action="browser_click",
            status="ok",
            selector="#btn",
        )
        assert len(mgr._audit_log) == 1

    def test_record_has_correct_fields(self):
        mgr = self._mgr()
        mgr._record_audit_event(
            session_id="s1",
            action="browser_click",
            status="ok",
            selector="#btn",
        )
        entry = mgr._audit_log[0]
        assert entry["session_id"] == "s1"
        assert entry["action"] == "browser_click"
        assert entry["status"] == "ok"

    def test_list_audit_log_returns_copy(self):
        mgr = self._mgr()
        mgr._record_audit_event(session_id="s1", action="a", status="ok")
        log = mgr.list_audit_log()
        assert isinstance(log, list)
        assert len(log) == 1

    def test_summarize_empty_log(self):
        mgr = self._mgr()
        summary = mgr.summarize_audit_log()
        assert summary["entry_count"] == 0
        assert summary["status"] == "no-signal"

    def test_summarize_with_failed_actions(self):
        mgr = self._mgr()
        mgr._record_audit_event(session_id="s1", action="browser_click", status="failed", selector="#x")
        summary = mgr.summarize_audit_log()
        assert summary["status"] == "failed"
        assert summary["risk"] == "yüksek"


class TestBrowserManagerUnhappyPaths:
    def test_start_session_returns_last_error_when_all_providers_fail(self, monkeypatch):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        monkeypatch.setattr(mgr, "_provider_candidates", lambda: ["playwright", "selenium"])
        monkeypatch.setattr(mgr, "_start_playwright_session", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pw down")))
        monkeypatch.setattr(mgr, "_start_selenium_session", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sel down")))

        ok, payload = mgr.start_session(browser_name="chromium")
        assert ok is False
        assert "sel down" in str(payload.get("error"))
        assert len(mgr._audit_log) >= 2

    def test_goto_url_records_execution_failed_audit_and_raises(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = types.SimpleNamespace(
            session_id="s1",
            provider="playwright",
            page=types.SimpleNamespace(
                goto=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network offline"))
            ),
            current_url="",
        )
        mgr._sessions["s1"] = session

        import pytest
        with pytest.raises(RuntimeError, match="network offline"):
            mgr.goto_url("s1", "https://example.com")

        assert mgr._audit_log[-1]["status"] == "execution_failed"
