import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_browser_manager_module():
    spec = importlib.util.spec_from_file_location(
        "browser_manager_test_mod",
        Path("managers/browser_manager.py"),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BM_MOD = _load_browser_manager_module()


class _Config:
    BROWSER_PROVIDER = "playwright"
    BROWSER_HEADLESS = True
    BROWSER_TIMEOUT_MS = 5000
    BROWSER_ALLOWED_DOMAINS = ["example.com"]


def test_browser_manager_playwright_flow(monkeypatch, tmp_path):
    manager = BM_MOD.BrowserManager(_Config())
    manager.artifact_dir = tmp_path
    calls = []

    class _Locator:
        def inner_html(self, timeout):
            calls.append(("inner_html", timeout))
            return "<main>ok</main>"

    class _Page:
        def goto(self, url, wait_until, timeout):
            calls.append(("goto", url, wait_until, timeout))

        def click(self, selector, timeout):
            calls.append(("click", selector, timeout))

        def fill(self, selector, value, timeout):
            calls.append(("fill", selector, value, timeout))

        def select_option(self, selector, value, timeout):
            calls.append(("select", selector, value, timeout))

        def locator(self, selector):
            calls.append(("locator", selector))
            return _Locator()

        def screenshot(self, path, full_page):
            Path(path).write_bytes(b"png")
            calls.append(("screenshot", path, full_page))

    class _Closable:
        def __init__(self, label):
            self.label = label

        def close(self):
            calls.append(("close", self.label))

    runtime = SimpleNamespace(stop=lambda: calls.append(("stop", "runtime")))
    fake_session = BM_MOD.BrowserSession(
        session_id="sess-1",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        browser=_Closable("browser"),
        context=_Closable("context"),
        runtime=runtime,
    )

    monkeypatch.setattr(manager, "_start_playwright_session", lambda *_args, **_kwargs: fake_session)

    ok, payload = manager.start_session()
    assert ok is True
    assert payload["session_id"] == "sess-1"

    assert manager.goto_url("sess-1", "https://example.com")[0] is True
    assert manager.click_element("sess-1", "#submit")[0] is True
    assert manager.fill_form("sess-1", "#name", "Sidar")[0] is True
    assert manager.select_option("sess-1", "#priority", "high")[0] is True

    ok, dom = manager.capture_dom("sess-1")
    assert ok is True
    assert "<main>ok</main>" == dom

    ok, screenshot_path = manager.capture_screenshot("sess-1", "page.png")
    assert ok is True
    assert Path(screenshot_path).exists()

    ok, message = manager.close_session("sess-1")
    assert ok is True
    assert "kapatıldı" in message
    assert ("goto", "https://example.com", "domcontentloaded", 5000) in calls
    assert ("close", "context") in calls
    assert ("close", "browser") in calls
    assert ("stop", "runtime") in calls


def test_browser_manager_rejects_urls_outside_allowlist():
    manager = BM_MOD.BrowserManager(_Config())

    with pytest.raises(ValueError):
        manager._validate_url("https://openai.com")