"""Sidar Project gateway agent.

Legacy tekli-ajan ReAct döngüsü kaldırıldı. Bu sınıf artık yalnızca
CLI/Web isteklerini SupervisorAgent'a yönlendirir.
"""

import asyncio
import logging
from typing import AsyncIterator, Optional

from pydantic import BaseModel, Field

from config import Config
from core.memory import ConversationMemory
from core.rag import DocumentStore
from managers.github_manager import GitHubManager
from managers.package_info import PackageInfoManager
from managers.security import SecurityManager
from managers.system_health import SystemHealthManager
from managers.web_search import WebSearchManager

logger = logging.getLogger(__name__)


class ToolCall(BaseModel):
    """Backward-compatible tool call schema (legacy imports)."""

    thought: str = Field(description="Ajanın mevcut adımdaki analizi ve planı.")
    tool: str = Field(description="Çalıştırılacak aracın tam adı.")
    argument: str = Field(default="", description="Araca geçirilecek parametre.")


class SidarAgent:
    """Gateway/API katmanı: istekleri SupervisorAgent'a delegasyon yapar."""

    VERSION = "3.0.0"

    def __init__(self, cfg: Config = None) -> None:
        self.cfg = cfg or Config()
        self._lock: Optional[asyncio.Lock] = None

        # Runtime bağımlılıkları status/operasyonel endpointler için korunur.
        self.security = SecurityManager(cfg=self.cfg)
        self.health = SystemHealthManager(self.cfg.USE_GPU, cfg=self.cfg)
        self.github = GitHubManager(self.cfg.GITHUB_TOKEN, self.cfg.GITHUB_REPO)
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
        self.memory = ConversationMemory(
            file_path=self.cfg.MEMORY_FILE,
            max_turns=self.cfg.MAX_MEMORY_TURNS,
            encryption_key=getattr(self.cfg, "MEMORY_ENCRYPTION_KEY", ""),
            keep_last=getattr(self.cfg, "MEMORY_SUMMARY_KEEP_LAST", 4),
        )

        self._supervisor = None
        logger.info(
            "SidarAgent v%s başlatıldı — supervisor-default mimari aktif.",
            self.VERSION,
        )

    async def respond(self, user_input: str) -> AsyncIterator[str]:
        """Kullanıcı girdisini SupervisorAgent üzerinden işle ve stream et."""
        user_input = user_input.strip()
        if not user_input:
            yield "⚠ Boş girdi."
            return

        multi_result = await self._try_multi_agent(user_input)

        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            await asyncio.to_thread(self.memory.add, "user", user_input)
            await asyncio.to_thread(self.memory.add, "assistant", multi_result)

        yield multi_result

    async def _try_multi_agent(self, user_input: str) -> str:
        if getattr(self, "_supervisor", None) is None:
            from agent.core.supervisor import SupervisorAgent

            self._supervisor = SupervisorAgent(self.cfg)

        result = await self._supervisor.run_task(user_input)
        if not isinstance(result, str) or not result.strip():
            return "⚠ Supervisor geçerli bir çıktı üretemedi."
        return result

    def clear_memory(self) -> str:
        self.memory.clear()
        return "Konuşma belleği temizlendi (dosya silindi). ✓"

    def set_access_level(self, new_level: str) -> str:
        old_level = self.security.level_name
        changed = self.security.set_level(new_level)
        if changed:
            self.cfg.ACCESS_LEVEL = self.security.level_name
            msg = (
                "[GÜVENLİK BİLDİRİMİ] Sistem yöneticisi tarafından ajanın "
                f"erişim seviyesi '{old_level}' modundan "
                f"'{self.security.level_name}' moduna değiştirildi."
            )
            self.memory.add("user", msg)
            self.memory.add(
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
