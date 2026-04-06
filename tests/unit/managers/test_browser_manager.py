from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from managers.browser_manager import BrowserManager, BrowserSession


@pytest.fixture()
def manager(tmp_path):
    cfg = SimpleNamespace(
        BROWSER_PROVIDER="auto",
        BROWSER_HEADLESS=True,
        BROWSER_TIMEOUT_MS=1234,
        BROWSER_ALLOWED_DOMAINS=["Example.com", "", " allowed.org "],
    )
    m = BrowserManager(cfg)
    m.artifact_dir = tmp_path
    return m


def _mk_session(provider: str = "playwright"):
    if provider == "playwright":
        page = SimpleNamespace(
            url="https://example.com",
            goto=lambda *a, **k: None,
            click=lambda *a, **k: None,
            fill=lambda *a, **k: None,
            type=lambda *a, **k: None,
            select_option=lambda *a, **k: None,
            locator=lambda _s: SimpleNamespace(inner_html=lambda **_k: "<body>x</body>"),
            screenshot=lambda **_k: None,
        )
        return BrowserSession(
            session_id="s1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=0.0,
            page=page,
            context=SimpleNamespace(close=lambda: None),
            browser=SimpleNamespace(close=lambda: None),
            runtime=SimpleNamespace(stop=lambda: None),
        )
    drv = SimpleNamespace(
        current_url="https://allowed.org",
        get=lambda _u: None,
        find_element=lambda *_a, **_k: SimpleNamespace(
            click=lambda: None,
            clear=lambda: None,
            send_keys=lambda _v: None,
        ),
        page_source="<html/>",
        save_screenshot=lambda _p: None,
        quit=lambda: None,
        set_page_load_timeout=lambda _t: None,
    )
    return BrowserSession(
        session_id="s2",
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=0.0,
        driver=drv,
    )


def test_helpers_and_validation(manager):
    assert manager.allowed_domains == {"example.com", "allowed.org"}
    assert manager._is_high_risk_click("button[type=submit]")
    assert not manager._is_high_risk_click("#menu")
    assert manager._summarize_value("") == ""
    assert manager._summarize_value("1234") == "****"
    assert manager._summarize_value("abcdefghij").startswith("ab***ij")

    manager._validate_url("https://example.com/x")
    with pytest.raises(ValueError):
        manager._validate_url("ftp://example.com")
    with pytest.raises(ValueError):
        manager._validate_url("https://not-allowed.net")


def test_hitl_guard_and_audit_summary(monkeypatch, manager):
    gate = SimpleNamespace(enabled=True)
    monkeypatch.setattr("managers.browser_manager.get_hitl_gate", lambda: gate)

    assert manager._sync_hitl_guard("browser_click", "#menu") is None
    blocked = manager._sync_hitl_guard("browser_click", "submit")
    assert blocked and blocked[0] is False

    manager._record_audit_event(session_id="s1", action="browser_click", status="execution_failed", selector="#x")
    manager._record_audit_event(session_id="s1", action="browser_fill_form", status="pending_approval", selector="input")
    manager._record_audit_event(session_id="s1", action="browser_click", status="executed", selector="submit")
    summary = manager.summarize_audit_log("s1", limit=2)
    assert summary["risk"] == "yüksek"
    assert "browser_click:#x" in summary["failed_actions"]
    assert summary["entry_count"] == 3
    assert len(summary["recent_entries"]) == 2


def test_start_session_fallback_and_status(monkeypatch, manager):
    monkeypatch.setattr(manager, "_provider_candidates", lambda: ["invalid", "playwright"])
    monkeypatch.setattr(
        manager,
        "_start_playwright_session",
        lambda _b, _h: BrowserSession(
            session_id="sess-ok",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=0,
            page=SimpleNamespace(url=""),
        ),
    )
    ok, payload = manager.start_session()
    assert ok and payload["session_id"] == "sess-ok"
    assert manager.status().startswith("BrowserManager")


def test_start_session_failure_records_audit(monkeypatch, manager):
    monkeypatch.setattr(manager, "_provider_candidates", lambda: ["playwright"])
    monkeypatch.setattr(manager, "_start_playwright_session", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    ok, payload = manager.start_session()
    assert not ok and payload["error"] == "boom"
    assert any(e["session_id"] == "startup:playwright" for e in manager.list_audit_log())


def test_goto_and_capture_and_collect_signals(manager):
    session = _mk_session("playwright")
    manager._sessions[session.session_id] = session

    ok, msg = manager.goto_url("s1", "https://example.com/home")
    assert ok and "Açıldı" in msg
    ok, dom = manager.capture_dom("s1")
    assert ok and "<body>" in dom
    ok, path = manager.capture_screenshot("s1", "shot.png")
    assert ok and path.endswith("shot.png")

    signals = manager.collect_session_signals("s1", include_dom=True, include_screenshot=True)
    assert signals["provider"] == "playwright"
    assert signals["dom_capture"]["ok"] is True
    assert signals["screenshot"]["ok"] is True


def test_goto_url_failure_and_capture_dom_failure(manager):
    session = _mk_session("playwright")
    session.page.goto = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("nav err"))
    session.page.locator = lambda _s: SimpleNamespace(inner_html=lambda **_k: (_ for _ in ()).throw(RuntimeError("dom err")))
    manager._sessions[session.session_id] = session

    with pytest.raises(RuntimeError):
        manager.goto_url("s1", "https://example.com")
    ok, msg = manager.capture_dom("s1")
    assert not ok and "DOM yakalama hatası" in msg


def test_click_fill_select_block_execute_and_fail(monkeypatch, manager):
    session = _mk_session("playwright")
    manager._sessions[session.session_id] = session

    monkeypatch.setattr(manager, "_sync_hitl_guard", lambda *_a, **_k: (False, "blocked"))
    assert manager.click_element("s1", "submit")[0] is False
    assert manager.fill_form("s1", "input", "x")[0] is False
    assert manager.select_option("s1", "select", "1")[0] is False

    monkeypatch.setattr(manager, "_sync_hitl_guard", lambda *_a, **_k: None)
    assert manager.click_element("s1", "#ok")[0] is True
    assert manager.fill_form("s1", "#in", "value", clear=False)[0] is True
    assert manager.select_option("s1", "#sel", "v")[0] is True

    monkeypatch.setattr(manager, "_click_element_impl", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("click err")))
    with pytest.raises(RuntimeError):
        manager.click_element("s1", "#bad")


def test_async_hitl_paths(monkeypatch, manager):
    session = _mk_session("playwright")
    manager._sessions[session.session_id] = session

    monkeypatch.setattr(manager, "_request_hitl_approval", lambda **_k: asyncio.sleep(0, result=False))
    ok, _ = asyncio.run(manager.click_element_hitl("s1", "submit", require_confirmation=True))
    assert ok is False

    monkeypatch.setattr(manager, "_request_hitl_approval", lambda **_k: asyncio.sleep(0, result=True))
    ok, _ = asyncio.run(manager.fill_form_hitl("s1", "#in", "secret"))
    assert ok is True
    ok, _ = asyncio.run(manager.select_option_hitl("s1", "#sel", "2"))
    assert ok is True


def test_close_session_paths(manager):
    assert manager.close_session("missing")[0] is False

    p = _mk_session("playwright")
    manager._sessions[p.session_id] = p
    assert manager.close_session("s1")[0] is True

    bad = _mk_session("playwright")
    bad.context = SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("close err")))
    manager._sessions[bad.session_id] = bad
    ok, msg = manager.close_session("s1")
    assert not ok and "Oturum kapatılırken hata" in msg


def test_selenium_provider_branches(manager, monkeypatch):
    session = _mk_session("selenium")
    manager._sessions[session.session_id] = session

    ok, _ = manager.goto_url("s2", "https://allowed.org")
    assert ok
    assert manager.capture_dom("s2")[0] is True
    assert manager.capture_screenshot("s2", "sel.png")[0] is True

    fake_selects: list[str] = []

    class FakeSelect:
        def __init__(self, _elem):
            pass

        def select_by_value(self, value):
            fake_selects.append(value)

    selenium_mod = ModuleType("selenium")
    webdriver_mod = ModuleType("selenium.webdriver")
    common_mod = ModuleType("selenium.webdriver.common")
    by_mod = ModuleType("selenium.webdriver.common.by")
    support_mod = ModuleType("selenium.webdriver.support")
    select_mod = ModuleType("selenium.webdriver.support.select")
    by_mod.By = SimpleNamespace(CSS_SELECTOR="css")
    select_mod.Select = FakeSelect

    monkeypatch.setitem(sys.modules, "selenium", selenium_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver", webdriver_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.common", common_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.common.by", by_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support", support_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support.select", select_mod)

    assert manager.select_option("s2", "#country", "tr")[0] is True
    assert fake_selects == ["tr"]
