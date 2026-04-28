"""
Sidar Project - Tarayıcı Otomasyon Yöneticisi
Playwright öncelikli, Selenium fallback'li dinamik web etkileşim katmanı.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import hashlib
import importlib
import logging
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from config import Config
from core.hitl import get_hitl_gate

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
    current_url: str = ""


class BaseBrowserProvider(abc.ABC):
    provider_name: str

    @abc.abstractmethod
    def start_session(
        self, manager: BrowserManager, browser_name: str, headless: bool
    ) -> BrowserSession:
        """Create and return a browser session."""

    @abc.abstractmethod
    def goto(self, manager: BrowserManager, session: BrowserSession, url: str) -> None:
        """Navigate to target URL."""

    @abc.abstractmethod
    def click(self, manager: BrowserManager, session: BrowserSession, selector: str) -> None:
        """Click element."""

    @abc.abstractmethod
    def fill(
        self,
        manager: BrowserManager,
        session: BrowserSession,
        selector: str,
        value: str,
        *,
        clear: bool,
    ) -> None:
        """Fill form input."""

    @abc.abstractmethod
    def select(
        self, manager: BrowserManager, session: BrowserSession, selector: str, value: str
    ) -> None:
        """Select option."""

    @abc.abstractmethod
    def capture_dom(self, manager: BrowserManager, session: BrowserSession, selector: str) -> str:
        """Capture DOM content."""

    @abc.abstractmethod
    def capture_screenshot(
        self, manager: BrowserManager, session: BrowserSession, path: str, *, full_page: bool
    ) -> None:
        """Capture screenshot."""

    @abc.abstractmethod
    def close(self, manager: BrowserManager, session: BrowserSession) -> None:
        """Close session resources."""

    @abc.abstractmethod
    def current_url(self, session: BrowserSession) -> str:
        """Get provider-native current URL."""


class PlaywrightBrowserProvider(BaseBrowserProvider):
    provider_name = "playwright"

    def start_session(
        self, manager: BrowserManager, browser_name: str, headless: bool
    ) -> BrowserSession:
        from playwright.sync_api import sync_playwright

        runtime = sync_playwright().start()
        launcher = getattr(runtime, browser_name, None)
        if launcher is None:
            runtime.stop()
            raise ValueError(f"Playwright browser tipi desteklenmiyor: {browser_name}")

        browser = launcher.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(manager.timeout_ms)
        return BrowserSession(
            session_id=str(uuid.uuid4()),
            provider=self.provider_name,
            browser_name=browser_name,
            headless=headless,
            started_at=time.time(),
            page=page,
            browser=browser,
            context=context,
            runtime=runtime,
        )

    def goto(self, manager: BrowserManager, session: BrowserSession, url: str) -> None:
        session.page.goto(url, wait_until="domcontentloaded", timeout=manager.timeout_ms)

    def click(self, manager: BrowserManager, session: BrowserSession, selector: str) -> None:
        session.page.click(selector, timeout=manager.timeout_ms)

    def fill(
        self,
        manager: BrowserManager,
        session: BrowserSession,
        selector: str,
        value: str,
        *,
        clear: bool,
    ) -> None:
        if clear:
            session.page.fill(selector, value, timeout=manager.timeout_ms)
            return
        session.page.type(selector, value, timeout=manager.timeout_ms)

    def select(
        self, manager: BrowserManager, session: BrowserSession, selector: str, value: str
    ) -> None:
        session.page.select_option(selector, value=value, timeout=manager.timeout_ms)

    def capture_dom(self, manager: BrowserManager, session: BrowserSession, selector: str) -> str:
        html = session.page.locator(selector).inner_html(timeout=manager.timeout_ms)
        return str(html)

    def capture_screenshot(
        self, manager: BrowserManager, session: BrowserSession, path: str, *, full_page: bool
    ) -> None:
        session.page.screenshot(path=path, full_page=full_page)

    def close(self, manager: BrowserManager, session: BrowserSession) -> None:
        if session.context is not None:
            session.context.close()
        if session.browser is not None:
            session.browser.close()
        if session.runtime is not None:
            session.runtime.stop()

    def current_url(self, session: BrowserSession) -> str:
        return str(getattr(session.page, "url", None) or "")


class SeleniumBrowserProvider(BaseBrowserProvider):
    provider_name = "selenium"

    def start_session(
        self, manager: BrowserManager, browser_name: str, headless: bool
    ) -> BrowserSession:
        webdriver = cast(Any, importlib.import_module("selenium.webdriver"))

        if browser_name not in {"chrome", "chromium", "firefox"}:
            raise ValueError(f"Selenium browser tipi desteklenmiyor: {browser_name}")

        driver: Any
        if browser_name in {"chrome", "chromium"}:
            chrome_options = webdriver.ChromeOptions()
            if headless:
                chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--no-sandbox")
            driver = webdriver.Chrome(options=chrome_options)
        else:
            firefox_options = webdriver.FirefoxOptions()
            if headless:
                firefox_options.add_argument("-headless")
            driver = webdriver.Firefox(options=firefox_options)

        driver.set_page_load_timeout(max(5, manager.timeout_ms // 1000))
        return BrowserSession(
            session_id=str(uuid.uuid4()),
            provider=self.provider_name,
            browser_name=browser_name,
            headless=headless,
            started_at=time.time(),
            driver=driver,
        )

    def goto(self, manager: BrowserManager, session: BrowserSession, url: str) -> None:
        session.driver.get(url)

    def click(self, manager: BrowserManager, session: BrowserSession, selector: str) -> None:
        by_module = importlib.import_module("selenium.webdriver.common.by")
        By = by_module.By
        session.driver.find_element(By.CSS_SELECTOR, selector).click()

    def fill(
        self,
        manager: BrowserManager,
        session: BrowserSession,
        selector: str,
        value: str,
        *,
        clear: bool,
    ) -> None:
        by_module = importlib.import_module("selenium.webdriver.common.by")
        By = by_module.By
        element = session.driver.find_element(By.CSS_SELECTOR, selector)
        if clear:
            element.clear()
        element.send_keys(value)

    def select(
        self, manager: BrowserManager, session: BrowserSession, selector: str, value: str
    ) -> None:
        by_module = importlib.import_module("selenium.webdriver.common.by")
        select_module = importlib.import_module("selenium.webdriver.support.select")
        By = by_module.By
        Select = select_module.Select
        Select(session.driver.find_element(By.CSS_SELECTOR, selector)).select_by_value(value)

    def capture_dom(self, manager: BrowserManager, session: BrowserSession, selector: str) -> str:
        _ = selector
        return str(session.driver.page_source)

    def capture_screenshot(
        self, manager: BrowserManager, session: BrowserSession, path: str, *, full_page: bool
    ) -> None:
        _ = full_page
        session.driver.save_screenshot(path)

    def close(self, manager: BrowserManager, session: BrowserSession) -> None:
        if session.driver is not None:
            session.driver.quit()

    def current_url(self, session: BrowserSession) -> str:
        return str(getattr(session.driver, "current_url", "") or "")


class BrowserManager:
    """Dinamik tarayıcı otomasyon işlemlerini güvenli ve sağlayıcıdan bağımsız yönetir."""

    def __init__(self, config: Config | None = None, llm_client: Any | None = None) -> None:
        self.cfg = config or Config()
        self._llm = llm_client
        self.provider = str(getattr(self.cfg, "BROWSER_PROVIDER", "auto") or "auto").strip().lower()
        self.default_headless = bool(getattr(self.cfg, "BROWSER_HEADLESS", True))
        self.timeout_ms = int(getattr(self.cfg, "BROWSER_TIMEOUT_MS", 15_000) or 15_000)
        self.visual_qa_enabled = bool(getattr(self.cfg, "BROWSER_VISUAL_QA_ENABLED", True))
        self.visual_qa_drift_threshold = float(
            getattr(self.cfg, "BROWSER_VISUAL_QA_DRIFT_THRESHOLD", 0.015) or 0.015
        )
        self.visual_qa_multimodal_margin = float(
            getattr(self.cfg, "BROWSER_VISUAL_QA_MULTIMODAL_MARGIN", 0.005) or 0.005
        )
        self.allowed_domains = {
            domain.strip().lower()
            for domain in (getattr(self.cfg, "BROWSER_ALLOWED_DOMAINS", []) or [])
            if str(domain).strip()
        }
        self.artifact_dir = Path(tempfile.gettempdir()) / "sidar_browser_artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, BrowserSession] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._browser_providers: dict[str, BaseBrowserProvider] = {
            "playwright": PlaywrightBrowserProvider(),
            "selenium": SeleniumBrowserProvider(),
        }

    @staticmethod
    def _is_high_risk_click(selector: str) -> bool:
        normalized = (selector or "").strip().lower()
        risk_markers = (
            "submit",
            "save",
            "update",
            "delete",
            "remove",
            "drop",
            "confirm",
            "publish",
            "create",
            "buy",
            "pay",
            "jira",
        )
        return any(marker in normalized for marker in risk_markers)

    @staticmethod
    def _summarize_value(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        if len(text) <= 8:
            return "*" * len(text)
        return f"{text[:2]}***{text[-2:]} (len={len(text)})"

    def _record_audit_event(
        self,
        *,
        session_id: str,
        action: str,
        status: str,
        selector: str = "",
        current_url: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "timestamp": time.time(),
            "session_id": session_id,
            "action": action,
            "status": status,
            "selector": selector,
            "url": current_url,
            "details": dict(details or {}),
        }
        self._audit_log.append(entry)
        logger.info(
            "Browser audit: session=%s action=%s status=%s selector=%s url=%s",
            session_id,
            action,
            status,
            selector,
            current_url,
        )
        return entry

    def _audit_session_action(
        self,
        session: BrowserSession,
        *,
        action: str,
        status: str,
        selector: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self._record_audit_event(
            session_id=session.session_id,
            action=action,
            status=status,
            selector=selector,
            current_url=self._session_url(session),
            details=details,
        )

    def list_audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit_log)

    def summarize_audit_log(
        self,
        session_id: str | None = None,
        *,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Tarayıcı audit akışını reviewer/swarm için yapılandırılmış sinyallere dönüştür."""
        normalized_session_id = str(session_id or "").strip()
        entries = [
            dict(item)
            for item in self._audit_log
            if not normalized_session_id
            or str(item.get("session_id", "")).strip() == normalized_session_id
        ]
        recent_entries = entries[-max(1, int(limit or 12)) :]

        status_counts: dict[str, int] = {}
        action_counts: dict[str, int] = {}
        failed_actions: list[str] = []
        pending_actions: list[str] = []
        high_risk_actions: list[str] = []
        urls: list[str] = []

        for entry in entries:
            status = str(entry.get("status", "") or "").strip()
            action = str(entry.get("action", "") or "").strip()
            selector = str(entry.get("selector", "") or "").strip()
            url = str(entry.get("url", "") or "").strip()
            if status:
                status_counts[status] = status_counts.get(status, 0) + 1
            if action:
                action_counts[action] = action_counts.get(action, 0) + 1
            if status in {"execution_failed", "failed", "rejected", "blocked_hitl"} and action:
                label = f"{action}:{selector}" if selector else action
                if label not in failed_actions:
                    failed_actions.append(label)
            if status == "pending_approval" and action and action not in pending_actions:
                pending_actions.append(action)
            if (
                action in {"browser_click", "browser_fill_form", "browser_select_option"}
                and selector
            ):
                if self._is_high_risk_click(selector):
                    label = f"{action}:{selector}"
                    if label not in high_risk_actions:
                        high_risk_actions.append(label)
            if url and url not in urls:
                urls.append(url)

        if failed_actions:
            risk = "yüksek"
            status = "failed"
        elif pending_actions or high_risk_actions:
            risk = "orta"
            status = "attention"
        elif entries:
            risk = "düşük"
            status = "ok"
        else:
            risk = "düşük"
            status = "no-signal"

        summary = (
            f"Browser sinyalleri: oturum={normalized_session_id or 'all'}, "
            f"kayıt={len(entries)}, failed={len(failed_actions)}, pending={len(pending_actions)}, "
            f"yüksek_risk={len(high_risk_actions)}."
        )
        return {
            "session_id": normalized_session_id,
            "status": status,
            "risk": risk,
            "entry_count": len(entries),
            "status_counts": status_counts,
            "action_counts": action_counts,
            "failed_actions": failed_actions[:8],
            "pending_actions": pending_actions[:8],
            "high_risk_actions": high_risk_actions[:8],
            "urls": urls[:8],
            "recent_entries": recent_entries,
            "summary": summary,
        }

    def collect_session_signals(
        self,
        session_id: str,
        *,
        include_dom: bool = False,
        include_screenshot: bool = False,
        include_visual_qa: bool = False,
        visual_baseline_path: str = "",
        dom_selector: str = "html",
    ) -> dict[str, Any]:
        """Reviewer ve swarm için oturumdan türetilmiş browser sinyali paketi üret."""
        session = self._require_session(session_id)
        signal = self.summarize_audit_log(session_id)
        signal.update(
            {
                "provider": session.provider,
                "browser_name": session.browser_name,
                "current_url": self._session_url(session),
            }
        )

        if include_dom:
            ok, dom = self.capture_dom(session_id, dom_selector)
            signal["dom_capture"] = {
                "ok": ok,
                "selector": dom_selector,
                "preview": (dom[:1000] + "…") if len(dom) > 1000 else dom,
            }

        if include_screenshot:
            ok, path = self.capture_screenshot(session_id, file_name=f"{session_id}.png")
            signal["screenshot"] = {"ok": ok, "path": path}

        if include_visual_qa:
            visual = self._run_coro_sync(
                self.analyze_visual_drift(
                    session_id,
                    baseline_path=visual_baseline_path,
                    file_name=f"{session_id}.visual.png",
                )
            )
            signal["visual_qa"] = visual

        return signal

    async def _analyze_screenshot_with_multimodal(
        self, image_path: str, prompt: str
    ) -> dict[str, Any]:
        if self._llm is None:
            return {"success": False, "reason": "LLM istemcisi bağlı değil"}
        multimodal_module = importlib.import_module("core.multimodal")
        pipeline = multimodal_module.MultimodalPipeline(self._llm, self.cfg)
        result = await pipeline.analyze_media(
            media_path=image_path,
            mime_type="image/png",
            prompt=prompt,
        )
        return cast(dict[str, Any], result)

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    def _compute_visual_drift(self, baseline_path: Path, current_path: Path) -> dict[str, Any]:
        try:
            image_module = importlib.import_module("PIL.Image")
            image_chops = importlib.import_module("PIL.ImageChops")
            img_a = image_module.open(str(baseline_path)).convert("RGB")
            img_b = image_module.open(str(current_path)).convert("RGB")
            if img_a.size != img_b.size:
                return {
                    "drift_detected": True,
                    "drift_score": 1.0,
                    "changed_ratio": 1.0,
                    "reason": "Görsel boyutları farklı",
                    "baseline_size": img_a.size,
                    "current_size": img_b.size,
                }
            diff = image_chops.difference(img_a, img_b).convert("L")
            histogram = diff.histogram()
            total_pixels = max(1, img_a.size[0] * img_a.size[1])
            changed_pixels = total_pixels - int(histogram[0] or 0)
            changed_ratio = max(0.0, min(1.0, changed_pixels / total_pixels))
            drift_score = round(changed_ratio, 6)
            return {
                "drift_detected": drift_score >= self.visual_qa_drift_threshold,
                "drift_score": drift_score,
                "changed_ratio": round(changed_ratio, 6),
                "baseline_size": img_a.size,
                "current_size": img_b.size,
                "reason": "pixel_diff",
            }
        except Exception:
            baseline_hash = self._hash_file(baseline_path)
            current_hash = self._hash_file(current_path)
            drift_detected = baseline_hash != current_hash
            return {
                "drift_detected": drift_detected,
                "drift_score": 1.0 if drift_detected else 0.0,
                "changed_ratio": 1.0 if drift_detected else 0.0,
                "reason": "hash_fallback",
                "baseline_hash": baseline_hash,
                "current_hash": current_hash,
            }

    def _should_run_multimodal_for_drift(self, drift_score: float) -> bool:
        threshold = self.visual_qa_drift_threshold
        margin = max(0.0, self.visual_qa_multimodal_margin)
        return abs(float(drift_score) - threshold) <= margin

    async def analyze_visual_drift(
        self,
        session_id: str,
        *,
        baseline_path: str = "",
        file_name: str | None = None,
        run_multimodal_analysis: bool = True,
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        if not self.visual_qa_enabled:
            return {"ok": False, "reason": "BROWSER_VISUAL_QA_ENABLED devre dışı"}

        ok, current_path = await asyncio.to_thread(
            self.capture_screenshot,
            session_id,
            file_name or f"{session_id}.visual.png",
        )
        if not ok:
            return {"ok": False, "reason": current_path}
        current = Path(current_path)
        baseline = Path(baseline_path).expanduser().resolve() if baseline_path.strip() else None

        if baseline is None:
            return {
                "ok": True,
                "session_id": session_id,
                "current_screenshot": str(current),
                "baseline_screenshot": "",
                "drift_detected": False,
                "drift_score": 0.0,
                "changed_ratio": 0.0,
                "reason": "baseline_missing",
                "recommendation": "Visual drift kıyaslaması için baseline_path sağlayın.",
            }
        if not baseline.exists():
            return {
                "ok": False,
                "session_id": session_id,
                "current_screenshot": str(current),
                "baseline_screenshot": str(baseline),
                "reason": "baseline_not_found",
            }

        drift = self._compute_visual_drift(baseline, current)
        result = {
            "ok": True,
            "session_id": session_id,
            "current_screenshot": str(current),
            "baseline_screenshot": str(baseline),
            "threshold": self.visual_qa_drift_threshold,
            **drift,
        }
        drift_score = float(result.get("drift_score", 0.0) or 0.0)
        should_run_multimodal = run_multimodal_analysis and self._should_run_multimodal_for_drift(
            drift_score
        )
        result["multimodal_check"] = {
            "enabled": bool(run_multimodal_analysis),
            "triggered": bool(should_run_multimodal),
            "threshold": self.visual_qa_drift_threshold,
            "margin": max(0.0, self.visual_qa_multimodal_margin),
            "drift_score": drift_score,
        }
        if should_run_multimodal:
            prompt = (
                "Bu ekran görüntüsünü UI regresyon açısından analiz et. "
                "Buton kayması, hizalama bozulması, görünürlük sorunları ve layout drift bulgularını listele."
            )
            with contextlib.suppress(Exception):
                mm = await self._analyze_screenshot_with_multimodal(str(current), prompt)
                result["multimodal_analysis"] = mm

        self._audit_session_action(
            session,
            action="browser_visual_qa",
            status="executed",
            details={
                "baseline": str(baseline),
                "current": str(current),
                "drift_detected": bool(result.get("drift_detected")),
                "drift_score": result.get("drift_score", 0.0),
            },
        )
        return result

    def _session_url(self, session: BrowserSession) -> str:
        if session.current_url:
            return session.current_url
        provider = self._browser_providers.get(session.provider)
        if provider is not None:
            return provider.current_url(session)
        return ""

    def _provider_for_session(self, session: BrowserSession) -> BaseBrowserProvider:
        provider = self._browser_providers.get(session.provider)
        if provider is None:
            raise ValueError(f"Desteklenmeyen browser provider: {session.provider}")
        return provider

    @staticmethod
    def _run_coro_sync(coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def _request_hitl_approval(
        self,
        *,
        session: BrowserSession,
        action: str,
        description: str,
        payload: dict[str, Any],
        selector: str,
    ) -> bool:
        current_url = self._session_url(session)
        self._record_audit_event(
            session_id=session.session_id,
            action=action,
            status="pending_approval",
            selector=selector,
            current_url=current_url,
            details=payload,
        )
        approved = await get_hitl_gate().request_approval(
            action=action,
            description=description,
            payload=payload,
            requested_by="BrowserManager",
        )
        self._record_audit_event(
            session_id=session.session_id,
            action=action,
            status="approved" if approved else "rejected",
            selector=selector,
            current_url=current_url,
            details=payload,
        )
        return approved

    def _sync_hitl_guard(
        self, action: str, selector: str, *, force_block: bool = False
    ) -> tuple[bool, str] | None:
        gate = get_hitl_gate()
        if not getattr(gate, "enabled", False):
            return None
        if not force_block and action == "browser_click" and not self._is_high_risk_click(selector):
            return None
        async_method = {
            "browser_click": "click_element_hitl",
            "browser_fill_form": "fill_form_hitl",
            "browser_select_option": "select_option_hitl",
        }.get(action, "HITL-korumalı async API")
        return False, f"HITL etkin; bu işlem için {async_method} kullanılmalı: {selector}"

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
        provider = self._browser_providers["playwright"]
        return provider.start_session(self, browser_name, headless)

    def _start_selenium_session(self, browser_name: str, headless: bool) -> BrowserSession:
        provider = self._browser_providers["selenium"]
        return provider.start_session(self, browser_name, headless)

    def is_available(self) -> bool:
        for candidate in self._provider_candidates():
            try:
                if candidate == "playwright":
                    import playwright.sync_api  # noqa: F401

                    return True
                if candidate == "selenium":  # pragma: no cover
                    return importlib.util.find_spec("selenium") is not None
            except Exception as exc:
                logger.debug("Browser provider availability check başarısız (%s): %s", candidate, exc)
                continue
        return False

    def status(self) -> str:
        active = len(self._sessions)
        return (
            f"BrowserManager: provider={self.provider} "
            f"available={'yes' if self.is_available() else 'no'} active_sessions={active}"
        )

    def start_session(
        self, browser_name: str = "chromium", headless: bool | None = None
    ) -> tuple[bool, dict[str, Any]]:
        headless_value = self.default_headless if headless is None else bool(headless)
        last_error = "Tarayıcı sağlayıcısı başlatılamadı."

        for candidate in self._provider_candidates():
            try:
                provider = self._browser_providers.get(candidate)
                if provider is None:
                    last_error = f"Desteklenmeyen browser provider: {candidate}"
                    continue
                session = provider.start_session(self, browser_name, headless_value)

                self._sessions[session.session_id] = session
                self._audit_session_action(
                    session,
                    action="browser_start_session",
                    status="started",
                    details={
                        "provider": session.provider,
                        "browser_name": session.browser_name,
                        "headless": session.headless,
                    },
                )
                return True, {
                    "session_id": session.session_id,
                    "provider": session.provider,
                    "browser": session.browser_name,
                    "headless": session.headless,
                }
            except Exception as exc:
                logger.warning("Browser provider başlatılamadı (%s): %s", candidate, exc)
                last_error = str(exc)
                self._record_audit_event(
                    session_id=f"startup:{candidate}",
                    action="browser_start_session",
                    status="failed",
                    details={
                        "provider": candidate,
                        "browser_name": browser_name,
                        "error": str(exc),
                    },
                )

        return False, {"error": last_error}

    def goto_url(self, session_id: str, url: str) -> tuple[bool, str]:
        self._validate_url(url)
        session = self._require_session(session_id)
        provider = self._provider_for_session(session)
        try:
            provider.goto(self, session, url)
            resolved_url = provider.current_url(session) or session.current_url or url
            session.current_url = resolved_url

            self._audit_session_action(
                session,
                action="browser_goto_url",
                status="executed",
                details={"url": url, "resolved_url": resolved_url},
            )
            return True, f"Açıldı: {resolved_url}"
        except Exception as exc:
            self._audit_session_action(
                session,
                action="browser_goto_url",
                status="execution_failed",
                details={"url": url, "error": str(exc)},
            )
            raise

    def _click_element_impl(self, session_id: str, selector: str) -> tuple[bool, str]:
        session = self._require_session(session_id)
        provider = self._provider_for_session(session)
        provider.click(self, session, selector)
        return True, f"Tıklandı: {selector}"

    async def _click_element_impl_async(self, session_id: str, selector: str) -> tuple[bool, str]:
        return await asyncio.to_thread(self._click_element_impl, session_id, selector)

    def click_element(self, session_id: str, selector: str) -> tuple[bool, str]:
        session = self._require_session(session_id)
        blocked = self._sync_hitl_guard("browser_click", selector)
        if blocked is not None:
            self._audit_session_action(
                session,
                action="browser_click",
                status="blocked_hitl",
                selector=selector,
                details={"reason": blocked[1]},
            )
            return blocked
        try:
            ok, message = self._click_element_impl(session_id, selector)
            self._audit_session_action(
                session,
                action="browser_click",
                status="executed" if ok else "execution_failed",
                selector=selector,
            )
            return ok, message
        except Exception as exc:
            self._audit_session_action(
                session,
                action="browser_click",
                status="execution_failed",
                selector=selector,
                details={"error": str(exc)},
            )
            raise

    async def click_element_hitl(
        self,
        session_id: str,
        selector: str,
        *,
        reason: str = "",
        require_confirmation: bool | None = None,
    ) -> tuple[bool, str]:
        session = self._require_session(session_id)
        must_confirm = (
            self._is_high_risk_click(selector)
            if require_confirmation is None
            else bool(require_confirmation)
        )
        if not must_confirm:
            return await self._click_element_impl_async(session_id, selector)

        payload = {
            "session_id": session_id,
            "selector": selector,
            "url": self._session_url(session),
            "reason": reason.strip(),
        }
        description = f"Tarayıcıda yüksek riskli tıklama yapılacak: {selector}" + (
            f" | Gerekçe: {reason.strip()}" if reason.strip() else ""
        )
        approved = await self._request_hitl_approval(
            session=session,
            action="browser_click",
            description=description,
            payload=payload,
            selector=selector,
        )
        if not approved:
            return False, f"HITL onayı beklenirken/sonucunda işlem reddedildi: {selector}"

        try:
            ok, message = await self._click_element_impl_async(session_id, selector)
            self._record_audit_event(
                session_id=session_id,
                action="browser_click",
                status="executed" if ok else "execution_failed",
                selector=selector,
                current_url=self._session_url(session),
                details=payload,
            )
            return ok, message
        except Exception as exc:
            self._record_audit_event(
                session_id=session_id,
                action="browser_click",
                status="execution_failed",
                selector=selector,
                current_url=self._session_url(session),
                details={**payload, "error": str(exc)},
            )
            raise

    def _fill_form_impl(
        self, session_id: str, selector: str, value: str, clear: bool = True
    ) -> tuple[bool, str]:
        session = self._require_session(session_id)
        provider = self._provider_for_session(session)
        provider.fill(self, session, selector, value, clear=clear)
        return True, f"Form dolduruldu: {selector}"

    async def _fill_form_impl_async(
        self,
        session_id: str,
        selector: str,
        value: str,
        clear: bool = True,
    ) -> tuple[bool, str]:
        return await asyncio.to_thread(self._fill_form_impl, session_id, selector, value, clear)

    def fill_form(
        self, session_id: str, selector: str, value: str, clear: bool = True
    ) -> tuple[bool, str]:
        session = self._require_session(session_id)
        blocked = self._sync_hitl_guard("browser_fill_form", selector, force_block=True)
        if blocked is not None:
            self._audit_session_action(
                session,
                action="browser_fill_form",
                status="blocked_hitl",
                selector=selector,
                details={"reason": blocked[1], "clear": bool(clear)},
            )
            return blocked
        try:
            ok, message = self._fill_form_impl(session_id, selector, value, clear=clear)
            self._audit_session_action(
                session,
                action="browser_fill_form",
                status="executed" if ok else "execution_failed",
                selector=selector,
                details={"clear": bool(clear), "value_preview": self._summarize_value(value)},
            )
            return ok, message
        except Exception as exc:
            self._audit_session_action(
                session,
                action="browser_fill_form",
                status="execution_failed",
                selector=selector,
                details={
                    "clear": bool(clear),
                    "value_preview": self._summarize_value(value),
                    "error": str(exc),
                },
            )
            raise

    async def fill_form_hitl(
        self,
        session_id: str,
        selector: str,
        value: str,
        *,
        clear: bool = True,
        reason: str = "",
    ) -> tuple[bool, str]:
        session = self._require_session(session_id)
        payload = {
            "session_id": session_id,
            "selector": selector,
            "url": self._session_url(session),
            "value_preview": self._summarize_value(value),
            "clear": bool(clear),
            "reason": reason.strip(),
        }
        description = f"Tarayıcı form alanı doldurulacak: {selector}" + (
            f" | Gerekçe: {reason.strip()}" if reason.strip() else ""
        )
        approved = await self._request_hitl_approval(
            session=session,
            action="browser_fill_form",
            description=description,
            payload=payload,
            selector=selector,
        )
        if not approved:
            return False, f"HITL onayı beklenirken/sonucunda form doldurma reddedildi: {selector}"

        try:
            ok, message = await self._fill_form_impl_async(session_id, selector, value, clear=clear)
            self._record_audit_event(
                session_id=session_id,
                action="browser_fill_form",
                status="executed" if ok else "execution_failed",
                selector=selector,
                current_url=self._session_url(session),
                details=payload,
            )
            return ok, message
        except Exception as exc:
            self._record_audit_event(
                session_id=session_id,
                action="browser_fill_form",
                status="execution_failed",
                selector=selector,
                current_url=self._session_url(session),
                details={**payload, "error": str(exc)},
            )
            raise

    def _select_option_impl(self, session_id: str, selector: str, value: str) -> tuple[bool, str]:
        session = self._require_session(session_id)
        provider = self._provider_for_session(session)
        provider.select(self, session, selector, value)
        return True, f"Seçim yapıldı: {selector}={value}"

    async def _select_option_impl_async(
        self, session_id: str, selector: str, value: str
    ) -> tuple[bool, str]:
        return await asyncio.to_thread(self._select_option_impl, session_id, selector, value)

    def select_option(self, session_id: str, selector: str, value: str) -> tuple[bool, str]:
        session = self._require_session(session_id)
        blocked = self._sync_hitl_guard("browser_select_option", selector, force_block=True)
        if blocked is not None:
            self._audit_session_action(
                session,
                action="browser_select_option",
                status="blocked_hitl",
                selector=selector,
                details={"reason": blocked[1], "value_preview": self._summarize_value(value)},
            )
            return blocked
        try:
            ok, message = self._select_option_impl(session_id, selector, value)
            self._audit_session_action(
                session,
                action="browser_select_option",
                status="executed" if ok else "execution_failed",
                selector=selector,
                details={"value_preview": self._summarize_value(value)},
            )
            return ok, message
        except Exception as exc:
            self._audit_session_action(
                session,
                action="browser_select_option",
                status="execution_failed",
                selector=selector,
                details={"value_preview": self._summarize_value(value), "error": str(exc)},
            )
            raise

    async def select_option_hitl(
        self,
        session_id: str,
        selector: str,
        value: str,
        *,
        reason: str = "",
    ) -> tuple[bool, str]:
        session = self._require_session(session_id)
        payload = {
            "session_id": session_id,
            "selector": selector,
            "url": self._session_url(session),
            "value_preview": self._summarize_value(value),
            "reason": reason.strip(),
        }
        description = f"Tarayıcı seçim alanı güncellenecek: {selector}" + (
            f" | Gerekçe: {reason.strip()}" if reason.strip() else ""
        )
        approved = await self._request_hitl_approval(
            session=session,
            action="browser_select_option",
            description=description,
            payload=payload,
            selector=selector,
        )
        if not approved:
            return False, f"HITL onayı beklenirken/sonucunda seçim reddedildi: {selector}"

        try:
            ok, message = await self._select_option_impl_async(session_id, selector, value)
            self._record_audit_event(
                session_id=session_id,
                action="browser_select_option",
                status="executed" if ok else "execution_failed",
                selector=selector,
                current_url=self._session_url(session),
                details=payload,
            )
            return ok, message
        except Exception as exc:
            self._record_audit_event(
                session_id=session_id,
                action="browser_select_option",
                status="execution_failed",
                selector=selector,
                current_url=self._session_url(session),
                details={**payload, "error": str(exc)},
            )
            raise

    def capture_dom(self, session_id: str, selector: str = "html") -> tuple[bool, str]:
        session = self._require_session(session_id)
        provider = self._provider_for_session(session)
        try:
            dom = provider.capture_dom(self, session, selector)
            self._audit_session_action(
                session,
                action="browser_capture_dom",
                status="executed",
                selector=selector,
            )
            return True, dom
        except Exception as exc:
            self._audit_session_action(
                session,
                action="browser_capture_dom",
                status="execution_failed",
                selector=selector,
                details={"error": str(exc)},
            )
            return False, f"DOM yakalama hatası: {exc}"

    def capture_screenshot(
        self,
        session_id: str,
        file_name: str | None = None,
        full_page: bool = True,
    ) -> tuple[bool, str]:
        session = self._require_session(session_id)
        target_name = file_name or f"{session.session_id}.png"
        target = (self.artifact_dir / target_name).resolve()
        provider = self._provider_for_session(session)

        provider.capture_screenshot(self, session, str(target), full_page=full_page)

        self._audit_session_action(
            session,
            action="browser_capture_screenshot",
            status="executed",
            details={"path": str(target), "full_page": bool(full_page)},
        )
        return True, str(target)

    def close_session(self, session_id: str) -> tuple[bool, str]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False, f"Tarayıcı oturumu bulunamadı: {session_id}"
        provider = self._provider_for_session(session)

        try:
            provider.close(self, session)
        except Exception as exc:
            logger.warning("Tarayıcı oturumu kapatılırken hata: %s", exc)
            self._audit_session_action(
                session,
                action="browser_close_session",
                status="execution_failed",
                details={"error": str(exc)},
            )
            return False, f"Oturum kapatılırken hata: {exc}"

        self._audit_session_action(
            session,
            action="browser_close_session",
            status="executed",
        )
        return True, f"Tarayıcı oturumu kapatıldı: {session_id}"
