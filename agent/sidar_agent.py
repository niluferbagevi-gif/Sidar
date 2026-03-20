"""
Sidar Project - Ana Ajan
Supervisor tabanlı multi-agent omurgasıyla çalışan yazılım mühendisi AI asistanı (Asenkron).
"""

import logging
import asyncio
import json
import time
import threading
import sys
from importlib import import_module
from pathlib import Path
from typing import Optional, AsyncIterator, Dict, List, Any

from pydantic import BaseModel, Field, ValidationError

try:
    from opentelemetry import trace
except Exception:  # OpenTelemetry opsiyoneldir
    trace = None

from config import Config
from core.ci_remediation import build_ci_failure_context, build_ci_failure_prompt, build_ci_remediation_payload
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
agent_contracts = sys.modules.get("agent.core.contracts") or import_module("agent.core.contracts")
agent_definitions = sys.modules.get("agent.definitions") or import_module("agent.definitions")

SIDAR_SYSTEM_PROMPT = agent_definitions.SIDAR_SYSTEM_PROMPT
ExternalTrigger = agent_contracts.ExternalTrigger


def _default_derive_correlation_id(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


derive_correlation_id = getattr(agent_contracts, "derive_correlation_id", _default_derive_correlation_id)


class _FallbackFederationTaskEnvelope:
    def __init__(self, **kwargs):
        self.task_id = str(kwargs.get("task_id", ""))
        self.source_system = str(kwargs.get("source_system", ""))
        self.source_agent = str(kwargs.get("source_agent", ""))
        self.target_system = str(kwargs.get("target_system", ""))
        self.target_agent = str(kwargs.get("target_agent", ""))
        self.goal = str(kwargs.get("goal", ""))
        self.protocol = str(kwargs.get("protocol", "federation.v1"))
        self.intent = str(kwargs.get("intent", "mixed"))
        self.context = dict(kwargs.get("context", {}) or {})
        self.inputs = list(kwargs.get("inputs", []) or [])
        self.meta = dict(kwargs.get("meta", {}) or {})
        self.correlation_id = derive_correlation_id(
            kwargs.get("correlation_id", ""),
            self.meta.get("correlation_id", ""),
            self.task_id,
        )

    def to_prompt(self) -> str:
        return (
            f"[FEDERATION TASK]\n"
            f"source_system={self.source_system}\n"
            f"source_agent={self.source_agent}\n"
            f"target_system={self.target_system}\n"
            f"target_agent={self.target_agent}\n"
            f"protocol={self.protocol}\n"
            f"correlation_id={self.correlation_id}\n"
            f"intent={self.intent}\n"
            f"goal={self.goal}\n"
            f"context={json.dumps(self.context, ensure_ascii=False, sort_keys=True)}\n"
            f"inputs={json.dumps(self.inputs, ensure_ascii=False)}\n"
            f"meta={json.dumps(self.meta, ensure_ascii=False, sort_keys=True)}"
        )


class _FallbackActionFeedback:
    def __init__(self, **kwargs):
        self.feedback_id = str(kwargs.get("feedback_id", ""))
        self.source_system = str(kwargs.get("source_system", ""))
        self.source_agent = str(kwargs.get("source_agent", ""))
        self.action_name = str(kwargs.get("action_name", ""))
        self.status = str(kwargs.get("status", "received"))
        self.summary = str(kwargs.get("summary", ""))
        self.related_task_id = str(kwargs.get("related_task_id", ""))
        self.related_trigger_id = str(kwargs.get("related_trigger_id", ""))
        self.details = dict(kwargs.get("details", {}) or {})
        self.meta = dict(kwargs.get("meta", {}) or {})
        self.correlation_id = derive_correlation_id(
            kwargs.get("correlation_id", ""),
            self.meta.get("correlation_id", ""),
            self.related_task_id,
            self.related_trigger_id,
            self.feedback_id,
        )

    def to_prompt(self) -> str:
        return (
            f"[ACTION FEEDBACK]\n"
            f"source_system={self.source_system}\n"
            f"source_agent={self.source_agent}\n"
            f"action_name={self.action_name}\n"
            f"status={self.status}\n"
            f"correlation_id={self.correlation_id}\n"
            f"related_task_id={self.related_task_id}\n"
            f"related_trigger_id={self.related_trigger_id}\n"
            f"summary={self.summary}\n"
            f"details={json.dumps(self.details, ensure_ascii=False, sort_keys=True)}\n"
            f"meta={json.dumps(self.meta, ensure_ascii=False, sort_keys=True)}"
        )


FederationTaskEnvelope = getattr(agent_contracts, "FederationTaskEnvelope", _FallbackFederationTaskEnvelope)
ActionFeedback = getattr(agent_contracts, "ActionFeedback", _FallbackActionFeedback)

logger = logging.getLogger(__name__)


class ToolCall(BaseModel):
    """Ajanın LLM çıktısındaki tekil araç çağrısı şeması."""

    thought: str = Field(..., description="Modelin araç seçimi öncesi kısa düşüncesi")
    tool: str = Field(..., description="Çalıştırılacak araç adı")
    argument: str = Field(..., description="Araç için ham argüman metni")


class SidarAgent:
    """
    Sidar — Yazılım Mimarı ve Baş Mühendis AI Asistanı.
    Tamamen asenkron ağ istekleri, stream, yapısal veri ve sonsuz vektör hafıza uyumlu yapı.
    """

    VERSION = "3.0.0"  # Kurumsal/SaaS v3.0.0 final sürüm etiketi

    def __init__(self, cfg: Config = None) -> None:
        self.cfg = cfg or Config()
        # Bulgu D: asyncio.Lock() __init__ içinde (senkron bağlam) oluşturulmamalı.
        # Python <3.10'da event loop bağlanma hatalarına yol açar.
        # Lazy init: ilk async çağrıda oluşturulur (respond() içindeki guard).
        self._lock: Optional[asyncio.Lock] = None

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
            database_url=getattr(self.cfg, "DATABASE_URL", ""),
            base_dir=self.cfg.BASE_DIR,
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
        self.system_prompt: str = SIDAR_SYSTEM_PROMPT
        self._autonomy_history: List[Dict[str, Any]] = []
        self._autonomy_lock: Optional[asyncio.Lock] = None


        # Tek omurga: supervisor tabanlı multi-agent
        self._supervisor = None
        self._initialized = False
        # Bulgu D: asyncio.Lock() lazy init — async bağlamda oluşturulur.
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
            if hasattr(self.memory, "db") and hasattr(self.memory.db, "get_active_prompt"):
                active_prompt = await self.memory.db.get_active_prompt("system")
                if active_prompt and active_prompt.prompt_text.strip():
                    self.system_prompt = active_prompt.prompt_text
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

    def _ensure_autonomy_runtime_state(self) -> None:
        if not hasattr(self, "_autonomy_history") or self._autonomy_history is None:
            self._autonomy_history = []
        if not hasattr(self, "_autonomy_lock"):
            self._autonomy_lock = None

    async def _append_autonomy_history(self, record: Dict[str, Any]) -> None:
        self._ensure_autonomy_runtime_state()
        if self._autonomy_lock is None:
            self._autonomy_lock = asyncio.Lock()
        async with self._autonomy_lock:
            history = list(self._autonomy_history[-49:])
            history.append(dict(record))
            self._autonomy_history = history

    @staticmethod
    def _build_trigger_prompt(trigger: ExternalTrigger, payload_dict: Dict[str, Any], ci_context: Dict[str, Any] | None) -> str:
        if ci_context:
            return build_ci_failure_prompt(ci_context)

        if payload_dict.get("kind") == "federation_task":
            federation_payload = dict(payload_dict.get("federation_task") or payload_dict)
            if payload_dict.get("federation_prompt"):
                return str(payload_dict.get("federation_prompt"))
            return FederationTaskEnvelope(
                task_id=str(federation_payload.get("task_id") or trigger.trigger_id),
                source_system=str(federation_payload.get("source_system") or trigger.source),
                source_agent=str(federation_payload.get("source_agent") or "external"),
                target_system=str(federation_payload.get("target_system") or "sidar"),
                target_agent=str(federation_payload.get("target_agent") or "supervisor"),
                goal=str(federation_payload.get("goal") or ""),
                protocol=str(federation_payload.get("protocol") or "federation.v1"),
                intent=str(federation_payload.get("intent") or "mixed"),
                context=dict(federation_payload.get("context") or {}),
                inputs=list(federation_payload.get("inputs") or []),
                meta=dict(federation_payload.get("meta") or {}),
                correlation_id=str(federation_payload.get("correlation_id") or trigger.correlation_id),
            ).to_prompt()

        if payload_dict.get("kind") == "action_feedback" or trigger.event_name == "action_feedback":
            return ActionFeedback(
                feedback_id=str(payload_dict.get("feedback_id") or trigger.trigger_id),
                source_system=str(payload_dict.get("source_system") or trigger.source),
                source_agent=str(payload_dict.get("source_agent") or "external"),
                action_name=str(payload_dict.get("action_name") or trigger.event_name),
                status=str(payload_dict.get("status") or "received"),
                summary=str(payload_dict.get("summary") or "Dış sistem action feedback sinyali alındı."),
                related_task_id=str(payload_dict.get("related_task_id") or ""),
                related_trigger_id=str(payload_dict.get("related_trigger_id") or ""),
                details=dict(payload_dict.get("details") or {}),
                meta=dict(payload_dict.get("meta") or trigger.meta or {}),
                correlation_id=str(payload_dict.get("correlation_id") or trigger.correlation_id),
            ).to_prompt()

        return trigger.to_prompt()

    def _build_trigger_correlation(
        self,
        trigger: ExternalTrigger,
        payload_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._ensure_autonomy_runtime_state()
        correlation_id = derive_correlation_id(
            getattr(trigger, "correlation_id", ""),
            trigger.meta.get("correlation_id", ""),
            payload_dict.get("correlation_id", ""),
            payload_dict.get("related_task_id", ""),
            payload_dict.get("task_id", ""),
            trigger.trigger_id,
        )
        related_trigger_id = str(payload_dict.get("related_trigger_id") or "").strip()
        related_task_id = str(payload_dict.get("related_task_id") or payload_dict.get("task_id") or "").strip()

        matches: List[Dict[str, Any]] = []
        for item in reversed(list(getattr(self, "_autonomy_history", []) or [])):
            item_trigger_id = str(item.get("trigger_id", "") or "")
            item_payload = dict(item.get("payload") or {})
            item_corr = derive_correlation_id(
                item.get("correlation", {}).get("correlation_id", "") if isinstance(item.get("correlation"), dict) else "",
                item.get("meta", {}).get("correlation_id", "") if isinstance(item.get("meta"), dict) else "",
                item_payload.get("correlation_id", ""),
                item_payload.get("related_task_id", ""),
                item_payload.get("task_id", ""),
                item_trigger_id,
            )
            if correlation_id and item_corr == correlation_id:
                matches.append(item)
            elif related_trigger_id and item_trigger_id == related_trigger_id:
                matches.append(item)
            elif related_task_id and str(item_payload.get("task_id", "") or "") == related_task_id:
                matches.append(item)

        unique_matches: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in matches:
            item_id = str(item.get("trigger_id", "") or "")
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            unique_matches.append(item)

        related_trigger_ids = [str(item.get("trigger_id", "") or "") for item in unique_matches[:8]]
        related_sources = list(dict.fromkeys(str(item.get("source", "") or "") for item in unique_matches[:8] if str(item.get("source", "") or "")))
        return {
            "correlation_id": correlation_id,
            "related_trigger_id": related_trigger_id,
            "related_task_id": related_task_id,
            "matched_records": len(unique_matches),
            "related_trigger_ids": related_trigger_ids,
            "related_sources": related_sources,
            "latest_related_status": str(unique_matches[0].get("status", "") or "") if unique_matches else "",
        }

    async def handle_external_trigger(self, trigger: ExternalTrigger | Dict[str, Any]) -> Dict[str, Any]:
        """Webhook/cron/federation kaynaklı proaktif tetikleri işler ve geçmişe kaydeder."""
        await self.initialize()
        self._ensure_autonomy_runtime_state()

        if isinstance(trigger, dict):
            trigger = ExternalTrigger(
                trigger_id=str(trigger.get("trigger_id", f"trigger-{int(time.time())}")),
                source=str(trigger.get("source", "external")),
                event_name=str(trigger.get("event_name", "event")),
                payload=dict(trigger.get("payload", {}) or {}),
                meta=dict(trigger.get("meta", {}) or {}),
            )

        payload_dict = dict(trigger.payload or {})
        ci_context = (
            payload_dict
            if payload_dict.get("kind") in {"workflow_run", "check_run", "check_suite"} and payload_dict.get("workflow_name")
            else build_ci_failure_context(trigger.event_name, payload_dict)
        )
        correlation = self._build_trigger_correlation(trigger, payload_dict)
        prompt = self._build_trigger_prompt(trigger, payload_dict, ci_context)
        started_at = time.time()
        status = "success"
        summary = ""
        remediation: Dict[str, Any] | None = None
        try:
            summary = await self._try_multi_agent(prompt)
            if not isinstance(summary, str) or not summary.strip():
                status = "empty"
                summary = "⚠ Proaktif tetik işlendikten sonra boş çıktı üretildi."
            elif ci_context:
                remediation = build_ci_remediation_payload(ci_context, summary)
        except Exception as exc:
            status = "failed"
            summary = f"⚠ Proaktif tetik işlenemedi: {exc}"

        record = {
            "trigger_id": trigger.trigger_id,
            "source": trigger.source,
            "event_name": trigger.event_name,
            "status": status,
            "summary": summary,
            "payload": dict(trigger.payload or {}),
            "meta": dict(trigger.meta or {}),
            "correlation": correlation,
            "prompt": prompt,
            "created_at": started_at,
            "completed_at": time.time(),
        }
        if remediation:
            record["remediation"] = remediation

        await self._append_autonomy_history(record)
        await self._memory_add("user", f"[AUTONOMY_TRIGGER] {prompt}")
        await self._memory_add("assistant", summary)
        return record

    def get_autonomy_activity(self, limit: int = 20) -> Dict[str, Any]:
        """Son proaktif tetik kayıtlarını özet metriklerle birlikte döndürür."""
        self._ensure_autonomy_runtime_state()
        normalized_limit = max(1, int(limit or 20))
        items = [dict(item) for item in self._autonomy_history[-normalized_limit:]]
        counts_by_status: Dict[str, int] = {}
        counts_by_source: Dict[str, int] = {}
        for item in items:
            status = str(item.get("status", "unknown") or "unknown")
            source = str(item.get("source", "unknown") or "unknown")
            counts_by_status[status] = counts_by_status.get(status, 0) + 1
            counts_by_source[source] = counts_by_source.get(source, 0) + 1

        return {
            "items": items,
            "total": len(self._autonomy_history),
            "returned": len(items),
            "counts_by_status": counts_by_status,
            "counts_by_source": counts_by_source,
            "latest_trigger_id": items[-1]["trigger_id"] if items else "",
        }


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

    async def _build_context(self) -> str:
        """
        Tüm alt sistem durumlarını özetleyen bağlam dizesi.
        Her LLM turunda system_prompt'a eklenir; model bu değerleri
        ASLA tahmin etmemelidir — gerçek runtime değerler burada verilir.

        Ayrıca SIDAR.md / CLAUDE.md dosyaları varsa proje özel talimatları
        hiyerarşik öncelik ile bağlama eklenir.
        """
        lines = []
        is_local_provider = (self.cfg.AI_PROVIDER or "").lower() == "ollama"
        include_verbose_runtime = not is_local_provider

        # ── Proje Ayarları (gerçek değerler — hallucination önleme) ──
        # GÜVENLİK: BASE_DIR ve sistem config değerleri LLM context'ine açık metin
        # olarak verilmez; prompt injection saldırılarına karşı gizlenir.
        lines.append("[Proje Ayarları — GERÇEK RUNTIME DEĞERLERİ]")
        lines.append(f"  Proje        : {self.cfg.PROJECT_NAME} v{self.cfg.VERSION}")
        # BASE_DIR tam yolu yerine yalnızca klasör adı gösterilir
        if include_verbose_runtime:
            lines.append(f"  Dizin        : [proje dizini]")
        provider_name = (self.cfg.AI_PROVIDER or "").lower()
        lines.append(f"  AI Sağlayıcı : {self.cfg.AI_PROVIDER.upper()}")
        if provider_name == "ollama":
            lines.append(f"  Coding Modeli: {self.cfg.CODING_MODEL}")
            lines.append(f"  Text Modeli  : {self.cfg.TEXT_MODEL}")
        else:
            lines.append(f"  Gemini Modeli: {self.cfg.GEMINI_MODEL}")
        lines.append(f"  Erişim Seviye: {self.cfg.ACCESS_LEVEL.upper()}")
        gpu_str = f"{self.cfg.GPU_INFO} (CUDA {self.cfg.CUDA_VERSION})" if self.cfg.USE_GPU else f"Yok ({self.cfg.GPU_INFO})"
        if include_verbose_runtime:
            lines.append(f"  GPU          : {gpu_str}")

        # ── Araç Durumu ───────────────────────────────────────────────
        lines.append("")
        lines.append("[Araç Durumu]")
        lines.append(f"  Güvenlik   : {self.security.level_name.upper()}")
        # GITHUB_REPO tam URL yerine yalnızca owner/repo formatında gösterilir
        if self.github.is_available():
            _repo_raw = str(self.cfg.GITHUB_REPO or "")
            _repo_display = _repo_raw.split("/")[-2] + "/" + _repo_raw.split("/")[-1] if "/" in _repo_raw else _repo_raw
            gh_status = f"Bağlı — {_repo_display}"
        else:
            gh_status = "Bağlı değil"
        lines.append(f"  GitHub     : {gh_status}")
        lines.append(f"  WebSearch  : {'Aktif' if self.web.is_available() else 'Kurulu değil'}")
        lines.append(f"  RAG        : {self.docs.status()}")

        if include_verbose_runtime:
            m = self.code.get_metrics()
            lines.append(f"  Okunan     : {m['files_read']} dosya | Yazılan: {m['files_written']}")

            last_file = self.memory.get_last_file()
            if last_file:
                # Tam yol yerine yalnızca dosya adı (basename) gösterilir
                lines.append(f"  Son dosya  : {Path(last_file).name}")

        # ── Görev Listesi (aktif görev varsa ekle) ──────────────────────
        if len(self.todo) > 0:
            lines.append("")
            lines.append("[Aktif Görev Listesi]")
            lines.append(self.todo.list_tasks())

        # ── SIDAR.md / CLAUDE.md (Claude Code uyumlu) ──────────────────
        instruction_block = await asyncio.to_thread(self._load_instruction_files)
        if instruction_block:
            lines.append("")
            max_instruction_chars = max(600, int(getattr(self.cfg, "LOCAL_INSTRUCTION_MAX_CHARS", 2400)))
            if is_local_provider and len(instruction_block) > max_instruction_chars:
                instruction_block = instruction_block[:max_instruction_chars].rstrip() + "\n\n[Not] Talimatlar yerel model bağlam sınırı için kırpıldı."
            lines.append(instruction_block)

        context_text = "\n".join(lines)
        max_context_chars = max(1000, int(getattr(self.cfg, "LOCAL_AGENT_CONTEXT_MAX_CHARS", 4500)))
        if is_local_provider and len(context_text) > max_context_chars:
            return context_text[:max_context_chars].rstrip() + "\n\n[Not] Bağlam yerel model için kırpıldı."
        return context_text

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


    async def _tool_docs_search(self, arg: str) -> str:
        query = (arg or "").strip()
        if not query:
            return "⚠ Arama sorgusu belirtilmedi."
        mode = "auto"
        if "|" in query:
            parts = [p.strip() for p in query.split("|", 1)]
            query = parts[0]
            mode = parts[1] or "auto"
        session_id = "global"
        result_obj = await asyncio.to_thread(self.docs.search, query, None, mode, session_id)
        if asyncio.iscoroutine(result_obj):
            result_obj = await result_obj
        _ok, result = result_obj
        return result

    async def _tool_subtask(self, arg: str) -> str:
        task = (arg or "").strip()
        if not task:
            return "⚠ Alt görev belirtilmedi."

        max_steps = int(getattr(self.cfg, "SUBTASK_MAX_STEPS", 5))
        max_steps = max(1, max_steps)
        feedback = task

        for _ in range(max_steps):
            try:
                raw = await self.llm.chat(
                    messages=[{"role": "user", "content": feedback}],
                    model=getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL),
                    temperature=0.1,
                    stream=False,
                    json_mode=True,
                )
                if not isinstance(raw, str):
                    feedback = "Lütfen geçerli JSON araç çağrısı üret."
                    continue
                try:
                    action = ToolCall.model_validate_json(raw)
                except ValidationError:
                    import json as _json
                    action = _json.loads(raw)
                    action = ToolCall.model_validate(action)

                tool = action.tool.strip().lower()
                if tool == "final_answer":
                    return f"✓ Alt Görev Tamamlandı: {action.argument}"

                tool_result = await self._execute_tool(tool, action.argument)
                feedback = f"Araç sonucu: {tool_result}"
            except ValidationError:
                feedback = "Şema doğrulama hatası: thought/tool/argument alanları zorunlu."
            except Exception as exc:
                feedback = f"Araç çağrısı başarısız: {exc}"

        return "✗ Maksimum adım sınırına ulaşıldı. Alt görev tamamlanamadı."

    async def _tool_github_smart_pr(self, arg: str) -> str:
        if not self.github.is_available():
            return "⚠ GitHub token bulunamadı."

        parts = [p.strip() for p in (arg or "").split("|||")]
        title = parts[0] if len(parts) > 0 and parts[0] else "Otomatik PR"
        base = parts[1] if len(parts) > 1 and parts[1] else ""
        notes = parts[2] if len(parts) > 2 else ""

        ok, branch = self.code.run_shell("git branch --show-current")
        head = (branch or "").strip() if ok else ""
        if not head:
            return "✗ Aktif branch bulunamadı."

        if not base:
            try:
                base = self.github.default_branch
            except Exception:
                base = "main"

        ok_status, status_out = self.code.run_shell("git status --short")
        if not ok_status or not str(status_out).strip():
            return "ℹ Değişiklik bulunamadı; PR oluşturulmadı."

        self.code.run_shell("git diff --stat HEAD")
        ok_diff, diff_out = self.code.run_shell("git diff --no-color HEAD")
        diff_text = str(diff_out or "") if ok_diff else ""
        max_diff_chars = 10000
        if len(diff_text) > max_diff_chars:
            diff_text = diff_text[:max_diff_chars] + "\n\n[Not] Diff çok büyük olduğu için geri kalanı kırpıldı."

        _ok_log, commits = self.code.run_shell(f"git log --oneline {base}..HEAD")
        body = (
            f"{notes}\n\n"
            f"### Commitler\n{commits}\n\n"
            f"### Diff Özeti\n```diff\n{diff_text}\n```"
        )
        ok_pr, pr_out = self.github.create_pull_request(title, body, head, base)
        if not ok_pr:
            return f"✗ PR oluşturulamadı: {pr_out}"
        return f"✓ PR oluşturuldu: {pr_out}"


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
            await self.docs.add_document(
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
        await self.memory.clear()
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
            await self.memory.add("user", msg)
            await self.memory.add(
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
        await self.memory.add(role, content)

    def status(self) -> str:
        self._ensure_autonomy_runtime_state()
        autonomy_total = len(self._autonomy_history)
        lines = [
            f"[SidarAgent v{self.VERSION}]",
            f"  Sağlayıcı    : {self.cfg.AI_PROVIDER}",
            f"  Model        : {self.cfg.CODING_MODEL}",
            f"  Erişim       : {self.cfg.ACCESS_LEVEL}",
            f"  Bellek       : {len(self.memory)} mesaj (Kalıcı)",
            f"  Otonomi      : {autonomy_total} kayıt",
            f"  {self.github.status()}",
            f"  {self.web.status()}",
            f"  {self.pkg.status()}",
            f"  {self.docs.status()}",
            self.health.full_report(),
        ]
        return "\n".join(lines)