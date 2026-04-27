"""
Sidar Project - Otomatik Komut İşleyici
Kullanıcı girdisindeki ortak kalıpları otomatik olarak tanır ve işler (Asenkron Uyumlu).
"""

import asyncio
import inspect
import re

from core.memory import ConversationMemory
from core.rag import DocumentStore
from managers.code_manager import CodeManager
from managers.github_manager import GitHubManager
from managers.package_info import PackageInfoManager
from managers.system_health import SystemHealthManager
from managers.web_search import WebSearchManager


class AutoHandle:
    """
    Kullanıcı mesajlarını anahtar kelime örüntülerine göre analiz eder
    ve uygun manager metodunu çağırır.

    Dönen değer: (işlendi_mi: bool, yanıt: str)
    """

    def __init__(
        self,
        code: CodeManager,
        health: SystemHealthManager,
        github: GitHubManager,
        memory: ConversationMemory,
        web: WebSearchManager,
        pkg: PackageInfoManager,
        docs: DocumentStore,
        cfg=None,
    ) -> None:
        self.code = code
        self.health = health
        self.github = github
        self.memory = memory
        self.web = web
        self.pkg = pkg
        self.docs = docs
        self.cfg = cfg
        self.command_timeout = float(getattr(cfg, "AUTO_HANDLE_TIMEOUT", 12)) if cfg else 12.0

    # ─────────────────────────────────────────────
    #  ANA GİRİŞ NOKTASI (ASYNC)
    # ─────────────────────────────────────────────

    # Çok adımlı komutları tespit eden regex: "ardından", "sonrasında", numaralı adımlar vb.
    # Bu ifadeler varsa AutoHandle tek adım döndüremez → ReAct'a bırak.
    _MULTI_STEP_RE = re.compile(
        r"\bardından\b|\bsonrasında\b|\bönce\b.{1,60}\bsonra\b"
        r"|\b\d+\s*[\.\)]\s+\w|\bve\s+ardından\b|\bşunları\s+(yap|bul|göster|listele)\b"
        r"|\bfirst\b.{0,200}\bthen\b|\bstep\s*\d|\bnext\b",
        re.IGNORECASE | re.DOTALL,
    )

    _DOT_CMD_RE = re.compile(r"^\s*\.(status|health|clear|audit|gpu)\b", re.IGNORECASE)

    async def handle(self, text: str) -> tuple[bool, str]:
        """
        text: kullanıcı mesajı

        Returns:
            (True, yanıt)  — otomatik işlendiyse
            (False, "")    — LLM'e ilet
        """
        t = text.lower().strip()

        # Çok uzun girdiler otomatik işlenemez → ReAct'a bırak (ReDoS koruması)
        if len(text) > 2000:
            return False, ""

        # Nokta önekli kısayol komutları (CLI standardı): .status, .health, .clear vb.
        result = await self._try_dot_command(text, t)
        if result[0]:
            return result

        # Çok adımlı komutlar (ardından, önce...sonra, 1. ... 2. ...) direkt ReAct'a gider.
        # AutoHandle tek adım döndürdüğü için zincirli istekleri kırar.
        if self._MULTI_STEP_RE.search(text):
            return False, ""

        # ── Temel araçlar (Senkron) ──────────────────────────
        result = await self._try_clear_memory(t)
        if result[0]:
            return result

        result = await asyncio.to_thread(self._try_list_directory, t, text)
        if result[0]:
            return result

        result = await asyncio.to_thread(self._try_read_file, t, text)
        if result[0]:
            return result

        result = await self._try_audit(t)
        if result[0]:
            return result

        result = await self._try_health(t)
        if result[0]:
            return result

        result = await self._try_gpu_optimize(t)
        if result[0]:
            return result

        result = await asyncio.to_thread(self._try_validate_file, t, text)
        if result[0]:
            return result

        result = self._try_github_commits(t)
        if result[0]:
            return result

        result = self._try_github_info(t)
        if result[0]:
            return result

        result = self._try_github_list_files(t)
        if result[0]:
            return result

        result = self._try_github_read(t, text)
        if result[0]:
            return result

        result = self._try_github_list_prs(t, text)
        if result[0]:
            return result

        result = await self._try_github_get_pr(t, text)
        if result[0]:
            return result

        result = self._try_security_status(t)
        if result[0]:
            return result

        # ── Web Arama araçları (ASENKRON) ─────────────────────
        result = await self._try_web_search(t, text)
        if result[0]:
            return result

        result = await self._try_fetch_url(t, text)
        if result[0]:
            return result

        result = await self._try_search_docs(t, text)
        if result[0]:
            return result

        result = await self._try_search_stackoverflow(t, text)
        if result[0]:
            return result

        # ── Paket Bilgi araçları (ASENKRON) ───────────────────
        result = await self._try_pypi(t, text)
        if result[0]:
            return result

        result = await self._try_npm(t, text)
        if result[0]:
            return result

        result = await self._try_gh_releases(t, text)
        if result[0]:
            return result

        # ── RAG / Belge Deposu ────────────────────────────────
        result = await self._try_docs_search(t, text)
        if result[0]:
            return result

        result = await self._try_docs_add(t, text)
        if result[0]:
            return result

        result = self._try_docs_list(t, text)
        if result[0]:
            return result

        return False, ""

    async def _try_dot_command(self, raw: str, t: str) -> tuple[bool, str]:
        """CLI ile uyumlu nokta-komut kısayollarını işler."""
        m = self._DOT_CMD_RE.match(raw.strip())
        if not m:
            return False, ""
        cmd = m.group(1).lower()
        if cmd in ("status", "health"):
            return await self._try_health(f".{cmd}")
        if cmd == "clear":
            return await self._try_clear_memory(".clear")
        if cmd == "audit":
            return await self._try_audit(".audit")
        if cmd == "gpu":
            return await self._try_gpu_optimize(".gpu")
        return False, ""

    async def _run_blocking(self, func, *args):
        """Senkron manager çağrılarını event-loop'u bloklamadan çalıştır."""
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args),
            timeout=self.command_timeout,
        )

    # ─────────────────────────────────────────────
    #  TEMEL ARAÇ İŞLEYİCİLERİ (SENKRON)
    # ─────────────────────────────────────────────

    def _try_list_directory(self, t: str, raw: str) -> tuple[bool, str]:
        # "listele" tek başına çok geniş; yalnızca açıkça dizin/klasör bağlamı varsa tetikle.
        # "commit listele", "test fonksiyonlarını listele" gibi ifadeler yanlışlıkla eşleşmesin.
        if re.search(
            r"dizin\s+listele|klasör.*listele|klasör.*içer|dosyaları\s+göster"
            r"|kök\s+dizin.*listele|proje.*dizin.*listele|ls\b",
            t,
        ):
            # Path extraction: bulunursa dizin, bulunmazsa "."
            path = self._extract_dir_path(raw) or "."
            _, result = self.code.list_directory(path)
            return True, result
        return False, ""

    def _try_read_file(self, t: str, raw: str) -> tuple[bool, str]:
        # "göster" ve "içeriğ" çok geniş — execute_code, health, docs_add gibi komutları
        # yanlışlıkla yakalar. Yalnızca açık dosya okuma bağlamında tetikle.
        if re.search(
            r"(dosyayı?\s+oku|dosya\s+içeriğini\s+göster|dosya\s+içeriğini\s+getir"
            r"|içeriğini\s+getir|file\s+content|incele\b|cat\b)",
            t,
        ):
            path = self._extract_path(raw) or self.memory.get_last_file()
            if not path:
                return True, "⚠ Hangi dosyayı okumamı istiyorsunuz? Lütfen dosya yolunu belirtin."
            ok, content = self.code.read_file(path)
            if ok:
                self.memory.set_last_file(path)
                lines = content.splitlines()
                preview = "\n".join(lines[:80])
                suffix = f"\n... ({len(lines) - 80} satır daha)" if len(lines) > 80 else ""
                return True, f"[{path}]\n```\n{preview}{suffix}\n```"
            return True, f"✗ {content}"
        return False, ""

    async def _try_audit(self, t: str) -> tuple[bool, str]:
        if re.search(r"^\.audit\b|denetle|sistemi\s+tara|audit|teknik\s+rapor|kod.*kontrol", t):
            try:
                result = await self._run_blocking(self.code.audit_project, ".")
                return True, result
            except TimeoutError:
                return True, "⚠ Denetim işlemi zaman aşımına uğradı."
            except Exception as exc:
                return True, f"⚠ Denetim sırasında hata oluştu: {exc}"
        return False, ""

    async def _try_health(self, t: str) -> tuple[bool, str]:
        # "GPU durumunu göster" ve "CPU/RAM göster" ifadelerini de yakalamak için
        # "göster" bağlamını buraya ekledik — ancak yalnızca donanım keyword'leri ile birlikte.
        if re.search(
            r"^\.(status|health)\b|sistem.*sağlık|donanım\s+(durumu|rapor|göster)|hardware"
            r"|sağlık.*rapor|cpu.*durumu|ram.*durumu|gpu.*durum"
            r"|sistem.*rapor|memory.*report",
            t,
        ):
            if not self.health:
                return True, "⚠ Sistem sağlık monitörü başlatılamadı."
            try:
                result = await self._run_blocking(self.health.full_report)
                return True, result
            except TimeoutError:
                return True, "⚠ Sağlık raporu zaman aşımına uğradı."
            except Exception as exc:
                return True, f"⚠ Sağlık raporu alınamadı: {exc}"
        return False, ""

    async def _try_gpu_optimize(self, t: str) -> tuple[bool, str]:
        if re.search(r"^\.gpu\b|gpu.*(optimize|temizle|boşalt|clear)|vram", t):
            if not self.health:
                return True, "⚠ Sistem sağlık monitörü başlatılamadı."
            try:
                result = await self._run_blocking(self.health.optimize_gpu_memory)
                return True, result
            except TimeoutError:
                return True, "⚠ GPU optimizasyonu zaman aşımına uğradı."
            except Exception as exc:
                return True, f"⚠ GPU optimizasyonu başarısız: {exc}"
        return False, ""

    def _try_validate_file(self, t: str, raw: str) -> tuple[bool, str]:
        # "kontrol et" çok geniş — "httpx sürümünü kontrol et", "GPU durumunu kontrol et" gibi
        # ifadeleri hatalıca yakalar. Yalnızca açık sözdizimi/dosya doğrulama bağlamında tetikle.
        if re.search(r"sözdizimi|syntax|python\s+doğrula|validate.*dosya|dosya.*doğrula", t):
            path = self._extract_path(raw) or self.memory.get_last_file()
            if not path:
                return True, "⚠ Doğrulanacak dosya yolunu belirtin."
            ok, content = self.code.read_file(path)
            if not ok:
                return True, f"✗ Dosya okunamadı: {content}"
            if path.endswith(".py"):
                ok, msg = self.code.validate_python_syntax(content)
            elif path.endswith(".json"):
                ok, msg = self.code.validate_json(content)
            else:
                return True, f"⚠ {path} için sözdizimi doğrulama desteklenmiyor."
            icon = "✓" if ok else "✗"
            return True, f"{icon} {msg}"
        return False, ""

    def _try_github_commits(self, t: str) -> tuple[bool, str]:
        # "son.*commit" + "listele" genel "listele" regex'inden önce çalışmalı;
        # "commit'i getir", "commit'leri göster", "commit geçmişi" gibi ifadeleri de yakala.
        if re.search(
            r"(github|commit).*(listele|göster|son|last|getir|geçmiş)"
            r"|son.*commit|commit.*geçmiş|commit.*listele",
            t,
        ):
            if not self.github.is_available():
                return True, "⚠ GitHub token ayarlanmamış."
            m = re.search(r"(\d+)\s*commit", t)
            n = int(m.group(1)) if m else 10
            _, result = self.github.list_commits(n=n)
            return True, result
        return False, ""

    def _try_github_info(self, t: str) -> tuple[bool, str]:
        # Yanlış-pozitifleri azalt: yalnızca açık bilgi/özet niyeti varsa tetikle.
        if re.search(
            r"(?:github|repo|depo).*(?:bilgi|info|özet|durum|detay)"
            r"|(?:bilgi|info|özet|durum|detay).*(?:github|repo|depo)",
            t,
        ):
            if not self.github.is_available():
                return True, "⚠ GitHub token ayarlanmamış."
            _, result = self.github.get_repo_info()
            return True, result
        return False, ""

    def _try_github_list_files(self, t: str) -> tuple[bool, str]:
        """Repo dosyalarını listele: 'repodaki dosyaları listele' vb."""
        if re.search(
            r"(github|repo|depo).*(dosya|içerik).*(listele|göster|getir)"
            r"|(dosya|içerik).*(listele|göster|getir).*(github|repo|depo)",
            t,
        ):
            if not self.github.is_available():
                return True, "⚠ GitHub token ayarlanmamış."
            _, result = self.github.list_files("")
            return True, result
        return False, ""

    def _try_github_read(self, t: str, raw: str) -> tuple[bool, str]:
        if re.search(r"github.*(oku|dosya|file)|uzak.*dosya", t):
            if not self.github.is_available():
                return True, "⚠ GitHub token ayarlanmamış."
            path = self._extract_path(raw)
            if not path:
                return True, "⚠ Okunacak GitHub dosya yolunu belirtin."
            ok, content = self.github.read_remote_file(path)
            return True, content if ok else f"✗ {content}"
        return False, ""

    def _try_github_list_prs(self, t: str, raw: str) -> tuple[bool, str]:
        """PR listesi — 'PR listele', 'açık pull requestler', 'kapalı PR'lar' vb."""
        if re.search(
            r"(pr|pull.?request).*(listele|listesi|göster|getir|var\s+m[ıi])"
            r"|(açık|kapalı|tüm).*(pr|pull.?request)"
            r"|pull.?request.*listele",
            t,
        ):
            if not self.github.is_available():
                return True, "⚠ GitHub token ayarlanmamış."
            # Durum tespiti: açık / kapalı / tüm
            if re.search(r"kapalı|closed|kapanmış", t):
                state = "closed"
            elif re.search(r"tüm|hepsi|all", t):
                state = "all"
            else:
                state = "open"
            m = re.search(r"(\d+)\s*(?:pr|pull)", t)
            limit = int(m.group(1)) if m else 10
            _, result = self.github.list_pull_requests(state=state, limit=limit)
            return True, result
        return False, ""

    async def _try_github_get_pr(self, t: str, raw: str) -> tuple[bool, str]:
        """PR detay sorgulama — 'PR #5 detayı', '#12 pull request' vb."""
        m = re.search(
            r"(?:pr|pull.?request)\s*#?(\d+)"
            r"|#(\d+)\s*(?:pr|pull.?request)"
            r"|(\d+)(?:\.?\s*numaral[ıi]|\.?\s*no.?lu)\s*(?:pr|pull.?request)",
            t,
        )
        if m:
            number = int(next(g for g in m.groups() if g is not None))
            # "dosyaları" veya "yorum" alt komutu var mı?
            if re.search(r"dosya|file|değişiklik", t):
                if not self.github.is_available():
                    return True, "⚠ GitHub token ayarlanmamış."
                _, result = self.github.get_pr_files(number)
                return True, result
            # Varsayılan: detay
            if not self.github.is_available():
                return True, "⚠ GitHub token ayarlanmamış."
            _, result = self.github.get_pull_request(number)
            return True, result
        return False, ""

    def _try_security_status(self, t: str) -> tuple[bool, str]:
        # "güvenlik" ve "erişim" çok geniş — "güvenlik açısından incele" gibi analiz
        # isteklerini de yakalayıp security.status_report() döndürüyor.
        # Yalnızca açıkça erişim seviyesi veya OpenClaw durumu sorulduğunda tetikle.
        if re.search(
            r"openclaw|erişim\s+seviyesi|access\s+level|güvenlik\s+seviyesi"
            r"|sandbox.*mod|yetki\s+seviyesi",
            t,
        ):
            return True, self.code.security.status_report()
        return False, ""

    async def _try_clear_memory(self, t: str) -> tuple[bool, str]:
        """'.clear' veya doğal dil temizleme komutlarını işler."""
        if re.search(
            r"^\.clear\b|bell[eə][ğg]i?\s+(temizle|sıfırla|sil|resetle)"
            r"|sohbet[i]?\s+(temizle|sıfırla|sil|resetle)"
            r"|konuşma[yı]?\s+(temizle|sıfırla|sil|resetle)"
            r"|hafıza[yı]?\s+(temizle|sıfırla|sil|resetle)",
            t,
        ):
            clear_result = self.memory.clear()
            if inspect.isawaitable(clear_result):
                await clear_result
            return True, "✓ Konuşma belleği temizlendi."
        return False, ""

    # ─────────────────────────────────────────────
    #  WEB ARAMA İŞLEYİCİLERİ (ASENKRON)
    # ─────────────────────────────────────────────

    async def _try_web_search(self, t: str, raw: str) -> tuple[bool, str]:
        """Web araması — 'web'de ara', 'internette ara', 'google:' vb."""
        m = re.search(
            r"(?:web.?de\s+ara|internette\s+ara|google\s*:|search\s*:)\s*(.+)",
            t,
        )
        if m:
            query = m.group(1).strip()
            if not query:
                return True, "⚠ Arama sorgusu belirtilmedi."
            _, result = await self.web.search(query)
            return True, result
        return False, ""

    async def _try_fetch_url(self, t: str, raw: str) -> tuple[bool, str]:
        """URL içerik çekme — 'url oku', 'fetch url' vb."""
        if re.search(r"url.*(oku|çek|getir|fetch)|fetch.*url", t):
            url = self._extract_url(raw)
            if not url:
                return True, "⚠ Geçerli bir URL bulunamadı."
            _, result = await self.web.fetch_url(url)
            return True, result
        return False, ""

    async def _try_search_docs(self, t: str, raw: str) -> tuple[bool, str]:
        """Dokümantasyon araması — 'docs ara fastapi', 'dokümantasyon' vb."""
        m = re.search(
            r"(?:docs?\s+ara|dokümantasyon\s+ara|resmi\s+docs?)\s*[:\-]?\s*(.+)",
            t,
        )
        if m:
            parts = m.group(1).strip().split(" ", 1)
            lib = parts[0]
            topic = parts[1] if len(parts) > 1 else ""
            _, result = await self.web.search_docs(lib, topic)
            return True, result
        return False, ""

    async def _try_search_stackoverflow(self, t: str, raw: str) -> tuple[bool, str]:
        """Stack Overflow araması — 'stackoverflow: python async' vb."""
        m = re.search(r"(?:stackoverflow|so)\s*[:\-]\s*(.+)", t)
        if m:
            query = m.group(1).strip()
            _, result = await self.web.search_stackoverflow(query)
            return True, result
        return False, ""

    # ─────────────────────────────────────────────
    #  PAKET BİLGİ İŞLEYİCİLERİ (ASENKRON)
    # ─────────────────────────────────────────────

    async def _try_pypi(self, t: str, raw: str) -> tuple[bool, str]:
        """PyPI paket sorgusu — 'pypi requests', 'paket bilgisi fastapi' vb."""
        m = re.search(
            r"(?:pypi|pip\s+show|paket\s+bilgisi?|python\s+paketi?)\s*[:\-]?\s*([\w\-_.]+)",
            t,
        )
        if m:
            package = m.group(1).strip()
            # Sürüm karşılaştırma: "pypi requests 2.31.0"
            ver_m = re.search(r"(?:pypi|pip\s+show|paket\s+bilgisi?)\s+[\w\-_.]+\s+([\d.]+)", t)
            if ver_m:
                _, result = await self.pkg.pypi_compare(package, ver_m.group(1))
            else:
                _, result = await self.pkg.pypi_info(package)
            return True, result
        return False, ""

    async def _try_npm(self, t: str, raw: str) -> tuple[bool, str]:
        """npm paket sorgusu — 'npm react', 'node paketi axios' vb."""
        m = re.search(
            r"(?:npm|node\s+paketi?|js\s+paketi?)\s*[:\-]?\s*([@\w\-_./]+)",
            t,
        )
        if m:
            package = m.group(1).strip()
            _, result = await self.pkg.npm_info(package)
            return True, result
        return False, ""

    async def _try_gh_releases(self, t: str, raw: str) -> tuple[bool, str]:
        """GitHub releases sorgusu — 'github releases tiangolo/fastapi' vb."""
        m = re.search(
            r"(?:github\s+releases?|gh\s+releases?|sürümler)\s*[:\-]?\s*([\w\-_.]+/[\w\-_.]+)",
            t,
        )
        if m:
            repo = m.group(1).strip()
            _, result = await self.pkg.github_releases(repo)
            return True, result
        return False, ""

    # ─────────────────────────────────────────────
    #  RAG / BELGE DEPOSU İŞLEYİCİLERİ (SENKRON)
    # ─────────────────────────────────────────────

    async def _try_docs_search(self, t: str, raw: str) -> tuple[bool, str]:
        """Belge deposunda arama — 'depoda ara', 'bilgi bankası', 'rag ara vektör:' vb."""
        m = re.search(
            r"(?:depoda\s+ara|bilgi\s+bankası|rag\s+ara|belgeler.*ara)\s*[:\-]?\s*(.+)",
            t,
        )
        if m:
            query_raw = m.group(1).strip()
            # Opsiyonel motor seçimi: "sorgu mode:vector" veya "vector: sorgu"
            mode_m = re.search(r"\bmode:(auto|vector|bm25|keyword)\b", query_raw, re.IGNORECASE)
            if mode_m:
                mode = mode_m.group(1).lower()
                query = query_raw[: mode_m.start()].strip() or query_raw[mode_m.end() :].strip()
            else:
                mode = "auto"
                query = query_raw
            result_obj = await asyncio.to_thread(self.docs.search, query, None, mode)
            if inspect.isawaitable(result_obj):
                result_obj = await result_obj
            _, result = result_obj
            return True, result
        return False, ""

    def _try_docs_list(self, t: str, raw: str) -> tuple[bool, str]:
        """Belge deposunu listele."""
        if re.search(r"belge.*listele|belge\s+deposu.*listele|rag.*listele|döküman.*listele", t):
            return True, self.docs.list_documents()
        return False, ""

    async def _try_docs_add(self, t: str, raw: str) -> tuple[bool, str]:
        """URL'den belge deposuna ekle — 'belge ekle/deposuna ekle https://...' vb."""
        m = re.search(
            r"(?:belge\s+ekle|belge\s+depos[ıu]na\s+ekle|dokümana?\s+ekle|rag.*ekle"
            r"|url.*belge.*ekle|ekle.*belge\s+depos)\s*(https?://\S+)",
            raw,
            re.IGNORECASE,
        )
        if not m:
            # İkincil form: URL mevcut ve "belge/depo/rag" + "ekle" kelimesi varsa
            url_m = re.search(r"(https?://\S+)", raw)
            if url_m and re.search(r"belge|depo|rag", t) and re.search(r"ekle", t):
                m_url = url_m.group(1).strip()
                title_m = re.search(r'"([^"]+)"', raw)
                title = title_m.group(1) if title_m else ""
                _, result = await self.docs.add_document_from_url(m_url, title=title)
                return True, result
        if m:
            url = m.group(1).strip()
            title_m = re.search(r'"([^"]+)"', raw)
            title = title_m.group(1) if title_m else ""
            _, result = await self.docs.add_document_from_url(url, title=title)
            return True, result
        return False, ""

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    def _extract_path(self, text: str) -> str | None:
        """Metinden dosya yolu çıkar (uzantılı dosyalar için)."""
        m = re.search(r'["\']([^"\']+\.[a-zA-Z]{1,6})["\']', text)
        if m:
            return m.group(1)
        m = re.search(
            r"\b([\w/\\.\-]+\.(?:py|json|md|txt|yaml|yml|js|ts|sh|toml|cfg|ini))\b",
            text,
        )
        if m:
            return m.group(1)
        return None

    def _extract_dir_path(self, text: str) -> str | None:
        """Metinden dizin yolu çıkar (dosya adı içermeyen yollar için).
        Uzantılı dosya adlarını dizin olarak döndürmez; yalnızca açık dizin yolları alınır.
        """
        # Tırnak içindeki yol varsa ve uzantı içermiyorsa dizin say
        m = re.search(r'["\']([^"\']+)["\']', text)
        if m and "." not in m.group(1).split("/")[-1]:
            return m.group(1)
        # Açık dizin belirteçleri: "./", "../", "/home/..."
        m = re.search(r"(\./[\w/\\.\-]+|\.\.?/[\w/\\.\-]*|/[\w/\\.\-]{3,})", text)
        if m:
            candidate = m.group(1)
            # Uzantılı dosya yoluysa dizin değil, atla
            if re.search(r"\.\w{1,6}$", candidate):
                return None
            return candidate
        return None

    def _extract_url(self, text: str) -> str | None:
        """Metinden URL çıkar."""
        m = re.search(r'https?://[^\s"\'<>]+', text)
        return m.group(0) if m else None
