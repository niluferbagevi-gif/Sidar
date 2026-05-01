from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.browser_manager import BrowserManager, BrowserSession
from managers.code_manager import CodeManager
from managers.github_manager import GitHubManager
from managers.security import SecurityManager


class _FakeBrowserProvider:
    provider_name = "fake"

    def start_session(self, manager, browser_name, headless):
        return BrowserSession(
            session_id="sess-1",
            provider=self.provider_name,
            browser_name=browser_name,
            headless=headless,
            started_at=0.0,
            current_url="",
        )

    def goto(self, manager, session, url):
        session.current_url = url

    def click(self, manager, session, selector):
        return None

    def fill(self, manager, session, selector, value, *, clear):
        return None

    def select(self, manager, session, selector, value):
        return None

    def capture_dom(self, manager, session, selector):
        return "<div>ok</div>"

    def capture_screenshot(self, manager, session, path, *, full_page):
        Path(path).write_bytes(b"img")

    def close(self, manager, session):
        return None

    def current_url(self, session):
        return session.current_url


@pytest.mark.integration
def test_code_manager_file_roundtrip_smoke(tmp_path: Path) -> None:
    cfg = SimpleNamespace(BASE_DIR=str(tmp_path), ACCESS_LEVEL="full", ENABLE_LSP=False)
    security = SecurityManager(cfg=cfg, access_level="full")
    manager = CodeManager(security=security, base_dir=tmp_path, cfg=cfg)

    ok_w, msg_w = manager.write_file("demo.txt", "hello integration")
    ok_r, msg_r = manager.read_file("demo.txt")

    assert ok_w is True
    assert ok_r is True
    assert "hello integration" in msg_r
    assert "başarı" in msg_w.lower() or "write" in msg_w.lower()


@pytest.mark.integration
def test_github_manager_degrades_without_token() -> None:
    gh = GitHubManager(token="", repo_name="", require_token=False)
    assert gh.is_available() is False

    ok, msg = gh.list_commits(3)
    assert ok is False
    assert "GitHub" in msg


@pytest.mark.integration
def test_browser_manager_session_lifecycle_with_fake_provider(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        BROWSER_PROVIDER="fake",
        BROWSER_HEADLESS=True,
        BROWSER_TIMEOUT_MS=1000,
        BROWSER_VISUAL_QA_ENABLED=False,
        BROWSER_VISUAL_QA_DRIFT_THRESHOLD=0.015,
        BROWSER_VISUAL_QA_MULTIMODAL_MARGIN=0.005,
        BROWSER_ALLOWED_DOMAINS=[],
    )
    manager = BrowserManager(config=cfg)
    manager._browser_providers = {"fake": _FakeBrowserProvider()}

    ok_start, payload = manager.start_session(browser_name="chromium", headless=True)
    assert ok_start is True
    sid = payload["session_id"]

    ok_nav, nav_msg = manager.goto_url(sid, "https://example.com")
    assert ok_nav is True
    assert "https://example.com" in nav_msg

    ok_close, close_msg = manager.close_session(sid)
    assert ok_close is True
    assert "kapatıldı" in close_msg.lower()
