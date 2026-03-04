"""
Sidar Project - Web Arama Yöneticisi
Tavily, Google Custom Search ve DuckDuckGo motorları ile asenkron web araması.
Sürüm: 2.7.0

Motor öncelik sırası (auto modu): Tavily → Google → DuckDuckGo
"""

import asyncio
import logging
import re
from html import unescape
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class WebSearchManager:
    """
    Gelişmiş, çoklu motor destekli ve asenkron web arama yöneticisi.
    DuckDuckGo, Tavily ve Google Custom Search API'lerini destekler.
    """

    MAX_RESULTS = 5
    FETCH_TIMEOUT = 15  # saniye
    FETCH_MAX_CHARS = 4000

    _NO_RESULTS_PREFIX = "[NO_RESULTS]"

    def __init__(self, config=None) -> None:
        if config is not None:
            self.engine = getattr(config, "SEARCH_ENGINE", "auto").lower()
            self.tavily_key = getattr(config, "TAVILY_API_KEY", "")
            self.google_key = getattr(config, "GOOGLE_SEARCH_API_KEY", "")
            self.google_cx = getattr(config, "GOOGLE_SEARCH_CX", "")
            
            self.MAX_RESULTS = getattr(config, "WEB_SEARCH_MAX_RESULTS", self.MAX_RESULTS)
            self.FETCH_TIMEOUT = getattr(config, "WEB_FETCH_TIMEOUT", self.FETCH_TIMEOUT)
            self.FETCH_MAX_CHARS = getattr(config, "WEB_FETCH_MAX_CHARS", self.FETCH_MAX_CHARS)
        else:
            self.engine = "auto"
            self.tavily_key = ""
            self.google_key = ""
            self.google_cx = ""

        self._ddg_available = self._check_ddg()

    def _check_ddg(self) -> bool:
        try:
            # v8 uyumlu import (AsyncDDGS yerine standart DDGS)
            from duckduckgo_search import DDGS  # noqa: F401
            return True
        except ImportError as e:
            logger.debug(f"DDG Import hatası: {e}")
            return False

    def is_available(self) -> bool:
        """En az bir arama motoru çalışabilir durumda mı?"""
        return self._ddg_available or bool(self.tavily_key) or bool(self.google_key and self.google_cx)

    def status(self) -> str:
        engines = []
        if self.tavily_key: engines.append("Tavily")
        if self.google_key and self.google_cx: engines.append("Google")
        if self._ddg_available: engines.append("DuckDuckGo")
        
        if not engines:
            return "WebSearch: Kurulu veya yapılandırılmış motor yok."
            
        return f"WebSearch: Aktif (Mod: {self.engine.upper()}) | {', '.join(engines)}"

    # ─────────────────────────────────────────────
    #  ANA ARAMA YÖNLENDİRİCİ (ASYNC)
    # ─────────────────────────────────────────────

    async def search(self, query: str, max_results: Optional[int] = None) -> Tuple[bool, str]:
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
            if ok:
                return True, self._normalize_result_text(res)
            # 401/403 veya başka bir hata → aşağıdaki auto-fallback'e düş
            logger.info("Tavily başarısız; otomatik fallback başlatılıyor.")
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

    async def _search_tavily(self, query: str, n: int) -> Tuple[bool, str]:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "max_results": n
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
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
                if body: lines.append(f"   {body}")
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

    async def _search_google(self, query: str, n: int) -> Tuple[bool, str]:
        url = "https://customsearch.googleapis.com/customsearch/v1"
        params = {
            "key": self.google_key,
            "cx": self.google_cx,
            "q": query,
            "num": min(n, 10)
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
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
                if body: lines.append(f"   {body}")
                lines.append(f"   → {href}\n")

            return True, "\n".join(lines)
        except Exception as exc:
            logger.warning("Google API hatası: %s", exc)
            return False, f"[HATA] Google Search: {exc}"

    async def _search_duckduckgo(self, query: str, n: int) -> Tuple[bool, str]:
        try:
            from duckduckgo_search import DDGS

            # v8 güncellemesi için DDGS'yi asenkron thread'de çalıştırıyoruz
            def _sync_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=n))

            results = await asyncio.to_thread(_sync_search)

            if not results:
                return True, self._mark_no_results(f"'{query}' için DuckDuckGo'da sonuç bulunamadı.")

            lines = [f"[Web Arama (DuckDuckGo): {query}]", ""]
            for i, r in enumerate(results, 1):
                title = r.get("title", "Başlıksız")
                body = (r.get("body") or "")[:300].rstrip()
                href = r.get("href", "")
                lines.append(f"{i}. **{title}**")
                if body: lines.append(f"   {body}")
                lines.append(f"   → {href}\n")

            return True, "\n".join(lines)
        except Exception as exc:
            logger.warning("DuckDuckGo hatası: %s", exc)
            return False, f"[HATA] DuckDuckGo: {exc}"

    # ─────────────────────────────────────────────
    #  URL İÇERİĞİ ÇEKME (ASYNC)
    # ─────────────────────────────────────────────

    async def fetch_url(self, url: str) -> Tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=self.FETCH_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; SidarBot/1.0)"}
                )
                resp.raise_for_status()
                
                text = self._clean_html(resp.text)
                truncated = text[: self.FETCH_MAX_CHARS]
                suffix = f"\n... ({len(text) - self.FETCH_MAX_CHARS} karakter daha)" if len(text) > self.FETCH_MAX_CHARS else ""
                
                return True, f"[URL: {url}]\n\n{truncated}{suffix}"
                
        except httpx.TimeoutException:
            return False, f"[HATA] URL zaman aşımı: {url}"
        except httpx.RequestError as exc:
            return False, f"[HATA] URL bağlantı/istek hatası: {url} - {exc}"
        except httpx.HTTPStatusError as exc:
            return False, f"[HATA] HTTP Hata Kodu {exc.response.status_code}: {url}"
        except Exception as exc:
            logger.error("URL çekme hatası: %s", exc)
            return False, f"[HATA] URL çekme: {exc}"

    @staticmethod
    def _clean_html(html: str) -> str:
        clean = re.sub(
            r"<(script|style)[^>]*>.*?</(script|style)>",
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        clean = re.sub(r"<[^>]+>", " ", clean)
        # HTML entity decode (named + numeric)
        clean = unescape(clean)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    # ─────────────────────────────────────────────
    #  DOKÜMANTASYON ARAMALARI (ASYNC)
    # ─────────────────────────────────────────────

    async def search_docs(self, library: str, topic: str = "") -> Tuple[bool, str]:
        base = f"{library} {topic} documentation".strip()
        # Tavily veya Google varsa site: filtresi ekle; DDG'de OR operatörü güvenilmez
        if self.tavily_key or (self.google_key and self.google_cx):
            q = (base + " site:docs.python.org OR site:pypi.org"
                 " OR site:readthedocs.io OR site:github.com")
        else:
            # DDG: site: filtresi yerine hedef odaklı arama terimi kullan
            q = f"{library} {topic} official docs reference".strip()
        return await self.search(q, max_results=5)

    async def search_stackoverflow(self, query: str) -> Tuple[bool, str]:
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
            return result_text[len(cls._NO_RESULTS_PREFIX):].strip()
        return result_text

    def __repr__(self) -> str:
        engines = []
        if self.tavily_key:
            engines.append("Tavily")
        if self.google_key and self.google_cx:
            engines.append("Google")
        if self._ddg_available:
            engines.append("DuckDuckGo")
        return (
            f"<WebSearchManager engine={self.engine} "
            f"available={[e for e in engines]}>"
        )  