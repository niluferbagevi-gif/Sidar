"""Sidar Project - Ana Ajan.

Supervisor tabanlı multi-agent omurgasıyla çalışan yazılım mühendisi AI asistanı (Asenkron).
"""

import asyncio
import contextlib
import inspect
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

try:
    from opentelemetry import trace
except Exception:  # OpenTelemetry opsiyoneldir
    trace = None  # type: ignore[assignment]

from agent.autonomy.service import (
    append_autonomy_history as append_autonomy_history_service,
)
from agent.autonomy.service import (
    ensure_autonomy_runtime_state as ensure_autonomy_runtime_state_service,
)
from agent.autonomy.service import (
    get_autonomy_activity as get_autonomy_activity_service,
)
from agent.bootstrap import log_sidar_agent_startup
from agent.core.contracts_fallback import (
    default_derive_correlation_id as _default_derive_correlation_id,
)
from agent.definitions import SIDAR_SYSTEM_PROMPT
from agent.federation import service as federation_service
from agent.github import smart_pr as github_smart_pr
from agent.maintenance.nightly import (
    run_nightly_memory_maintenance as run_nightly_memory_maintenance_service,
)
from agent.self_heal.executor import (
    execute_mechanical_autofix as execute_mechanical_autofix_service,
)
from agent.self_heal.executor import (
    execute_self_heal_plan as execute_self_heal_plan_service,
)
from agent.self_heal.executor import (
    restore_self_heal_backups as restore_self_heal_backups_service,
)
from agent.self_heal.orchestrator import (
    attempt_autonomous_self_heal as attempt_autonomous_self_heal_service,
)
from agent.self_heal.planner import build_plan as build_self_heal_plan_service
from agent.self_heal.planner import collect_snapshots as collect_self_heal_snapshots_service
from agent.self_heal.planner import resolve_scope_batches as resolve_self_heal_scope_batches_service
from agent.services.response_service import parse_tool_call as parse_tool_call_service
from agent.services.tool_service import execute_tool as execute_tool_service
from agent.triggers import build_trigger_correlation as build_trigger_correlation_service
from agent.triggers import handle_external_trigger as handle_external_trigger_service
from config import Config
from core.ci_remediation import (
    build_ci_failure_context,
    build_ci_failure_prompt,
    build_ci_remediation_payload,
    build_self_heal_patch_prompt,
    normalize_self_heal_plan,
)
from core.distributed_lock import DistributedLockLease, RedisDistributedLock
from core.entity_memory import get_entity_memory
from core.llm_client import LLMClient
from core.memory import ConversationMemory
from core.rag import DocumentStore, get_shared_document_store
from managers.code_manager import CodeManager
from managers.github_manager import GitHubManager
from managers.package_info import PackageInfoManager
from managers.security import SecurityManager
from managers.system_health import SystemHealthManager
from managers.todo_manager import TodoManager
from managers.web_search import WebSearchManager

if TYPE_CHECKING:
    from agent.core.contracts import ExternalTrigger as ExternalTriggerType
else:
    ExternalTriggerType = Any


def get_agent_metrics_collector() -> Any:
    from core.agent_metrics import get_agent_metrics_collector as _get_agent_metrics_collector

    return _get_agent_metrics_collector()


logger = logging.getLogger(__name__)

ActionFeedback = federation_service.ActionFeedback
FederationTaskEnvelope = federation_service.FederationTaskEnvelope
derive_correlation_id = federation_service.derive_correlation_id
_FallbackActionFeedback = federation_service.FallbackActionFeedback
_FallbackFederationTaskEnvelope = federation_service.FallbackFederationTaskEnvelope
build_trigger_prompt_service = federation_service.build_trigger_prompt
trigger_attr_service = federation_service.trigger_attr
trigger_meta_service = federation_service.trigger_meta
trigger_payload_service = federation_service.trigger_payload
trigger_to_prompt_service = federation_service.trigger_to_prompt

__all__ = [
    "ActionFeedback",
    "FederationTaskEnvelope",
    "SidarAgent",
    "ToolCall",
    "_FallbackActionFeedback",
    "_default_derive_correlation_id",
    "_FallbackFederationTaskEnvelope",
]

ARCHIVE_CONTEXT_HEADER = "[Geçmiş Sohbet Arşivinden İlgili Notlar]"
CONTEXT_GEMINI_MODEL_LABEL = "Gemini Modeli"
CONTEXT_GITHUB_CONNECTED_PREFIX = "Bağlı — "
CONTEXT_TASK_LIST_HEADER = "[Aktif Görev Listesi]"
SUBTASK_MAX_STEPS_MESSAGE = "✗ Maksimum adım sınırına ulaşıldı. Alt görev tamamlanamadı."
GITHUB_SMART_PR_NO_TOKEN_MESSAGE = github_smart_pr.GITHUB_SMART_PR_NO_TOKEN_MESSAGE
GITHUB_SMART_PR_NO_BRANCH_MESSAGE = github_smart_pr.GITHUB_SMART_PR_NO_BRANCH_MESSAGE
GITHUB_SMART_PR_NO_CHANGES_MESSAGE = github_smart_pr.GITHUB_SMART_PR_NO_CHANGES_MESSAGE
GITHUB_SMART_PR_CREATE_FAILED_PREFIX = github_smart_pr.GITHUB_SMART_PR_CREATE_FAILED_PREFIX
GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX = github_smart_pr.GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX


class ToolCall(BaseModel):
    """Ajanın LLM çıktısındaki tekil araç çağrısı şeması."""

    thought: str = Field(..., description="Modelin araç seçimi öncesi kısa düşüncesi")
    tool: str = Field(..., description="Çalıştırılacak araç adı")
    argument: str = Field(..., description="Araç için ham argüman metni")


@dataclass
class AgentDependencies:
    """SidarAgent alt sistem bağımlılıkları (DI)."""

    security: SecurityManager
    code: CodeManager
    health: SystemHealthManager
    github: GitHubManager
    memory: ConversationMemory
    llm: LLMClient
    web: WebSearchManager
    pkg: PackageInfoManager
    docs: DocumentStore
    todo: TodoManager

    @classmethod
    def from_config(cls, cfg: Config, *, has_explicit_database_url: bool) -> "AgentDependencies":
        security = SecurityManager(cfg=cfg)
        code = CodeManager(
            security,
            Path(cfg.BASE_DIR),
            docker_image=getattr(cfg, "DOCKER_PYTHON_IMAGE", "python:3.11-alpine"),
            docker_exec_timeout=getattr(cfg, "DOCKER_EXEC_TIMEOUT", 10),
        )
        health = SystemHealthManager(cfg.USE_GPU, cfg=cfg)
        github = GitHubManager(cfg.GITHUB_TOKEN, cfg.GITHUB_REPO)
        memory = ConversationMemory(
            database_url=getattr(cfg, "DATABASE_URL", "") if has_explicit_database_url else None,
            base_dir=cfg.BASE_DIR,
            file_path=cfg.MEMORY_FILE,
            max_turns=cfg.MAX_MEMORY_TURNS,
            encryption_key=getattr(cfg, "MEMORY_ENCRYPTION_KEY", ""),
            previous_encryption_keys=getattr(cfg, "MEMORY_ENCRYPTION_KEY_PREVIOUS", ""),
            keep_last=getattr(cfg, "MEMORY_SUMMARY_KEEP_LAST", 4),
        )
        llm = LLMClient(cfg.AI_PROVIDER, cfg)
        web = WebSearchManager(cfg)
        pkg = PackageInfoManager(cfg)
        docs = get_shared_document_store(
            store_dir=cfg.RAG_DIR,
            cfg=cfg,
            initialize_vector=not bool(getattr(cfg, "CLI_FAST_MODE", False)),
        )
        todo = TodoManager(cfg)
        return cls(
            security=security,
            code=code,
            health=health,
            github=github,
            memory=memory,
            llm=llm,
            web=web,
            pkg=pkg,
            docs=docs,
            todo=todo,
        )


class SidarAgent:
    """Sidar — Yazılım Mimarı ve Baş Mühendis AI Asistanı.

    Tamamen asenkron ağ istekleri, stream, yapısal veri ve sonsuz vektör hafıza uyumlu yapı.
    """

    VERSION = Config.VERSION  # Merkezi ürün sürümü: sidar_version.PRODUCT_VERSION → Config.VERSION

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        config: Config | None = None,
        deps: AgentDependencies | None = None,
        **kwargs: Any,
    ) -> None:
        """SidarAgent oluşturur.

        Geriye dönük uyumluluk için hem ``cfg`` hem ``config`` parametreleri desteklenir.
        ``config`` verildiğinde önceliklidir; beklenmeyen anahtar argümanlar reddedilir.
        """
        if kwargs:
            unexpected = ", ".join(sorted(kwargs.keys()))
            raise TypeError(f"Unexpected keyword argument(s): {unexpected}")

        selected_cfg = config if config is not None else cfg
        self.cfg = selected_cfg or Config()
        raw_database_url = (
            getattr(selected_cfg, "DATABASE_URL", "")
            if selected_cfg is not None
            else getattr(self.cfg, "DATABASE_URL", "")
        )
        has_explicit_database_url = isinstance(raw_database_url, str) and bool(
            raw_database_url.strip()
        )
        self._normalize_config_defaults()
        # Bulgu D: asyncio.Lock() __init__ içinde (senkron bağlam) oluşturulmamalı.
        # Python <3.10'da event loop bağlanma hatalarına yol açar.
        # Lazy init: ilk async çağrıda oluşturulur (respond() içindeki guard).
        self._lock: asyncio.Lock | None = None

        self._deps = deps or AgentDependencies.from_config(
            self.cfg, has_explicit_database_url=has_explicit_database_url
        )

        # Alt sistemler — DI üzerinden atanır (test izolasyonu için).
        self.security = self._deps.security
        self.code = self._deps.code
        self.health = self._deps.health
        self.github = self._deps.github
        self.memory = self._deps.memory
        self.llm = self._deps.llm
        self.web = self._deps.web
        self.pkg = self._deps.pkg
        self.docs = self._deps.docs
        self.todo = self._deps.todo
        self.tracer = (
            trace.get_tracer(__name__)
            if trace and getattr(self.cfg, "ENABLE_TRACING", False)
            else None
        )
        self._instructions_cache: str | None = None
        self._instructions_mtimes: dict[str, float] = {}
        self._instructions_lock = threading.Lock()
        self.system_prompt: str = SIDAR_SYSTEM_PROMPT
        self._autonomy_history: list[dict[str, Any]] = []
        self._autonomy_lock: asyncio.Lock | None = None
        self._self_heal_attempts: dict[str, int] = {}
        self._self_heal_attempts_lock: asyncio.Lock | None = None
        self._last_activity_ts: float = time.time()
        self._nightly_maintenance_lock: asyncio.Lock | None = None
        self._nightly_distributed_lock: RedisDistributedLock | None = None
        self._last_nightly_maintenance_ts: float = 0.0

        # Tek omurga: supervisor tabanlı multi-agent
        self._supervisor = None
        self._initialized = False
        # Bulgu D: asyncio.Lock() lazy init — async bağlamda oluşturulur.
        self._init_lock: asyncio.Lock | None = None

        log_sidar_agent_startup(self.VERSION, self.cfg)

    def _normalize_config_defaults(self) -> None:
        """Eksik/uygunsuz config alanlarını varsayılan Config değerleriyle tamamlar."""
        defaults = Config()
        sentinel = object()

        def _is_mock_like(value: Any) -> bool:
            return bool(value.__class__.__module__.startswith("unittest.mock"))

        default_keys = [key for key in dir(defaults) if key.isupper()]
        for key in default_keys:
            default_value = getattr(defaults, key, sentinel)
            if default_value is sentinel:
                continue
            if not key.isupper():
                continue
            current = getattr(self.cfg, key, sentinel)
            if current is sentinel or current is None or _is_mock_like(current):
                setattr(self.cfg, key, default_value)
                continue
            expected = type(default_value)
            if expected in (str, int, float, bool):
                if not isinstance(current, expected):
                    setattr(self.cfg, key, default_value)

    def _parse_tool_call(self, raw: str) -> dict[str, Any] | None:
        """Ham LLM çıktısını araç çağrısı sözlüğüne dönüştürür.

        Markdown JSON bloklarını (```json ... ```) soyar, JSON parse eder.
        Geçersiz JSON durumunda ``final_answer`` aracına yönlendirir.
        ``tool`` anahtarı eksikse varsayılan olarak ``final_answer`` atanır.
        """
        return parse_tool_call_service(raw)

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            ensure_initialized = getattr(self.memory, "_ensure_initialized", None)
            if callable(ensure_initialized):
                await ensure_initialized()
            else:
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
        """Kullanıcı girdisini asenkron işle ve yanıtı STREAM olarak döndür."""
        user_input = user_input.strip()
        if not user_input:
            yield "⚠ Boş girdi."
            return

        await self.initialize()
        self.mark_activity("respond")

        # Tek akış: tüm görevler SupervisorAgent üzerinden yürütülür.
        multi_result = await self._try_multi_agent(user_input)
        if asyncio.iscoroutine(multi_result):
            multi_result = await multi_result

        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            try:
                await self._memory_add("user", user_input)
                await self._memory_add("assistant", multi_result)
            except Exception as exc:
                logger.warning("Memory add failed during respond flow: %s", exc)

        yield multi_result

    def mark_activity(self, source: str = "runtime") -> None:
        self._last_activity_ts = time.time()
        logger.debug("Sidar activity updated: %s", source)

    def seconds_since_last_activity(self) -> float:
        return max(0.0, time.time() - float(getattr(self, "_last_activity_ts", 0.0) or 0.0))

    def _get_nightly_distributed_lock(self) -> RedisDistributedLock | None:
        """Return Redis-backed distributed lock manager when enabled for shared jobs."""
        if not bool(getattr(self.cfg, "ENABLE_DISTRIBUTED_AGENT_LOCKS", True)):
            return None
        redis_url = str(getattr(self.cfg, "REDIS_URL", "") or "").strip()
        if not redis_url:
            return None
        if self._nightly_distributed_lock is None:
            timeout_ms = max(
                50,
                int(getattr(self.cfg, "DISTRIBUTED_AGENT_LOCK_TIMEOUT_MS", 250) or 250),
            )
            self._nightly_distributed_lock = RedisDistributedLock.from_url(
                redis_url,
                max_connections=int(getattr(self.cfg, "REDIS_MAX_CONNECTIONS", 10) or 10),
                timeout_seconds=timeout_ms / 1000,
            )
        return self._nightly_distributed_lock

    async def _acquire_nightly_distributed_lease(
        self,
    ) -> tuple[DistributedLockLease | None, dict[str, Any] | None]:
        """Acquire cross-pod lease for nightly maintenance or return a skip reason."""
        lock = self._get_nightly_distributed_lock()
        if lock is None:
            if bool(getattr(self.cfg, "DISTRIBUTED_AGENT_LOCK_REQUIRED", False)):
                return None, {"status": "skipped", "reason": "distributed_lock_unconfigured"}
            return None, None
        ttl_seconds = max(
            60,
            int(getattr(self.cfg, "DISTRIBUTED_AGENT_LOCK_TTL_SECONDS", 1800) or 1800),
        )
        try:
            lease = await lock.acquire(
                "sidar:locks:nightly-memory-maintenance", ttl_seconds=ttl_seconds
            )
        except Exception as exc:
            logger.warning("Nightly distributed lock acquire failed: %s", exc)
            if bool(getattr(self.cfg, "DISTRIBUTED_AGENT_LOCK_REQUIRED", False)):
                return None, {
                    "status": "skipped",
                    "reason": "distributed_lock_unavailable",
                    "error": str(exc),
                }
            return None, None
        if lease is None:
            return None, {"status": "skipped", "reason": "already_running_distributed"}
        return lease, None

    async def _release_nightly_distributed_lease(self, lease: DistributedLockLease | None) -> None:
        if lease is None or self._nightly_distributed_lock is None:
            return
        try:
            await self._nightly_distributed_lock.release(lease)
        except Exception as exc:
            logger.warning("Nightly distributed lock release failed: %s", exc)

    def _ensure_autonomy_runtime_state(self) -> None:
        ensure_autonomy_runtime_state_service(self)

    async def _append_autonomy_history(self, record: dict[str, Any]) -> None:
        await append_autonomy_history_service(self, record)

    @staticmethod
    def _update_remediation_step(
        remediation_loop: dict[str, Any], step_name: str, *, status: str, detail: str
    ) -> None:
        steps = list(remediation_loop.get("steps") or [])
        for step in steps:
            if str(step.get("name", "")).strip() != step_name:
                continue
            step["status"] = status
            step["detail"] = detail
            break

    async def _collect_self_heal_snapshots(self, scope_paths: list[str]) -> list[dict[str, str]]:
        return await collect_self_heal_snapshots_service(self.code, scope_paths)

    def _resolve_self_heal_scope_batches(
        self, scope_paths: list[str], remediation_loop: dict[str, Any]
    ) -> list[list[str]]:
        batch_size = max(1, int(getattr(self.cfg, "SELF_HEAL_AUTONOMOUS_BATCH_SIZE", 5) or 5))
        return resolve_self_heal_scope_batches_service(
            scope_paths, remediation_loop, batch_size=batch_size
        )

    async def _build_self_heal_plan(
        self,
        *,
        ci_context: dict[str, Any],
        diagnosis: str,
        remediation_loop: dict[str, Any],
    ) -> dict[str, Any]:
        return await build_self_heal_plan_service(
            code=self.code,
            llm=self.llm,
            cfg=self.cfg,
            ci_context=ci_context,
            diagnosis=diagnosis,
            remediation_loop=remediation_loop,
            prompt_builder=build_self_heal_patch_prompt,
            plan_normalizer=normalize_self_heal_plan,
            logger=logger,
            range_factory=globals().get("range", range),
        )

    async def _restore_self_heal_backups(self, backups: dict[str, str]) -> None:
        await restore_self_heal_backups_service(self.code, backups)

    async def _execute_self_heal_plan(
        self,
        *,
        remediation_loop: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        return await execute_self_heal_plan_service(
            code=self.code,
            base_dir=str(self.cfg.BASE_DIR),
            remediation_loop=remediation_loop,
            plan=plan,
        )

    async def _attempt_mechanical_autofix(
        self, *, remediation_loop: dict[str, Any]
    ) -> dict[str, Any]:
        return await execute_mechanical_autofix_service(
            code=self.code,
            base_dir=str(self.cfg.BASE_DIR),
            remediation_loop=remediation_loop,
        )

    async def _attempt_autonomous_self_heal(
        self,
        *,
        ci_context: dict[str, Any],
        diagnosis: str,
        remediation: dict[str, Any],
        human_approval: bool | None = None,
    ) -> dict[str, Any]:
        """Delegate bounded self-heal orchestration to its domain service."""
        return await attempt_autonomous_self_heal_service(
            self,
            ci_context=ci_context,
            diagnosis=diagnosis,
            remediation=remediation,
            human_approval=human_approval,
        )

    @staticmethod
    def _trigger_attr(
        trigger: ExternalTriggerType | dict[str, Any], name: str, default: Any = ""
    ) -> Any:
        return trigger_attr_service(trigger, name, default)

    @staticmethod
    def _trigger_payload(trigger: ExternalTriggerType | dict[str, Any]) -> dict[str, Any]:
        return trigger_payload_service(trigger)

    @staticmethod
    def _trigger_meta(trigger: ExternalTriggerType | dict[str, Any]) -> dict[str, Any]:
        return trigger_meta_service(trigger)

    @staticmethod
    def _trigger_to_prompt(trigger: ExternalTriggerType | dict[str, Any]) -> str:
        return trigger_to_prompt_service(trigger)

    @staticmethod
    def _build_trigger_prompt(
        trigger: ExternalTriggerType | dict[str, Any],
        payload_dict: dict[str, Any],
        ci_context: dict[str, Any] | None,
    ) -> str:
        if ci_context:
            return build_ci_failure_prompt(ci_context)
        return build_trigger_prompt_service(trigger, payload_dict, None)

    def _build_trigger_correlation(
        self,
        trigger: ExternalTriggerType | dict[str, Any],
        payload_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """Delegate external-trigger correlation to its domain service."""
        return build_trigger_correlation_service(self, trigger, payload_dict)

    async def handle_external_trigger(
        self, trigger: ExternalTriggerType | dict[str, Any]
    ) -> dict[str, Any]:
        """Delegate external-trigger processing to its domain service."""
        return await handle_external_trigger_service(
            self,
            trigger,
            ci_context_builder=build_ci_failure_context,
            remediation_builder=build_ci_remediation_payload,
        )

    async def run_nightly_memory_maintenance(
        self,
        *,
        force: bool = False,
        reason: str = "nightly_idle",
    ) -> dict[str, Any]:
        """Uzun süreli kullanım için sohbet/RAG belleğini sıkıştırır ve temizler."""
        return await run_nightly_memory_maintenance_service(
            self,
            force=force,
            reason=reason,
            entity_memory_factory=get_entity_memory,
        )

    def get_autonomy_activity(self, limit: int = 20) -> dict[str, Any]:
        """Son proaktif tetik kayıtlarını özet metriklerle birlikte döndürür."""
        return get_autonomy_activity_service(self, limit)

    async def _try_multi_agent(self, user_input: str) -> str:
        """Görevi SupervisorAgent'a yönlendirir (tek omurga)."""
        if getattr(self, "_supervisor", None) is None:
            supervisor_mod = import_module("agent.core.supervisor")
            SupervisorAgent = supervisor_mod.SupervisorAgent
            self._supervisor = SupervisorAgent(self.cfg)
            if self._supervisor is not None:
                self._supervisor.llm = self.llm

            # Supervisor altında açılan role-agent'ların, üst ajanın paylaşılan
            # kaynak yöneticilerini (özellikle web arama yöneticisini) kullanmasını sağla.
            # Böylece testlerde class-level monkeypatch edilen async mock'lar,
            # beklenen örnek üzerinden doğrulanabilir ve çalışma zamanı davranışı
            # tekil manager örneği etrafında deterministik kalır.
            researcher = getattr(self._supervisor, "researcher", None)
            if researcher is not None:
                if hasattr(researcher, "web"):
                    researcher.web = self.web
                if hasattr(researcher, "docs"):
                    researcher.docs = self.docs

            for role_name in ("researcher", "coder", "reviewer", "poyraz", "qa", "coverage"):
                role_agent = getattr(self._supervisor, role_name, None)
                if role_agent is not None and hasattr(role_agent, "llm"):
                    role_agent.llm = self.llm

        if self._supervisor is None:
            return "⚠ Supervisor başlatılamadı."
        result = self._supervisor.run_task(user_input)
        if inspect.isawaitable(result):
            result = await result
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
            collection = self.docs.collection
            if collection is None:
                return ""
            results = collection.query(
                query_texts=[user_input],
                n_results=min(top_k * 3, 20),
                where={"source": "memory_archive"},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("Arşiv belleği sorgusu başarısız: %s", exc)
            return ""

        docs: list[str] = results.get("documents", [[]])[0] if results else []
        metas: list[dict[str, Any]] = results.get("metadatas", [[]])[0] if results else []
        distances = results.get("distances", [[]])[0] if results else []

        selected: list[str] = []
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

        return f"\n\n{ARCHIVE_CONTEXT_HEADER}\n" + "\n".join(selected) + "\n"

    # ─────────────────────────────────────────────
    #  BAĞLAM OLUŞTURMA
    # ─────────────────────────────────────────────

    async def _build_context(self) -> str:
        """Tüm alt sistem durumlarını özetleyen bağlam dizesi.

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
            lines.append("  Dizin        : [proje dizini]")
        provider_name = (self.cfg.AI_PROVIDER or "").lower()
        lines.append(f"  AI Sağlayıcı : {self.cfg.AI_PROVIDER.upper()}")
        if provider_name == "ollama":
            lines.append(f"  Coding Modeli: {self.cfg.CODING_MODEL}")
            lines.append(f"  Text Modeli  : {self.cfg.TEXT_MODEL}")
        else:
            lines.append(f"  {CONTEXT_GEMINI_MODEL_LABEL}: {self.cfg.GEMINI_MODEL}")
        lines.append(f"  Erişim Seviye: {self.cfg.ACCESS_LEVEL.upper()}")
        gpu_str = (
            f"{self.cfg.GPU_INFO} (CUDA {self.cfg.CUDA_VERSION})"
            if self.cfg.USE_GPU
            else f"Yok ({self.cfg.GPU_INFO})"
        )
        if include_verbose_runtime:
            lines.append(f"  GPU          : {gpu_str}")

        # ── Araç Durumu ───────────────────────────────────────────────
        lines.append("")
        lines.append("[Araç Durumu]")
        lines.append(f"  Güvenlik   : {self.security.level_name.upper()}")
        # GITHUB_REPO tam URL yerine yalnızca owner/repo formatında gösterilir
        if self.github.is_available():
            _repo_raw = str(self.cfg.GITHUB_REPO or "")
            _repo_display = (
                _repo_raw.split("/")[-2] + "/" + _repo_raw.split("/")[-1]
                if "/" in _repo_raw
                else _repo_raw
            )
            gh_status = f"{CONTEXT_GITHUB_CONNECTED_PREFIX}{_repo_display}"
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
        todo_count = 0
        try:
            todo_count = int(len(self.todo))
        except TypeError:
            dynamic_len = getattr(self.todo, "__len__", None)
            if callable(dynamic_len):
                try:
                    todo_count = int(dynamic_len())
                except Exception:
                    todo_count = 0
        except Exception:
            todo_count = 0

        if todo_count > 0:
            lines.append("")
            lines.append(CONTEXT_TASK_LIST_HEADER)
            lines.append(self.todo.list_tasks())

        # ── SIDAR.md / CLAUDE.md (Claude Code uyumlu) ──────────────────
        instruction_block = await asyncio.to_thread(self._load_instruction_files)
        if instruction_block:
            lines.append("")
            max_instruction_chars = max(
                600, int(getattr(self.cfg, "LOCAL_INSTRUCTION_MAX_CHARS", 2400))
            )
            if is_local_provider and len(instruction_block) > max_instruction_chars:
                instruction_block = (
                    instruction_block[:max_instruction_chars].rstrip()
                    + "\n\n[Not] Talimatlar yerel model bağlam sınırı için kırpıldı."
                )
            lines.append(instruction_block)

        context_text = "\n".join(lines)
        max_context_chars = max(1000, int(getattr(self.cfg, "LOCAL_AGENT_CONTEXT_MAX_CHARS", 4500)))
        if is_local_provider and len(context_text) > max_context_chars:
            return (
                context_text[:max_context_chars].rstrip()
                + "\n\n[Not] Bağlam yerel model için kırpıldı."
            )
        return context_text

    def _load_instruction_files(self) -> str:
        """Proje genelindeki SIDAR.md ve CLAUDE.md dosyalarını hiyerarşik şekilde yükle.

        - Daha üst dizin dosyaları önce gelir.
        - Alt dizin dosyaları daha sonra gelerek öncelik alır.
        - Dosya değişikliği (mtime) algılandığında otomatik olarak yeniden yükler.
          Bu davranış Claude Code'un CLAUDE.md'yi her konuşmada taze okumasına eşdeğerdir.
        """
        root = Path(self.cfg.BASE_DIR)
        instruction_names = ("SIDAR.md", "CLAUDE.md")
        found_files: list[Path] = []

        for name in instruction_names:
            found_files.extend(root.rglob(name))

        # Aynı dosya iki kez gelmesin, deterministik sırada olsun
        normalized_files = []
        for candidate in found_files:
            try:
                path_obj = candidate if isinstance(candidate, Path) else Path(candidate)
                if not hasattr(path_obj, "is_file") or not path_obj.is_file():
                    continue
                resolved = path_obj.resolve() if hasattr(path_obj, "resolve") else path_obj
                normalized_files.append(resolved)
            except Exception as exc:
                logger.debug("Instruction file normalization skipped for %s: %s", candidate, exc)
                continue

        unique_files = sorted(set(normalized_files), key=lambda p: str(p))

        # Mevcut mtime'ları topla
        current_mtimes: dict[str, float] = {}
        for path in unique_files:
            try:
                current_mtimes[str(path)] = path.stat().st_mtime
            except Exception as exc:
                logger.debug("Instruction file mtime read skipped for %s: %s", path, exc)

        lock_cm: Any = (
            self._instructions_lock
            if hasattr(self._instructions_lock, "__enter__")
            and hasattr(self._instructions_lock, "__exit__")
            else contextlib.nullcontext()
        )
        with lock_cm:
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
                except Exception as exc:
                    logger.debug("Instruction file read skipped for %s: %s", path, exc)
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
        try:
            result_obj = await asyncio.to_thread(self.docs.search, query, None, mode, session_id)
            resolved_result = await result_obj if asyncio.iscoroutine(result_obj) else result_obj
        except TimeoutError:
            return "✗ Doküman araması zaman aşımına uğradı."
        except Exception as exc:
            logger.exception("SidarAgent docs search tool failed: query=%s mode=%s", query, mode)
            return f"✗ Doküman araması başarısız: {exc}"

        if not isinstance(resolved_result, tuple) or len(resolved_result) != 2:
            return "✗ Doküman araması geçersiz yanıt döndürdü."

        _ok, result = resolved_result
        text = str(result or "").strip()
        if not text:
            return "ℹ Doküman araması boş yanıt döndürdü."
        return text

    async def _execute_tool(self, tool: str, argument: str) -> str:
        return await execute_tool_service(
            tool,
            argument,
            resolve_handler=lambda handler_name: getattr(self, handler_name, None),
        )

    async def _tool_subtask(self, arg: str) -> str:
        task = (arg or "").strip()
        if not task:
            return "⚠ Alt görev belirtilmedi."

        try:
            _metrics = get_agent_metrics_collector()
        except Exception:
            _metrics = None

        agent_max_steps = getattr(self.cfg, "AGENT_MAX_REACT_STEPS", None)
        resolved_agent_steps = (
            agent_max_steps
            if agent_max_steps is not None
            else getattr(Config, "AGENT_MAX_REACT_STEPS", 10)
        )
        legacy_subtask_steps = getattr(self.cfg, "SUBTASK_MAX_STEPS", None)
        if (
            legacy_subtask_steps is not None
            and int(legacy_subtask_steps) != int(getattr(Config, "SUBTASK_MAX_STEPS", 5))
            and int(resolved_agent_steps) == int(getattr(Config, "AGENT_MAX_REACT_STEPS", 10))
        ):
            # Backward compatibility: existing callers/tests that explicitly tune
            # SUBTASK_MAX_STEPS keep their narrower guard unless the new agent-level
            # ReAct setting is also overridden.
            max_steps = int(legacy_subtask_steps)
        else:
            max_steps = int(
                agent_max_steps
                if agent_max_steps is not None
                else getattr(self.cfg, "MAX_REACT_STEPS", legacy_subtask_steps or 5)
            )
        max_steps = max(1, max_steps)
        feedback = task

        for _ in range(max_steps):
            llm_started_at = None
            tool_started_at = None
            tool = ""
            try:
                llm_started_at = time.monotonic()
                raw = await self.llm.chat(
                    messages=[{"role": "user", "content": feedback}],
                    model=getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL),
                    temperature=0.1,
                    stream=False,
                    json_mode=True,
                )
                if _metrics is not None:
                    _metrics.record_step(
                        "sidar_agent",
                        "llm_decision",
                        str(getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL) or "unknown"),
                        "success",
                        time.monotonic() - llm_started_at,
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

                tool_started_at = time.monotonic()
                tool_result = await self._execute_tool(tool, action.argument)
                if _metrics is not None:
                    _metrics.record_step(
                        "sidar_agent",
                        "tool_execution",
                        tool,
                        "success",
                        time.monotonic() - tool_started_at,
                    )
                feedback = f"Araç sonucu: {tool_result}"
            except ValidationError:
                if _metrics is not None:
                    _metrics.record_step(
                        "sidar_agent",
                        "llm_decision",
                        str(getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL) or "unknown"),
                        "failed",
                        max(0.0, time.monotonic() - (llm_started_at or time.monotonic())),
                    )
                feedback = "Şema doğrulama hatası: thought/tool/argument alanları zorunlu."
            except Exception as exc:
                if _metrics is not None:
                    failed_step = "tool_execution" if tool else "llm_decision"
                    failed_target = tool or str(
                        getattr(self.cfg, "TEXT_MODEL", self.cfg.CODING_MODEL) or "unknown"
                    )
                    started_at = tool_started_at or llm_started_at or time.monotonic()
                    _metrics.record_step(
                        "sidar_agent",
                        failed_step,
                        failed_target,
                        "failed",
                        max(0.0, time.monotonic() - started_at),
                    )
                logger.exception("Tool execution failed in subtask loop: tool=%s", tool or "llm")
                action_argument = getattr(locals().get("action", None), "argument", "")
                feedback = (
                    "Araç çalışmadı; sonraki adımda bunu dikkate al. "
                    f"tool={tool or 'llm_decision'} argument={action_argument!r} "
                    f"error={exc}"
                )

        return SUBTASK_MAX_STEPS_MESSAGE

    async def _tool_github_smart_pr(self, arg: str) -> str:
        return await github_smart_pr.create_smart_pr(arg=arg, code=self.code, github=self.github)

    # ─────────────────────────────────────────────
    #  BELLEK ÖZETLEME VE VEKTÖR ARŞİVLEME (ASYNC)
    # ─────────────────────────────────────────────

    async def _summarize_memory(self) -> None:
        """Konuşma geçmişini LLM ile özetler ve belleği sıkıştırır.

        AYRICA: Eski konuşmaları 'Sonsuz Hafıza' için Vektör DB'ye (ChromaDB) gömer.
        """
        history = await self.memory.get_history()
        if len(history) < 4:
            return

        # 1. VEKTÖR BELLEK (SONSUZ HAFIZA) KAYDI
        # Kısa özetlemeye geçmeden önce, tüm detayları RAG sistemine kaydediyoruz
        def _format_turn(turn: dict[str, Any]) -> str:
            turn_time = time.localtime(turn.get("timestamp", time.time()))
            ts = time.strftime("%Y-%m-%d %H:%M:%S", turn_time)
            return f"[{ts}] {turn['role'].upper()}:\n{turn['content']}"

        full_turns_text = "\n\n".join(_format_turn(t) for t in history)

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
        turns_text_short = "\n".join(f"{t['role'].upper()}: {t['content'][:400]}" for t in history)
        summarize_prompt = (
            "Aşağıdaki konuşmayı kısa ve bilgilendirici şekilde özetle. "
            "Teknik detayları, dosya adlarını ve kod kararlarını koru:\n\n" + turns_text_short
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
        """Ajanın güvenlik seviyesini dinamik olarak değiştirir.

        Değişikliği sohbet belleğine kalıcı olarak yazar.
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
