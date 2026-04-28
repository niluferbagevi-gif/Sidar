"""
Sidar Project - Web Arama Yöneticisi
Tavily, Google Custom Search ve DuckDuckGo motorları ile asenkron web araması.
Sürüm: 2.7.0

Motor öncelik sırası (auto modu): Tavily → Google → DuckDuckGo
"""

import asyncio
import logging
from html import unescape
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


class WebSearchManager:
    """
    Gelişmiş, çoklu motor destekli ve asenkron web arama yöneticisi.
    DuckDuckGo, Tavily ve Google Custom Search API'lerini destekler.
    """

    MAX_RESULTS = 5
    FETCH_TIMEOUT = 15  # saniye
    FETCH_MAX_CHARS = 12000

    _NO_RESULTS_PREFIX = "[NO_RESULTS]"

    def __init__(self, config: Any = None) -> None:
        self.cfg = config
        if config is not None:
            self.engine = getattr(config, "SEARCH_ENGINE", "auto").lower()
            self.tavily_key = getattr(config, "TAVILY_API_KEY", "")
            self.google_key = getattr(config, "GOOGLE_SEARCH_API_KEY", "")
            self.google_cx = getattr(config, "GOOGLE_SEARCH_CX", "")

            self.MAX_RESULTS = getattr(config, "WEB_SEARCH_MAX_RESULTS", self.MAX_RESULTS)
            self.FETCH_TIMEOUT = getattr(config, "WEB_FETCH_TIMEOUT", self.FETCH_TIMEOUT)
            self.FETCH_MAX_CHARS = getattr(
                config,
                "WEB_SCRAPE_MAX_CHARS",
                getattr(config, "WEB_FETCH_MAX_CHARS", self.FETCH_MAX_CHARS),
            )
        else:
            self.engine = "auto"
            self.tavily_key = ""
            self.google_key = ""
            self.google_cx = ""

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self.timeout = httpx.Timeout(float(self.FETCH_TIMEOUT), connect=5.0)

        self._ddg_available = self._check_ddg()

    def _check_ddg(self) -> bool:
        try:
            # v8 uyumlu import (AsyncDDGS yerine standart DDGS)
            from duckduckgo_search import DDGS  # noqa: F401

            return True
        except ImportError as exc:
            logger.debug("DDG Import hatası: %s", exc)
            return False

    def is_available(self) -> bool:
        """En az bir arama motoru çalışabilir durumda mı?"""
        return (
            self._ddg_available or bool(self.tavily_key) or bool(self.google_key and self.google_cx)
        )

    def status(self) -> str:
        engines = []
        if self.tavily_key:
            engines.append("Tavily")
        if self.google_key and self.google_cx:
            engines.append("Google")
        if self._ddg_available:
            engines.append("DuckDuckGo")

        if not engines:
            return "WebSearch: Kurulu veya yapılandırılmış motor yok."

        return f"WebSearch: Aktif (Mod: {self.engine.upper()}) | {', '.join(engines)}"

    # ─────────────────────────────────────────────
    #  ANA ARAMA YÖNLENDİRİCİ (ASYNC)
    # ─────────────────────────────────────────────

    async def search(self, query: str, max_results: int | None = None) -> tuple[bool, str]:
        """
        Belirlenen motora veya fallback (yedek) mantığına göre arama yapar.
        """
        n = max_results or self.MAX_RESULTS
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = self.MAX_RESULTS
        n = max(1, min(n, 10))

        tavily_already_tried = False

        if self.engine == "tavily" and self.tavily_key:
            ok, res = await self._search_tavily(query, n)
            tavily_already_tried = True
            if self._is_actionable_result(ok, res):
                return True, self._normalize_result_text(res)
            if ok:
                # Tavily açıkça seçildiyse ve yalnızca "sonuç yok" döndüyse
                # hataya düşmeden bu sonucu kullanıcıya ilet.
                return True, self._normalize_result_text(res)
            # Tavily çağrısı hata verdiyse auto fallback'e düş.
            logger.info(
                "Tavily eyleme geçirilebilir sonuç üretmedi; otomatik fallback başlatılıyor."
            )
        elif self.engine == "google" and self.google_key and self.google_cx:
            ok, res = await self._search_google(query, n)
            return ok, self._normalize_result_text(res)
        elif self.engine == "duckduckgo" and self._ddg_available:
            ok, res = await self._search_duckduckgo(query, n)
            return ok, self._normalize_result_text(res)

        # AUTO MODU VEYA FALLBACK: Tavily -> Google -> DuckDuckGo
        # tavily_already_tried=True ise yukarıda denendiydi ve başarısız oldu — atla
        if self.tavily_key and not tavily_already_tried:
            ok, res = await self._search_tavily(query, n)
            if self._is_actionable_result(ok, res):
                return True, self._normalize_result_text(res)

        if self.google_key and self.google_cx:
            ok, res = await self._search_google(query, n)
            if self._is_actionable_result(ok, res):
                return True, self._normalize_result_text(res)

        if self._ddg_available:
            ok, res = await self._search_duckduckgo(query, n)
            return ok, self._normalize_result_text(res)

        return False, "⚠ Web arama yapılamadı. API anahtarları veya duckduckgo-search paketi eksik."

    # ─────────────────────────────────────────────
    #  MOTORLAR
    # ─────────────────────────────────────────────

    async def _search_tavily(self, query: str, n: int) -> tuple[bool, str]:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "max_results": n,
        }
        try:
            async with httpx.AsyncClient(timeout=10, headers=self.headers) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()

            results = data.get("results", [])
            if not results:
                return True, self._mark_no_results(f"'{query}' için Tavily'de sonuç bulunamadı.")

            lines = [f"[Web Arama (Tavily): {query}]", ""]
            for i, r in enumerate(results, 1):
                title = r.get("title", "Başlıksız")
                body = r.get("content", "")[:300].rstrip()
                href = r.get("url", "")
                lines.append(f"{i}. **{title}**")
                if body:
                    lines.append(f"   {body}")
                lines.append(f"   → {href}\n")

            return True, "\n".join(lines)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                logger.error(
                    "Tavily kimlik doğrulama hatası (%d) — API anahtarı geçersiz veya süresi dolmuş; "
                    "Tavily bu oturum için devre dışı bırakıldı.",
                    exc.response.status_code,
                )
                self.tavily_key = ""  # 401/403 sonrası gereksiz istekleri önle
            else:
                logger.warning("Tavily HTTP hatası: %s", exc)
            return False, f"[HATA] Tavily: {exc}"
        except Exception as exc:
            logger.warning("Tavily API hatası: %s", exc)
            return False, f"[HATA] Tavily: {exc}"

    async def _search_google(self, query: str, n: int) -> tuple[bool, str]:
        url = "https://customsearch.googleapis.com/customsearch/v1"
        params = {
            "key": self.google_key,
            "cx": self.google_cx,
            "q": query,
            "num": min(n, 10),
        }
        try:
            async with httpx.AsyncClient(timeout=10, headers=self.headers) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            items = data.get("items", [])
            if not items:
                return True, self._mark_no_results(f"'{query}' için Google'da sonuç bulunamadı.")

            lines = [f"[Web Arama (Google): {query}]", ""]
            for i, r in enumerate(items, 1):
                title = r.get("title", "Başlıksız")
                body = r.get("snippet", "")[:300].rstrip()
                href = r.get("link", "")
                lines.append(f"{i}. **{title}**")
                if body:
                    lines.append(f"   {body}")
                lines.append(f"   → {href}\n")

            return True, "\n".join(lines)
        except Exception as exc:
            logger.warning("Google API hatası: %s", exc)
            return False, f"[HATA] Google Search: {exc}"

    async def _search_duckduckgo(self, query: str, n: int) -> tuple[bool, str]:
        try:
            import duckduckgo_search

            # Dinamik AsyncDDGS kontrolü (Gelecekteki versiyon değişikliklerine karşı koruma)
            if hasattr(duckduckgo_search, "AsyncDDGS"):
                from duckduckgo_search import AsyncDDGS

                async def _async_search() -> list[dict[str, Any]]:
                    async with AsyncDDGS() as ddgs:
                        # Bazı versiyonlarda liste, bazılarında async generator döner
                        maybe_res = ddgs.text(query, max_results=n)
                        res = await maybe_res if isawaitable(maybe_res) else maybe_res
                        # Eğer dönen nesne async generator ise
                        if hasattr(res, "__aiter__"):
                            return [r async for r in res]
                        return list(res)

                # Olası takılmalara karşı zaman aşımı koruması
                results = await asyncio.wait_for(_async_search(), timeout=self.FETCH_TIMEOUT)

            else:
                # AsyncDDGS yoksa (Örn: DDG SDK v8+), standart DDGS'i güvenli thread'de çalıştır
                from duckduckgo_search import DDGS

                def _sync_search() -> list[dict[str, Any]]:
                    with DDGS() as ddgs:
                        return list(ddgs.text(query, max_results=n))

                # Thread işlemini de timeout ile sınırlandır (Sessiz bloklanmaları önler)
                thread_task = asyncio.create_task(asyncio.to_thread(_sync_search))
                try:
                    results = await asyncio.wait_for(
                        thread_task,
                        timeout=self.FETCH_TIMEOUT,
                    )
                except Exception:
                    thread_task.cancel()
                    raise

            if not results:
                return True, self._mark_no_results(
                    f"'{query}' için DuckDuckGo'da sonuç bulunamadı."
                )

            lines = [f"[Web Arama (DuckDuckGo): {query}]", ""]
            for i, r in enumerate(results, 1):
                title = r.get("title", "Başlıksız")
                body = (r.get("body") or "")[:300].rstrip()
                href = r.get("href", "")
                lines.append(f"{i}. **{title}**")
                if body:
                    lines.append(f"   {body}")
                lines.append(f"   → {href}\n")

            return True, "\n".join(lines)

        except TimeoutError:
            logger.warning("DuckDuckGo araması zaman aşımına uğradı (%s sn).", self.FETCH_TIMEOUT)
            return False, f"[HATA] DuckDuckGo: Zaman aşımı ({self.FETCH_TIMEOUT}sn)"
        except Exception as exc:
            logger.warning("DuckDuckGo hatası: %s", exc)
            return False, f"[HATA] DuckDuckGo: {exc}"

    # ─────────────────────────────────────────────
    #  URL İÇERİĞİ ÇEKME (ASYNC)
    # ─────────────────────────────────────────────

    async def scrape_url(self, url: str) -> str:
        """Web sayfası içeriğini temizleyip bağlam güvenli şekilde döndürür."""
        try:
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                resp.encoding = "utf-8"

            text = self._clean_html(resp.text)
            text = self._truncate_content(text)
            return text
        except httpx.TimeoutException:
            return f"Hata: Sayfa içeriği çekilemedi - zaman aşımı ({url})"
        except httpx.RequestError as exc:
            return f"Hata: Sayfa içeriği çekilemedi - bağlantı/istek hatası ({exc})"
        except httpx.HTTPStatusError as exc:
            return f"Hata: Sayfa içeriği çekilemedi - HTTP {exc.response.status_code}"
        except Exception as exc:
            logger.error("URL çekme hatası: %s", exc)
            return f"Hata: Sayfa içeriği çekilemedi - {exc}"

    async def fetch_url(self, url: str) -> tuple[bool, str]:
        """Geriye dönük uyumluluk: fetch_url araç çağrısını yeni scrape akışına yönlendirir."""
        text = await self.scrape_url(url)
        if text.startswith("Hata: Sayfa içeriği çekilemedi"):
            return False, text
        return True, f"[URL: {url}]\n\n{text}"

    def _truncate_content(self, text: str) -> str:
        try:
            configured_limit = int(self.FETCH_MAX_CHARS)
        except (TypeError, ValueError):
            configured_limit = self.FETCH_MAX_CHARS = 12000

        max_len = max(1000, configured_limit)
        if len(text) <= max_len:
            return text
        return text[:max_len] + "... [İçerik çok uzun olduğu için kesildi]"

    @staticmethod
    def _clean_html(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        clean = soup.get_text(separator=" ", strip=True)
        clean = unescape(clean)
        clean = " ".join(clean.split())
        return clean.strip()

    # ─────────────────────────────────────────────
    #  DOKÜMANTASYON ARAMALARI (ASYNC)
    # ─────────────────────────────────────────────

    async def search_docs(self, library: str, topic: str = "") -> tuple[bool, str]:
        base = f"{library} {topic} documentation".strip()
        # Tavily veya Google varsa site: filtresi ekle; DDG'de OR operatörü güvenilmez
        if self.tavily_key or (self.google_key and self.google_cx):
            q = (
                base + " site:docs.python.org OR site:pypi.org"
                " OR site:readthedocs.io OR site:github.com"
            )
        else:
            # DDG: site: filtresi yerine hedef odaklı arama terimi kullan
            q = f"{library} {topic} official docs reference".strip()
        return await self.search(q, max_results=5)

    async def search_stackoverflow(self, query: str) -> tuple[bool, str]:
        # site:stackoverflow.com Tavily/Google'da çalışır; DDG'de kısmen desteklenir
        if self.tavily_key or (self.google_key and self.google_cx):
            q = f"site:stackoverflow.com {query}"
        else:
            q = f"stackoverflow {query}"
        return await self.search(q, max_results=5)

    @classmethod
    def _mark_no_results(cls, text: str) -> str:
        return f"{cls._NO_RESULTS_PREFIX} {text}"

    @classmethod
    def _is_actionable_result(cls, ok: bool, result_text: str) -> bool:
        return ok and not result_text.startswith(cls._NO_RESULTS_PREFIX)

    @classmethod
    def _normalize_result_text(cls, result_text: str) -> str:
        if result_text.startswith(cls._NO_RESULTS_PREFIX):
            return result_text[len(cls._NO_RESULTS_PREFIX) :].strip()
        return result_text

    def __repr__(self) -> str:
        engines = []
        if self.tavily_key:
            engines.append("Tavily")
        if self.google_key and self.google_cx:
            engines.append("Google")
        if self._ddg_available:
            engines.append("DuckDuckGo")
        return f"<WebSearchManager engine={self.engine} available={[e for e in engines]}>"
