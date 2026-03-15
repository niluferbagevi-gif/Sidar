"""
Sidar Project - Ana Ajan
Supervisor tabanlı multi-agent omurgasıyla çalışan yazılım mühendisi AI asistanı (Asenkron).
"""

import logging
import asyncio
import inspect
import time
import threading
from pathlib import Path
from typing import Optional, AsyncIterator, Dict, List
from pydantic import BaseModel

try:
    from opentelemetry import trace
except Exception:  # OpenTelemetry opsiyoneldir
    trace = None

from config import Config
from core.memory import ConversationMemory
from core.llm_client import LLMClient
from core.rag import DocumentStore
from managers.code_manager import CodeManager
from managers.system_health import SystemHealthManager
from managers.github_manager import GitHubManager
from managers.security import SecurityManager
from managers.web_search import WebSearchManager
from managers.package_info import PackageInfoManager
from managers.todo_manager import TodoManager

logger = logging.getLogger(__name__)


class ToolCall(BaseModel):
    """LLM araç çağrılarının doğrulanması için standart şema."""

    thought: str
    tool: str
    argument: str

class SidarAgent:
    """
    Sidar — Yazılım Mimarı ve Baş Mühendis AI Asistanı.
    Tamamen asenkron ağ istekleri, stream, yapısal veri ve sonsuz vektör hafıza uyumlu yapı.
    """

    VERSION = "3.0.0"  # Kurumsal/SaaS v3.0.0 final sürüm etiketi

    def __init__(self, cfg: Config = None) -> None:
        self.cfg = cfg or Config()
        self._lock = None  # Asenkron Lock, respond çağrıldığında yaratılacak

        # Alt sistemler — temel (Senkron/Yerel)
        self.security = SecurityManager(cfg=self.cfg)
        self.code = CodeManager(
            self.security,
            self.cfg.BASE_DIR,
            docker_image=getattr(self.cfg, "DOCKER_PYTHON_IMAGE", "python:3.11-alpine"),
            docker_exec_timeout=getattr(self.cfg, "DOCKER_EXEC_TIMEOUT", 10),
        )
        self.health = SystemHealthManager(self.cfg.USE_GPU, cfg=self.cfg)
        self.github = GitHubManager(self.cfg.GITHUB_TOKEN, self.cfg.GITHUB_REPO)
        
        self.memory = ConversationMemory(
            file_path=self.cfg.MEMORY_FILE,
            max_turns=self.cfg.MAX_MEMORY_TURNS,
            encryption_key=getattr(self.cfg, "MEMORY_ENCRYPTION_KEY", ""),
            keep_last=getattr(self.cfg, "MEMORY_SUMMARY_KEEP_LAST", 4),
        )
        
        self.llm = LLMClient(self.cfg.AI_PROVIDER, self.cfg)

        # Alt sistemler — yeni (Asenkron)
        self.web = WebSearchManager(self.cfg)
        self.pkg = PackageInfoManager(self.cfg)
        self.docs = DocumentStore(
            self.cfg.RAG_DIR,
            top_k=self.cfg.RAG_TOP_K,
            chunk_size=self.cfg.RAG_CHUNK_SIZE,
            chunk_overlap=self.cfg.RAG_CHUNK_OVERLAP,
            use_gpu=getattr(self.cfg, "USE_GPU", False),
            gpu_device=getattr(self.cfg, "GPU_DEVICE", 0),
            mixed_precision=getattr(self.cfg, "GPU_MIXED_PRECISION", False),
            cfg=self.cfg,
        )

        self.todo = TodoManager(self.cfg)
        self.tracer = trace.get_tracer(__name__) if trace and getattr(self.cfg, "ENABLE_TRACING", False) else None
        self._instructions_cache: Optional[str] = None
        self._instructions_mtimes: Dict[str, float] = {}
        self._instructions_lock = threading.Lock()


        # Tek omurga: supervisor tabanlı multi-agent
        self._supervisor = None
        self._initialized = False
        self._init_lock: Optional[asyncio.Lock] = None

        logger.info(
            "SidarAgent v%s başlatıldı — sağlayıcı=%s model=%s erişim=%s (VECTOR MEMORY + ASYNC)",
            self.VERSION,
            self.cfg.AI_PROVIDER,
            self.cfg.CODING_MODEL,
            self.cfg.ACCESS_LEVEL,
        )


    async def initialize(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            await self.memory.initialize()
            self._initialized = True

    # ─────────────────────────────────────────────
    #  ANA YANIT METODU (ASYNC STREAMING)
    # ─────────────────────────────────────────────

    async def respond(self, user_input: str) -> AsyncIterator[str]:
        """
        Kullanıcı girdisini asenkron işle ve yanıtı STREAM olarak döndür.
        """
        user_input = user_input.strip()
        if not user_input:
            yield "⚠ Boş girdi."
            return

        await self.initialize()

        # Tek akış: tüm görevler SupervisorAgent üzerinden yürütülür.
        multi_result = await self._try_multi_agent(user_input)

        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            await self._memory_add("user", user_input)
            await self._memory_add("assistant", multi_result)

        yield multi_result


    async def _try_multi_agent(self, user_input: str) -> str:
        """Görevi SupervisorAgent'a yönlendirir (tek omurga)."""
        if getattr(self, "_supervisor", None) is None:
            from agent.core.supervisor import SupervisorAgent
            self._supervisor = SupervisorAgent(self.cfg)

        result = await self._supervisor.run_task(user_input)
        if not isinstance(result, str) or not result.strip():
            return "⚠ Supervisor geçerli bir çıktı üretemedi."
        return result

    async def _get_memory_archive_context(self, user_input: str) -> str:
        """Sonsuz hafıza arşivinden sınırlı ve alakalı bağlamı çek."""
        top_k = max(1, int(getattr(self.cfg, "MEMORY_ARCHIVE_TOP_K", 3)))
        min_score = float(getattr(self.cfg, "MEMORY_ARCHIVE_MIN_SCORE", 0.35))
        max_chars = max(300, int(getattr(self.cfg, "MEMORY_ARCHIVE_MAX_CHARS", 1500)))
        return await asyncio.to_thread(
            self._get_memory_archive_context_sync,
            user_input,
            top_k,
            min_score,
            max_chars,
        )

    def _get_memory_archive_context_sync(
        self,
        user_input: str,
        top_k: int,
        min_score: float,
        max_chars: int,
    ) -> str:
        """ChromaDB'den memory_archive kaynaklı en alakalı özetleri getir."""
        if not getattr(self.docs, "collection", None):
            return ""

        try:
            # Alaka eşiği uygulayabilmek için distances dahil explicit query kullanılır.
            results = self.docs.collection.query(
                query_texts=[user_input],
                n_results=min(top_k * 3, 20),
                where={"source": "memory_archive"},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("Arşiv belleği sorgusu başarısız: %s", exc)
            return ""

        docs: List[str] = results.get("documents", [[]])[0] if results else []
        metas: List[Dict] = results.get("metadatas", [[]])[0] if results else []
        distances = results.get("distances", [[]])[0] if results else []

        selected: List[str] = []
        used_chars = 0
        for idx, doc_text in enumerate(docs):
            meta = metas[idx] if idx < len(metas) and metas[idx] else {}
            if meta.get("source") != "memory_archive":
                continue

            distance = distances[idx] if idx < len(distances) else None
            relevance = 1.0 - float(distance) if distance is not None else 1.0
            if relevance < min_score:
                continue

            snippet = (doc_text or "").replace("\n", " ").strip()
            if not snippet:
                continue
            if len(snippet) > 500:
                snippet = snippet[:500] + "..."

            title = str(meta.get("title", "Sohbet Arşivi"))
            block = f"- ({relevance:.2f}) {title}: {snippet}"

            if used_chars + len(block) > max_chars:
                break
            selected.append(block)
            used_chars += len(block)
            if len(selected) >= top_k:
                break

        if not selected:
            return ""

        return "\n\n[Geçmiş Sohbet Arşivinden İlgili Notlar]\n" + "\n".join(selected) + "\n"

    # ─────────────────────────────────────────────
    #  BAĞLAM OLUŞTURMA
    # ─────────────────────────────────────────────

    def _build_context(self) -> str:
        """
        Tüm alt sistem durumlarını özetleyen bağlam dizesi.
        Her LLM turunda system_prompt'a eklenir; model bu değerleri
        ASLA tahmin etmemelidir — gerçek runtime değerler burada verilir.

        Ayrıca SIDAR.md / CLAUDE.md dosyaları varsa proje özel talimatları
        hiyerarşik öncelik ile bağlama eklenir.
        """
        lines = []

        # ── Proje Ayarları (gerçek değerler — hallucination önleme) ──
        lines.append("[Proje Ayarları — GERÇEK RUNTIME DEĞERLERİ]")
        lines.append(f"  Proje        : {self.cfg.PROJECT_NAME} v{self.cfg.VERSION}")
        lines.append(f"  Dizin        : {self.cfg.BASE_DIR}")
        lines.append(f"  AI Sağlayıcı : {self.cfg.AI_PROVIDER.upper()}")
        if self.cfg.AI_PROVIDER == "ollama":
            lines.append(f"  Coding Modeli: {self.cfg.CODING_MODEL}")
            lines.append(f"  Text Modeli  : {self.cfg.TEXT_MODEL}")
            lines.append(f"  Ollama URL   : {self.cfg.OLLAMA_URL}")
        else:
            lines.append(f"  Gemini Modeli: {self.cfg.GEMINI_MODEL}")
        lines.append(f"  Erişim Seviye: {self.cfg.ACCESS_LEVEL.upper()}")
        gpu_str = f"{self.cfg.GPU_INFO} (CUDA {self.cfg.CUDA_VERSION})" if self.cfg.USE_GPU else f"Yok ({self.cfg.GPU_INFO})"
        lines.append(f"  GPU          : {gpu_str}")

        # ── Araç Durumu ───────────────────────────────────────────────
        lines.append("")
        lines.append("[Araç Durumu]")
        lines.append(f"  Güvenlik   : {self.security.level_name.upper()}")
        gh_status = f"Bağlı — {self.cfg.GITHUB_REPO}" if self.github.is_available() else "Bağlı değil"
        lines.append(f"  GitHub     : {gh_status}")
        lines.append(f"  WebSearch  : {'Aktif' if self.web.is_available() else 'Kurulu değil'}")
        lines.append(f"  RAG        : {self.docs.status()}")

        m = self.code.get_metrics()
        lines.append(f"  Okunan     : {m['files_read']} dosya | Yazılan: {m['files_written']}")

        last_file = self.memory.get_last_file()
        if last_file:
            lines.append(f"  Son dosya  : {last_file}")

        # ── Görev Listesi (aktif görev varsa ekle) ──────────────────────
        if len(self.todo) > 0:
            lines.append("")
            lines.append("[Aktif Görev Listesi]")
            lines.append(self.todo.list_tasks())

        # ── SIDAR.md / CLAUDE.md (Claude Code uyumlu) ──────────────────
        instruction_block = self._load_instruction_files()
        if instruction_block:
            lines.append("")
            lines.append(instruction_block)

        return "\n".join(lines)

    def _load_instruction_files(self) -> str:
        """
        Proje genelindeki SIDAR.md ve CLAUDE.md dosyalarını hiyerarşik şekilde yükle.
        - Daha üst dizin dosyaları önce gelir.
        - Alt dizin dosyaları daha sonra gelerek öncelik alır.
        - Dosya değişikliği (mtime) algılandığında otomatik olarak yeniden yükler.
          Bu davranış Claude Code'un CLAUDE.md'yi her konuşmada taze okumasına eşdeğerdir.
        """
        root = Path(self.cfg.BASE_DIR)
        instruction_names = ("SIDAR.md", "CLAUDE.md")
        found_files = []

        for name in instruction_names:
            found_files.extend(root.rglob(name))

        # Aynı dosya iki kez gelmesin, deterministik sırada olsun
        unique_files = sorted({p.resolve() for p in found_files if p.is_file()})

        # Mevcut mtime'ları topla
        current_mtimes: Dict[str, float] = {}
        for path in unique_files:
            try:
                current_mtimes[str(path)] = path.stat().st_mtime
            except Exception:
                pass

        with self._instructions_lock:
            # Cache geçerli mi? Hem içerik hem mtime eşleşmeli
            if self._instructions_cache is not None and current_mtimes == self._instructions_mtimes:
                return self._instructions_cache

            # Değişiklik var veya ilk yükleme → yeniden oku
            self._instructions_mtimes = current_mtimes

            if not unique_files:
                self._instructions_cache = ""
                return ""

            blocks = ["[Proje Talimat Dosyaları — SIDAR.md / CLAUDE.md]"]
            for path in unique_files:
                try:
                    rel = path.relative_to(root)
                    content = path.read_text(encoding="utf-8", errors="replace").strip()
                except Exception:
                    continue
                if not content:
                    continue
                blocks.append(f"\n## {rel}")
                blocks.append(content)

            self._instructions_cache = "\n".join(blocks) if len(blocks) > 1 else ""
            return self._instructions_cache

    # ─────────────────────────────────────────────
    #  BELLEK ÖZETLEME VE VEKTÖR ARŞİVLEME (ASYNC)
    # ─────────────────────────────────────────────

    async def _summarize_memory(self) -> None:
        """
        Konuşma geçmişini LLM ile özetler ve belleği sıkıştırır.
        AYRICA: Eski konuşmaları 'Sonsuz Hafıza' için Vektör DB'ye (ChromaDB) gömer.
        """
        history = await self.memory.get_history()
        if len(history) < 4:
            return

        # 1. VEKTÖR BELLEK (SONSUZ HAFIZA) KAYDI
        # Kısa özetlemeye geçmeden önce, tüm detayları RAG sistemine kaydediyoruz
        full_turns_text = "\n\n".join(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t.get('timestamp', time.time())))}] {t['role'].upper()}:\n{t['content']}"
            for t in history
        )
        
        try:
            await asyncio.to_thread(
                self.docs.add_document,
                title=f"Sohbet Geçmişi Arşivi ({time.strftime('%Y-%m-%d %H:%M')})",
                content=full_turns_text,
                source="memory_archive",
                tags=["memory", "archive", "conversation"],
            )
            logger.info("Eski konuşmalar RAG (Vektör) belleğine arşivlendi.")
        except Exception as exc:
            logger.warning("Vektör belleğe kayıt başarısız: %s", exc)

        # 2. KISA SÜRELİ BELLEK ÖZETLEMESİ
        # LLM token tasarrufu için sadece ilk 400 karakterlik kısımları gönderiyoruz
        turns_text_short = "\n".join(
            f"{t['role'].upper()}: {t['content'][:400]}"
            for t in history
        )
        summarize_prompt = (
            "Aşağıdaki konuşmayı kısa ve bilgilendirici şekilde özetle. "
            "Teknik detayları, dosya adlarını ve kod kararlarını koru:\n\n"
            + turns_text_short
        )
        try:
            summary = await self.llm.chat(
                messages=[{"role": "user", "content": summarize_prompt}],
                model=getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL),
                temperature=0.1,
                stream=False,
                json_mode=False,
            )
            await self.memory.apply_summary(str(summary))
            logger.info("Bellek özetlendi (%d → 2 mesaj).", len(history))
        except Exception as exc:
            logger.warning("Bellek özetleme başarısız: %s", exc)

    # ─────────────────────────────────────────────
    #  YARDIMCI METODLAR
    # ─────────────────────────────────────────────

    async def clear_memory(self) -> str:
        maybe = self.memory.clear()
        if inspect.isawaitable(maybe):
            await maybe
        return "Konuşma belleği temizlendi (dosya silindi). ✓"

    async def set_access_level(self, new_level: str) -> str:
        """
        Ajanın güvenlik seviyesini dinamik olarak değiştirir ve değişikliği
        sohbet belleğine kalıcı olarak yazar.
        """
        old_level = self.security.level_name
        changed = self.security.set_level(new_level)
        if changed:
            self.cfg.ACCESS_LEVEL = self.security.level_name
            msg = (
                "[GÜVENLİK BİLDİRİMİ] Sistem yöneticisi tarafından ajanın "
                f"erişim seviyesi '{old_level}' modundan "
                f"'{self.security.level_name}' moduna değiştirildi."
            )
            await self._memory_add("user", msg)
            await self._memory_add(
                "assistant",
                (
                    "Anlaşıldı, bundan sonraki işlemlerde "
                    f"'{self.security.level_name}' seviyesinin güvenlik "
                    "kurallarına ve yetkilerine göre hareket edeceğim."
                ),
            )
            return (
                f"✓ Erişim seviyesi '{self.security.level_name}' olarak güncellendi "
                "ve sohbet belleğine işlendi."
            )
        return f"ℹ Erişim seviyesi zaten '{self.security.level_name}'."

    async def _memory_add(self, role: str, content: str) -> None:
        maybe = self.memory.add(role, content)
        if inspect.isawaitable(maybe):
            await maybe

    def status(self) -> str:
        lines = [
            f"[SidarAgent v{self.VERSION}]",
            f"  Sağlayıcı    : {self.cfg.AI_PROVIDER}",
            f"  Model        : {self.cfg.CODING_MODEL}",
            f"  Erişim       : {self.cfg.ACCESS_LEVEL}",
            f"  Bellek       : {len(self.memory)} mesaj (Kalıcı)",
            f"  {self.github.status()}",
            f"  {self.web.status()}",
            f"  {self.pkg.status()}",
            f"  {self.docs.status()}",
            self.health.full_report(),
        ]
        return "\n".join(lines)  
