"""
Sidar Project - Tarayıcı Otomasyon Yöneticisi
Playwright öncelikli, Selenium fallback'li dinamik web etkileşim katmanı.
"""

from __future__ import annotations

import logging
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class BrowserSession:
    session_id: str
    provider: str
    browser_name: str
    headless: bool
    started_at: float
    page: Any = None
    browser: Any = None
    context: Any = None
    driver: Any = None
    runtime: Any = None


class BrowserManager:
    """Dinamik tarayıcı otomasyon işlemlerini güvenli ve sağlayıcıdan bağımsız yönetir."""

    def __init__(self, config: Config | None = None) -> None:
        self.cfg = config or Config()
        self.provider = str(getattr(self.cfg, "BROWSER_PROVIDER", "auto") or "auto").strip().lower()
        self.default_headless = bool(getattr(self.cfg, "BROWSER_HEADLESS", True))
        self.timeout_ms = int(getattr(self.cfg, "BROWSER_TIMEOUT_MS", 15_000) or 15_000)
        self.allowed_domains = {
            domain.strip().lower()
            for domain in (getattr(self.cfg, "BROWSER_ALLOWED_DOMAINS", []) or [])
            if str(domain).strip()
        }
        self.artifact_dir = Path(tempfile.gettempdir()) / "sidar_browser_artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, BrowserSession] = {}

    def _provider_candidates(self) -> list[str]:
        if self.provider == "auto":
            return ["playwright", "selenium"]
        return [self.provider]

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Yalnızca http/https URL'leri desteklenir.")
        host = (parsed.hostname or "").lower()
        if not host:
            raise ValueError("Geçersiz URL.")
        if self.allowed_domains and host not in self.allowed_domains:
            raise ValueError(f"Alan adı allowlist dışında: {host}")

    def _require_session(self, session_id: str) -> BrowserSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Tarayıcı oturumu bulunamadı: {session_id}")
        return session

    def _start_playwright_session(self, browser_name: str, headless: bool) -> BrowserSession:
        from playwright.sync_api import sync_playwright

        runtime = sync_playwright().start()
        launcher = getattr(runtime, browser_name, None)
        if launcher is None:
            runtime.stop()
            raise ValueError(f"Playwright browser tipi desteklenmiyor: {browser_name}")

        browser = launcher.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return BrowserSession(
            session_id=str(uuid.uuid4()),
            provider="playwright",
            browser_name=browser_name,
            headless=headless,
            started_at=time.time(),
            page=page,
            browser=browser,
            context=context,
            runtime=runtime,
        )

    def _start_selenium_session(self, browser_name: str, headless: bool) -> BrowserSession:
        from selenium import webdriver

        if browser_name not in {"chrome", "chromium", "firefox"}:
            raise ValueError(f"Selenium browser tipi desteklenmiyor: {browser_name}")

        if browser_name in {"chrome", "chromium"}:
            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
            driver = webdriver.Chrome(options=options)
        else:
            options = webdriver.FirefoxOptions()
            if headless:
                options.add_argument("-headless")
            driver = webdriver.Firefox(options=options)

        driver.set_page_load_timeout(max(5, self.timeout_ms // 1000))
        return BrowserSession(
            session_id=str(uuid.uuid4()),
            provider="selenium",
            browser_name=browser_name,
            headless=headless,
            started_at=time.time(),
            driver=driver,
        )

    def is_available(self) -> bool:
        for candidate in self._provider_candidates():
            try:
                if candidate == "playwright":
                    import playwright.sync_api  # noqa: F401

                    return True
                if candidate == "selenium":
                    import selenium  # noqa: F401

                    return True
            except Exception:
                continue
        return False

    def status(self) -> str:
        active = len(self._sessions)
        return (
            f"BrowserManager: provider={self.provider} "
            f"available={'yes' if self.is_available() else 'no'} active_sessions={active}"
        )

    def start_session(self, browser_name: str = "chromium", headless: bool | None = None) -> tuple[bool, dict[str, Any]]:
        headless_value = self.default_headless if headless is None else bool(headless)
        last_error = "Tarayıcı sağlayıcısı başlatılamadı."

        for candidate in self._provider_candidates():
            try:
                if candidate == "playwright":
                    session = self._start_playwright_session(browser_name, headless_value)
                elif candidate == "selenium":
                    session = self._start_selenium_session(browser_name, headless_value)
                else:
                    last_error = f"Desteklenmeyen browser provider: {candidate}"
                    continue

                self._sessions[session.session_id] = session
                return True, {
                    "session_id": session.session_id,
                    "provider": session.provider,
                    "browser": session.browser_name,
                    "headless": session.headless,
                }
            except Exception as exc:
                logger.warning("Browser provider başlatılamadı (%s): %s", candidate, exc)
                last_error = str(exc)

        return False, {"error": last_error}

    def goto_url(self, session_id: str, url: str) -> tuple[bool, str]:
        self._validate_url(url)
        session = self._require_session(session_id)

        if session.provider == "playwright":
            session.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            return True, f"Açıldı: {url}"

        session.driver.get(url)
        return True, f"Açıldı: {url}"

    def click_element(self, session_id: str, selector: str) -> tuple[bool, str]:
        session = self._require_session(session_id)
        if session.provider == "playwright":
            session.page.click(selector, timeout=self.timeout_ms)
            return True, f"Tıklandı: {selector}"

        from selenium.webdriver.common.by import By

        session.driver.find_element(By.CSS_SELECTOR, selector).click()
        return True, f"Tıklandı: {selector}"

    def fill_form(self, session_id: str, selector: str, value: str, clear: bool = True) -> tuple[bool, str]:
        session = self._require_session(session_id)
        if session.provider == "playwright":
            if clear:
                session.page.fill(selector, value, timeout=self.timeout_ms)
            else:
                session.page.type(selector, value, timeout=self.timeout_ms)
            return True, f"Form dolduruldu: {selector}"

        from selenium.webdriver.common.by import By

        element = session.driver.find_element(By.CSS_SELECTOR, selector)
        if clear:
            element.clear()
        element.send_keys(value)
        return True, f"Form dolduruldu: {selector}"

    def select_option(self, session_id: str, selector: str, value: str) -> tuple[bool, str]:
        session = self._require_session(session_id)
        if session.provider == "playwright":
            session.page.select_option(selector, value=value, timeout=self.timeout_ms)
            return True, f"Seçim yapıldı: {selector}={value}"

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.select import Select

        Select(session.driver.find_element(By.CSS_SELECTOR, selector)).select_by_value(value)
        return True, f"Seçim yapıldı: {selector}={value}"

    def capture_dom(self, session_id: str, selector: str = "html") -> tuple[bool, str]:
        session = self._require_session(session_id)
        if session.provider == "playwright":
            return True, session.page.locator(selector).inner_html(timeout=self.timeout_ms)
        return True, session.driver.page_source

    def capture_screenshot(
        self,
        session_id: str,
        file_name: str | None = None,
        full_page: bool = True,
    ) -> tuple[bool, str]:
        session = self._require_session(session_id)
        target_name = file_name or f"{session.session_id}.png"
        target = (self.artifact_dir / target_name).resolve()

        if session.provider == "playwright":
            session.page.screenshot(path=str(target), full_page=full_page)
        else:
            session.driver.save_screenshot(str(target))

        return True, str(target)

    def close_session(self, session_id: str) -> tuple[bool, str]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False, f"Tarayıcı oturumu bulunamadı: {session_id}"

        try:
            if session.provider == "playwright":
                if session.context is not None:
                    session.context.close()
                if session.browser is not None:
                    session.browser.close()
                if session.runtime is not None:
                    session.runtime.stop()
            elif session.driver is not None:
                session.driver.quit()
        except Exception as exc:
            logger.warning("Tarayıcı oturumu kapatılırken hata: %s", exc)
            return False, f"Oturum kapatılırken hata: {exc}"

        return True, f"Tarayıcı oturumu kapatıldı: {session_id}"
