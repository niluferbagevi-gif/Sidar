from __future__ import annotations

from types import SimpleNamespace

import pytest

from managers.browser_manager import BrowserManager, BrowserSession


class _FakeLocator:
    def inner_html(self, timeout: int):
        assert timeout > 0
        return "<div id='app'>ok</div>"


class _FakePage:
    def __init__(self):
        self.url = ""
        self.clicked = []

    def goto(self, url: str, wait_until: str, timeout: int):
        assert wait_until == "domcontentloaded"
        assert timeout > 0
        self.url = url

    def click(self, selector: str, timeout: int):
        if selector == "#timeout":
            raise TimeoutError("element not found")
        self.clicked.append((selector, timeout))

    def locator(self, selector: str):
        assert selector
        return _FakeLocator()


def _manager(monkeypatch):
    cfg = SimpleNamespace(BROWSER_PROVIDER="playwright", BROWSER_HEADLESS=True, BROWSER_TIMEOUT_MS=1500, BROWSER_ALLOWED_DOMAINS=[])
    mgr = BrowserManager(config=cfg)
    fake_page = _FakePage()

    monkeypatch.setattr(mgr, "_provider_candidates", lambda: ["playwright"])
    monkeypatch.setattr(
        mgr,
        "_start_playwright_session",
        lambda browser_name, headless: BrowserSession(
            session_id="s1",
            provider="playwright",
            browser_name=browser_name,
            headless=headless,
            started_at=0.0,
            page=fake_page,
        ),
    )
    monkeypatch.setattr(mgr, "_sync_hitl_guard", lambda *args, **kwargs: None)
    return mgr


def test_browser_manager_session_goto_click_dom(monkeypatch):
    mgr = _manager(monkeypatch)
    ok, payload = mgr.start_session()
    assert ok is True

    sid = payload["session_id"]
    goto_ok, msg = mgr.goto_url(sid, "https://example.com")
    assert goto_ok is True
    assert "Açıldı" in msg

    click_ok, click_msg = mgr.click_element(sid, "#submit")
    assert click_ok is True
    assert "Tıklandı" in click_msg

    dom_ok, dom = mgr.capture_dom(sid, "#app")
    assert dom_ok is True
    assert "id='app'" in dom


def test_browser_manager_timeout_path(monkeypatch):
    mgr = _manager(monkeypatch)
    ok, payload = mgr.start_session()
    assert ok is True

    with pytest.raises(TimeoutError):
        mgr.click_element(payload["session_id"], "#timeout")
