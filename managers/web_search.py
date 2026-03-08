"""
Sidar Project - Web Arama Yöneticisi
DuckDuckGo tabanlı web arama, URL içerik çekme ve dokümantasyon araması.
"""

import asyncio
import logging
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class WebSearchManager:
    """Asenkron web arama/fetch yardımcıları."""

    _NO_RESULTS_PREFIX = "[NO_RESULTS]"

    def __init__(self, config=None) -> None:
        self.cfg = config
        self.tavily_key = getattr(config, "TAVILY_API_KEY", "") if config else ""
        self.google_key = getattr(config, "GOOGLE_SEARCH_API_KEY", "") if config else ""
        self.search_engine = getattr(config, "SEARCH_ENGINE", "auto") if config else "auto"

        timeout = float(getattr(config, "WEB_FETCH_TIMEOUT", 15) if config else 15)
        self.timeout = httpx.Timeout(timeout, connect=5.0)

        n = getattr(config, "WEB_SEARCH_MAX_RESULTS", 5) if config else 5
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 5
        n = max(1, min(n, 10))
        self.max_results = n

        self.max_chars = int(getattr(config, "WEB_SCRAPE_MAX_CHARS", getattr(config, "WEB_FETCH_MAX_CHARS", 12000)) if config else 12000)

        version = getattr(config, "VERSION", "2.7.0") if config else "2.7.0"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "X-Client": f"SidarAI/{version}",
        }

        self._ddg_available = self._check_ddg()

    def _check_ddg(self) -> bool:
        try:
            from duckduckgo_search import DDGS  # noqa: F401
            return True
        except Exception:
            return False

    def is_available(self) -> bool:
        return bool(self._ddg_available or self.tavily_key or self.google_key)

    def status(self) -> str:
        engines = []
        if self.tavily_key:
            engines.append("Tavily")
        if self.google_key:
            engines.append("Google")
        if self._ddg_available:
            engines.append("DuckDuckGo")
        if not engines:
            return "WebSearch: Kurulu veya yapılandırılmış motor yok."
        return f"WebSearch: Aktif ({', '.join(engines)})"

    def _normalize_result_text(self, text: str) -> str:
        return " ".join((text or "").split())

    def _is_actionable_result(self, text: str) -> bool:
        normalized = self._normalize_result_text(text)
        return bool(normalized and not normalized.startswith(self._NO_RESULTS_PREFIX))

    def _truncate_content(self, text: str) -> str:
        text = (text or "").strip()
        if len(text) <= self.max_chars:
            return text
        return text[: self.max_chars] + "\n... [İçerik çok uzun olduğu için kesildi]"

    async def search(self, query: str) -> tuple[bool, str]:
        q = (query or "").strip()
        if not q:
            return False, "⚠ Arama sorgusu belirtilmedi."

        if self._ddg_available:
            result = await self._search_ddg(q)
            if self._is_actionable_result(result):
                return True, result

        # Ağ tabanlı fallback: sonuç yoksa kullanıcıya yönlendirici link ver.
        return True, (
            f"{self._NO_RESULTS_PREFIX} Doğrudan sonuç alınamadı. "
            f"Şuradan arayabilirsiniz: https://duckduckgo.com/?q={quote_plus(q)}"
        )

    async def _search_ddg(self, query: str) -> str:
        def _run() -> str:
            try:
                from duckduckgo_search import DDGS

                lines = []
                with DDGS() as ddgs:
                    for item in ddgs.text(query, max_results=self.max_results):
                        title = self._normalize_result_text(item.get("title", ""))
                        href = item.get("href", "")
                        body = self._normalize_result_text(item.get("body", ""))
                        lines.append(f"- {title}\n  {href}\n  {body}")
                if not lines:
                    return f"{self._NO_RESULTS_PREFIX} Sonuç bulunamadı."
                return "[Web Sonuçları]\n" + "\n".join(lines)
            except Exception as exc:
                logger.warning("DDG araması başarısız: %s", exc)
                return f"{self._NO_RESULTS_PREFIX} Arama başarısız: {exc}"

        return await asyncio.to_thread(_run)

    async def scrape_url(self, url: str) -> str:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.headers,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return self._truncate_content(cleaned)

    async def fetch_url(self, url: str) -> tuple[bool, str]:
        u = (url or "").strip()
        if not u:
            return False, "⚠ URL belirtilmedi."
        try:
            content = await self.scrape_url(u)
            return True, f"[URL İçeriği] {u}\n\n{content}"
        except Exception as exc:
            return False, f"[HATA] URL içeriği alınamadı: {exc}"

    async def search_docs(self, library: str, topic: str = "") -> tuple[bool, str]:
        lib = (library or "").strip()
        top = (topic or "").strip()
        if not lib:
            return False, "⚠ Kütüphane adı belirtilmedi."
        query = f"{lib} official documentation {top}".strip()
        return await self.search(query)

    async def search_stackoverflow(self, query: str) -> tuple[bool, str]:
        q = (query or "").strip()
        if not q:
            return False, "⚠ Stack Overflow sorgusu belirtilmedi."
        return await self.search(f"site:stackoverflow.com {q}")
