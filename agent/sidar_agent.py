"""
Sidar Project - Ana Ajan
Supervisor tabanlı multi-agent omurgasıyla çalışan yazılım mühendisi AI asistanı (Asenkron).
"""

import asyncio
import contextlib
import importlib
import inspect
import json
import logging
import sys
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

from config import Config
from core.ci_remediation import (
    build_ci_failure_context,
    build_ci_failure_prompt,
    build_ci_remediation_payload,
    build_self_heal_patch_prompt,
    normalize_self_heal_plan,
)
from core.entity_memory import get_entity_memory
from core.llm_client import LLMClient
from core.memory import ConversationMemory
from core.rag import DocumentStore
from managers.code_manager import CodeManager
from managers.github_manager import GitHubManager
from managers.package_info import PackageInfoManager
from managers.security import SecurityManager
from managers.system_health import SystemHealthManager
from managers.todo_manager import TodoManager
from managers.web_search import WebSearchManager

agent_contracts = sys.modules.get("agent.core.contracts") or import_module("agent.core.contracts")
agent_definitions = sys.modules.get("agent.definitions") or import_module("agent.definitions")

SIDAR_SYSTEM_PROMPT = agent_definitions.SIDAR_SYSTEM_PROMPT
ExternalTrigger = agent_contracts.ExternalTrigger
if TYPE_CHECKING:
    from agent.core.contracts import ExternalTrigger as ExternalTriggerType
else:
    ExternalTriggerType = Any


def get_agent_metrics_collector() -> Any:
    from core.agent_metrics import get_agent_metrics_collector as _get_agent_metrics_collector

    return _get_agent_metrics_collector()


def _default_derive_correlation_id(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


derive_correlation_id = getattr(
    agent_contracts, "derive_correlation_id", _default_derive_correlation_id
)


class _FallbackFederationTaskEnvelope:
    def __init__(self, **kwargs: Any) -> None:
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
    def __init__(self, **kwargs: Any) -> None:
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


FederationTaskEnvelope = getattr(
    agent_contracts, "FederationTaskEnvelope", _FallbackFederationTaskEnvelope
)
ActionFeedback = getattr(agent_contracts, "ActionFeedback", _FallbackActionFeedback)

logger = logging.getLogger(__name__)

ARCHIVE_CONTEXT_HEADER = "[Geçmiş Sohbet Arşivinden İlgili Notlar]"
CONTEXT_GEMINI_MODEL_LABEL = "Gemini Modeli"
CONTEXT_GITHUB_CONNECTED_PREFIX = "Bağlı — "
CONTEXT_TASK_LIST_HEADER = "[Aktif Görev Listesi]"
SUBTASK_MAX_STEPS_MESSAGE = "✗ Maksimum adım sınırına ulaşıldı. Alt görev tamamlanamadı."
GITHUB_SMART_PR_NO_TOKEN_MESSAGE = "⚠ GitHub token bulunamadı."  # nosec B105
GITHUB_SMART_PR_NO_BRANCH_MESSAGE = "✗ Aktif branch bulunamadı."
GITHUB_SMART_PR_NO_CHANGES_MESSAGE = "ℹ Değişiklik bulunamadı; PR oluşturulmadı."
GITHUB_SMART_PR_CREATE_FAILED_PREFIX = "✗ PR oluşturulamadı:"
GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX = "✓ PR oluşturuldu:"


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
            keep_last=getattr(cfg, "MEMORY_SUMMARY_KEEP_LAST", 4),
        )
        llm = LLMClient(cfg.AI_PROVIDER, cfg)
        web = WebSearchManager(cfg)
        pkg = PackageInfoManager(cfg)
        docs = DocumentStore(
            cfg.RAG_DIR,
            top_k=cfg.RAG_TOP_K,
            chunk_size=cfg.RAG_CHUNK_SIZE,
            chunk_overlap=cfg.RAG_CHUNK_OVERLAP,
            use_gpu=getattr(cfg, "USE_GPU", False),
            gpu_device=getattr(cfg, "GPU_DEVICE", 0),
            mixed_precision=getattr(cfg, "GPU_MIXED_PRECISION", False),
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
    """
    Sidar — Yazılım Mimarı ve Baş Mühendis AI Asistanı.
    Tamamen asenkron ağ istekleri, stream, yapısal veri ve sonsuz vektör hafıza uyumlu yapı.
    """

    VERSION = "5.1.0"  # Ürün baseline: Ultimate Launcher + multimodal/browser/voice Faz A/B

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
        self._last_activity_ts: float = time.time()
        self._nightly_maintenance_lock: asyncio.Lock | None = None
        self._last_nightly_maintenance_ts: float = 0.0

        # Tek omurga: supervisor tabanlı multi-agent
        self._supervisor = None
        self._initialized = False
        # Bulgu D: asyncio.Lock() lazy init — async bağlamda oluşturulur.
        self._init_lock: asyncio.Lock | None = None

        logger.info(
            "SidarAgent v%s başlatıldı — sağlayıcı=%s model=%s erişim=%s (VECTOR MEMORY + ASYNC)",
            self.VERSION,
            self.cfg.AI_PROVIDER,
            self.cfg.CODING_MODEL,
            self.cfg.ACCESS_LEVEL,
        )

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
        import re as _re

        text = raw.strip() if isinstance(raw, str) else ""
        # Markdown ```json ... ``` veya ``` ... ``` bloğunu soy
        md_match = _re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if md_match:
            text = md_match.group(1).strip()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"tool": "final_answer", "argument": raw}
        if not isinstance(data, dict):
            return {"tool": "final_answer", "argument": raw}
        if "tool" not in data:
            data["tool"] = "final_answer"
        return data

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
        """
        Kullanıcı girdisini asenkron işle ve yanıtı STREAM olarak döndür.
        """
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

    def _ensure_autonomy_runtime_state(self) -> None:
        if not hasattr(self, "_autonomy_history") or self._autonomy_history is None:
            self._autonomy_history = []
        if not hasattr(self, "_autonomy_lock"):
            self._autonomy_lock = None

    async def _append_autonomy_history(self, record: dict[str, Any]) -> None:
        self._ensure_autonomy_runtime_state()
        if self._autonomy_lock is None:
            self._autonomy_lock = asyncio.Lock()
        async with self._autonomy_lock:
            history = list(self._autonomy_history[-49:])
            history.append(dict(record))
            self._autonomy_history = history

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
        snapshots: list[dict[str, str]] = []
        for path in scope_paths[:6]:
            normalized = str(path or "").strip().lstrip("./")
            if not normalized:
                continue
            ok, content = await asyncio.to_thread(self.code.read_file, normalized, False)
            if not ok:
                continue
            snapshots.append({"path": normalized, "content": str(content)})
        return snapshots

    def _resolve_self_heal_scope_batches(
        self, scope_paths: list[str], remediation_loop: dict[str, Any]
    ) -> list[list[str]]:
        configured_batch_size = max(
            1, int(getattr(self.cfg, "SELF_HEAL_AUTONOMOUS_BATCH_SIZE", 5) or 5)
        )
        candidate_batches: list[list[str]] = []
        for item in list(remediation_loop.get("autonomous_batches") or []):
            if not isinstance(item, dict):
                continue
            batch_scope = [
                str(path).strip()
                for path in list(item.get("scope_paths") or [])
                if str(path).strip()
            ]
            if batch_scope:
                candidate_batches.append(batch_scope)
        if not candidate_batches:
            candidate_batches = [
                scope_paths[index : index + configured_batch_size]
                for index in range(0, len(scope_paths), configured_batch_size)
            ]

        normalized: list[list[str]] = []
        seen_keys: set[tuple[str, ...]] = set()
        for batch_scope in candidate_batches:
            chunk = [path for path in batch_scope if path in scope_paths]
            if not chunk:
                continue
            key = tuple(chunk)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            normalized.append(chunk)
        return normalized

    async def _build_self_heal_plan(
        self,
        *,
        ci_context: dict[str, Any],
        diagnosis: str,
        remediation_loop: dict[str, Any],
    ) -> dict[str, Any]:
        scope_paths = [
            str(item).strip()
            for item in list(remediation_loop.get("scope_paths") or [])
            if str(item).strip()
        ]
        if not scope_paths:
            return {
                "summary": "Self-heal kapsamı boş olduğu için plan oluşturulmadı.",
                "confidence": "unknown",
                "operations": [],
                "validation_commands": list(remediation_loop.get("validation_commands") or []),
            }

        max_operations = max(1, int(getattr(self.cfg, "SELF_HEAL_MAX_PATCHES", 3) or 3))
        fallback_validation_commands = list(remediation_loop.get("validation_commands") or [])
        plan_timeout_seconds = max(
            30,
            int(getattr(self.cfg, "SELF_HEAL_PLAN_TIMEOUT_SECONDS", 180) or 180),
        )
        plan_max_retries = max(
            1,
            int(getattr(self.cfg, "SELF_HEAL_PLAN_MAX_RETRIES", 3) or 3),
        )
        skip_full_scope_min_files = max(
            1,
            int(getattr(self.cfg, "SELF_HEAL_SKIP_FULL_SCOPE_MIN_FILES", 6) or 6),
        )

        async def _generate_plan_for_scope(paths: list[str]) -> dict[str, Any]:
            last_plan: dict[str, Any] | None = None
            for attempt in range(1, plan_max_retries + 1):
                snapshots = await self._collect_self_heal_snapshots(paths)
                scope_loop = dict(remediation_loop)
                scope_loop["scope_paths"] = paths
                scope_loop["plan_retry"] = {"attempt": attempt, "max_retries": plan_max_retries}
                prompt = build_self_heal_patch_prompt(ci_context, diagnosis, scope_loop, snapshots)
                try:
                    raw_plan = await asyncio.wait_for(
                        self.llm.chat(
                            messages=[{"role": "user", "content": prompt}],
                            model=getattr(self.cfg, "CODING_MODEL", None),
                            temperature=0.1,
                            stream=False,
                            json_mode=True,
                        ),
                        timeout=plan_timeout_seconds,
                    )
                except TimeoutError:
                    logger.warning(
                        "Self-heal plan generation timeout: scope=%s timeout=%ss attempt=%s/%s",
                        ",".join(paths[:6]),
                        plan_timeout_seconds,
                        attempt,
                        plan_max_retries,
                    )
                    last_plan = {
                        "summary": (
                            "Self-heal planı zaman aşımına uğradı; "
                            "daha küçük batch ile yeniden denenecek."
                        ),
                        "confidence": "unknown",
                        "operations": [],
                        "validation_commands": fallback_validation_commands,
                    }
                    continue
                except Exception as exc:
                    logger.warning(
                        "Self-heal plan generation failed for scope %s at attempt %s/%s: %s",
                        paths,
                        attempt,
                        plan_max_retries,
                        exc,
                    )
                    last_plan = {
                        "summary": f"Self-heal planı üretilemedi: {exc}",
                        "confidence": "unknown",
                        "operations": [],
                        "validation_commands": fallback_validation_commands,
                    }
                    continue

                normalized = normalize_self_heal_plan(
                    raw_plan,
                    scope_paths=paths,
                    fallback_validation_commands=fallback_validation_commands,
                    max_operations=max_operations,
                )
                normalized["plan_attempt"] = attempt
                normalized["plan_max_retries"] = plan_max_retries
                if list(normalized.get("operations") or []):
                    return normalized
                last_plan = normalized

            if last_plan is not None:
                summary = str(last_plan.get("summary") or "").strip()
                attempts_info = f" (attempts: {plan_max_retries}/{plan_max_retries})"
                last_plan["summary"] = f"{summary}{attempts_info}" if summary else attempts_info.strip()
                last_plan["plan_attempt"] = plan_max_retries
                last_plan["plan_max_retries"] = plan_max_retries
                return last_plan
            return {
                "summary": "Self-heal planı üretilemedi.",
                "confidence": "unknown",
                "operations": [],
                "validation_commands": fallback_validation_commands,
                "plan_attempt": plan_max_retries,
                "plan_max_retries": plan_max_retries,
            }

        should_attempt_full_scope = (
            len(scope_paths) < skip_full_scope_min_files
            and not list(remediation_loop.get("autonomous_batches") or [])
        )
        fallback_plan: dict[str, Any] | None = None
        if should_attempt_full_scope:
            initial_plan = await _generate_plan_for_scope(scope_paths)
            if list(initial_plan.get("operations") or []):
                return initial_plan
            fallback_plan = initial_plan

        for chunk in self._resolve_self_heal_scope_batches(scope_paths, remediation_loop):
            batch_plan = await _generate_plan_for_scope(chunk)
            if list(batch_plan.get("operations") or []):
                summary = str(batch_plan.get("summary") or "").strip()
                batch_plan["summary"] = (
                    f"{summary} (batch plan: {len(chunk)}/{len(scope_paths)} dosya)"
                    if summary
                    else f"Batch plan ile patch üretildi: {len(chunk)}/{len(scope_paths)} dosya."
                )
                return batch_plan
            fallback_plan = batch_plan

        if fallback_plan is not None:
            return fallback_plan
        return {
            "summary": "Self-heal planı üretilemedi.",
            "confidence": "unknown",
            "operations": [],
            "validation_commands": fallback_validation_commands,
        }

    async def _restore_self_heal_backups(self, backups: dict[str, str]) -> None:
        for path, content in backups.items():
            await asyncio.to_thread(self.code.write_file, path, content, False)

    async def _execute_self_heal_plan(
        self,
        *,
        remediation_loop: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        operations = list(plan.get("operations") or [])
        validation_commands = list(
            plan.get("validation_commands") or remediation_loop.get("validation_commands") or []
        )
        result: dict[str, Any] = {
            "status": "skipped",
            "summary": str(plan.get("summary") or "").strip() or "Self-heal planı uygulanmadı.",
            "operations_applied": [],
            "validation_results": [],
            "reverted": False,
            "confidence": str(plan.get("confidence") or "unknown"),
        }
        if not operations:
            result["summary"] = "Self-heal planı patch operasyonu içermediği için atlandı."
            return result
        if not validation_commands:
            result["status"] = "blocked"
            result["summary"] = (
                "Self-heal planı güvenli doğrulama komutu içermediği için engellendi."
            )
            return result

        backups: dict[str, str] = {}
        applied: list[str] = []
        try:
            for item in operations:
                path = str(item.get("path") or "").strip()
                target = str(item.get("target") or "")
                replacement = str(item.get("replacement") or "")
                if path not in backups:
                    ok, original = await asyncio.to_thread(self.code.read_file, path, False)
                    if not ok:
                        raise RuntimeError(f"Self-heal yedekleme başarısız: {original}")
                    backups[path] = str(original)
                ok, message = await asyncio.to_thread(
                    self.code.patch_file, path, target, replacement
                )
                if not ok:
                    raise RuntimeError(f"{path} patch edilemedi: {message}")
                applied.append(path)

            for command in validation_commands:
                ok, output = await asyncio.to_thread(
                    self.code.run_shell_in_sandbox,
                    command,
                    str(self.cfg.BASE_DIR),
                )
                result["validation_results"].append(
                    {"command": command, "ok": ok, "output": output}
                )
                if not ok:
                    raise RuntimeError(f"Sandbox doğrulaması başarısız: {command}")

            result["status"] = "applied"
            result["operations_applied"] = applied
            result["summary"] = (
                f"Self-heal başarıyla uygulandı: {len(applied)} patch, "
                f"{len(result['validation_results'])} sandbox doğrulaması geçti."
            )
            return result
        except Exception as exc:
            await self._restore_self_heal_backups(backups)
            result["status"] = "reverted"
            result["reverted"] = True
            result["operations_applied"] = applied
            result["summary"] = f"Self-heal başarısız oldu ve geri alındı: {exc}"
            return result

    async def _attempt_autonomous_self_heal(
        self,
        *,
        ci_context: dict[str, Any],
        diagnosis: str,
        remediation: dict[str, Any],
        human_approval: bool | None = None,
    ) -> dict[str, Any]:
        remediation_loop = dict(remediation.get("remediation_loop") or {})
        if not bool(getattr(self.cfg, "ENABLE_AUTONOMOUS_SELF_HEAL", False)):
            execution = {"status": "disabled", "summary": "Autonomous self-heal kapalı."}
            remediation["self_heal_execution"] = execution
            return execution
        if str(remediation_loop.get("status", "")).strip() != "planned":
            execution = {"status": "skipped", "summary": "Remediation loop plan durumunda değil."}
            remediation["self_heal_execution"] = execution
            return execution
        if bool(remediation_loop.get("needs_human_approval")):
            if human_approval is False:
                remediation_loop["status"] = "rejected"
                self._update_remediation_step(
                    remediation_loop,
                    "handoff",
                    status="rejected",
                    detail="HITL onayı reddedildi; self-heal uygulanmadı.",
                )
                execution = {
                    "status": "rejected",
                    "summary": "İnsan onayı verilmediği için self-heal iptal edildi.",
                }
                remediation["remediation_loop"] = remediation_loop
                remediation["self_heal_execution"] = execution
                return execution
            if human_approval is True:
                remediation_loop["needs_human_approval"] = False
                self._update_remediation_step(
                    remediation_loop,
                    "handoff",
                    status="running",
                    detail="HITL onayı alındı; otonom self-heal devam ediyor.",
                )
            else:
                self._update_remediation_step(
                    remediation_loop,
                    "handoff",
                    status="awaiting_hitl",
                    detail="Riskli remediation otomatik uygulanmadı; HITL onayı bekleniyor.",
                )
                execution = {
                    "status": "awaiting_hitl",
                    "summary": "Risk seviyesi nedeniyle self-heal HITL onayına bırakıldı.",
                }
                remediation["remediation_loop"] = remediation_loop
                remediation["self_heal_execution"] = execution
                return execution
        if not hasattr(self, "code") or not hasattr(self, "llm"):
            execution = {
                "status": "blocked",
                "summary": "Self-heal için code/llm bağımlılıkları hazır değil.",
            }
            remediation["self_heal_execution"] = execution
            return execution

        plan = await self._build_self_heal_plan(
            ci_context=ci_context,
            diagnosis=diagnosis,
            remediation_loop=remediation_loop,
        )
        remediation["self_heal_plan"] = plan
        if not list(plan.get("operations") or []):
            execution = {"status": "blocked", "summary": "LLM patch planı üretilemedi."}
            if int(plan.get("plan_attempt") or 0) >= int(plan.get("plan_max_retries") or 0) > 0:
                remediation_loop["needs_human_intervention"] = True
                self._update_remediation_step(
                    remediation_loop,
                    "handoff",
                    status="pending",
                    detail=(
                        "Maksimum self-heal plan retry limiti aşıldı; "
                        "insan müdahalesi gerekiyor."
                    ),
                )
            self._update_remediation_step(
                remediation_loop,
                "patch",
                status="blocked",
                detail="LLM güvenli patch planı üretemedi.",
            )
            remediation["remediation_loop"] = remediation_loop
            remediation["self_heal_execution"] = execution
            return execution

        self._update_remediation_step(
            remediation_loop,
            "patch",
            status="running",
            detail="Self-heal patch operasyonları uygulanıyor.",
        )
        execution = await self._execute_self_heal_plan(remediation_loop=remediation_loop, plan=plan)
        remediation["self_heal_execution"] = execution

        if execution["status"] == "applied":
            remediation_loop["status"] = "applied"
            self._update_remediation_step(
                remediation_loop,
                "patch",
                status="completed",
                detail=f"{len(execution.get('operations_applied', []))} patch uygulandı.",
            )
            self._update_remediation_step(
                remediation_loop,
                "validate",
                status="completed",
                detail="Sandbox doğrulamaları başarıyla geçti.",
            )
            self._update_remediation_step(
                remediation_loop,
                "handoff",
                status="completed",
                detail="Değişiklikler başarıyla uygulandı; sonraki adım PR/proposal güncellemesi.",
            )
        else:
            remediation_loop["status"] = execution["status"]
            self._update_remediation_step(
                remediation_loop,
                "patch",
                status="failed",
                detail=execution["summary"],
            )
            self._update_remediation_step(
                remediation_loop,
                "validate",
                status="failed",
                detail="Self-heal doğrulaması başarısız olduğu için rollback yapıldı.",
            )
        remediation["remediation_loop"] = remediation_loop
        return execution

    @staticmethod
    def _trigger_attr(trigger: ExternalTriggerType | dict[str, Any], name: str, default: Any = "") -> Any:
        if isinstance(trigger, dict):
            return trigger.get(name, default)
        return getattr(trigger, name, default)

    @staticmethod
    def _trigger_payload(trigger: ExternalTriggerType | dict[str, Any]) -> dict[str, Any]:
        raw_payload = SidarAgent._trigger_attr(trigger, "payload", {})
        return dict(raw_payload or {}) if isinstance(raw_payload, dict) else {}

    @staticmethod
    def _trigger_meta(trigger: ExternalTriggerType | dict[str, Any]) -> dict[str, Any]:
        raw_meta = SidarAgent._trigger_attr(trigger, "meta", {})
        return dict(raw_meta or {}) if isinstance(raw_meta, dict) else {}

    @staticmethod
    def _trigger_to_prompt(trigger: ExternalTriggerType | dict[str, Any]) -> str:
        if isinstance(trigger, dict):
            event_name = str(trigger.get("event_name", "event"))
            payload = dict(trigger.get("payload", {}) or {})
            source = str(trigger.get("source", "external"))
            return f"[EXTERNAL EVENT]\\nsource={source}\\nevent_name={event_name}\\npayload={json.dumps(payload, ensure_ascii=False)}"
        to_prompt = getattr(trigger, "to_prompt", None)
        if callable(to_prompt):
            return str(to_prompt())
        event_name = str(getattr(trigger, "event_name", "event"))
        source = str(getattr(trigger, "source", "external"))
        payload = SidarAgent._trigger_payload(trigger)
        return f"[EXTERNAL EVENT]\\nsource={source}\\nevent_name={event_name}\\npayload={json.dumps(payload, ensure_ascii=False)}"

    @staticmethod
    def _build_trigger_prompt(
        trigger: ExternalTriggerType | dict[str, Any],
        payload_dict: dict[str, Any],
        ci_context: dict[str, Any] | None,
    ) -> str:
        if ci_context:
            return build_ci_failure_prompt(ci_context)

        if payload_dict.get("kind") == "federation_task":
            federation_payload = dict(payload_dict.get("federation_task") or payload_dict)
            if payload_dict.get("federation_prompt"):
                return str(payload_dict.get("federation_prompt"))
            return FederationTaskEnvelope(
                task_id=str(federation_payload.get("task_id") or SidarAgent._trigger_attr(trigger, "trigger_id", "")),
                source_system=str(federation_payload.get("source_system") or SidarAgent._trigger_attr(trigger, "source", "external")),
                source_agent=str(federation_payload.get("source_agent") or "external"),
                target_system=str(federation_payload.get("target_system") or "sidar"),
                target_agent=str(federation_payload.get("target_agent") or "supervisor"),
                goal=str(federation_payload.get("goal") or ""),
                protocol=str(federation_payload.get("protocol") or "federation.v1"),
                intent=str(federation_payload.get("intent") or "mixed"),
                context=dict(federation_payload.get("context") or {}),
                inputs=list(federation_payload.get("inputs") or []),
                meta=dict(federation_payload.get("meta") or {}),
                correlation_id=str(
                    federation_payload.get("correlation_id")
                    or SidarAgent._trigger_attr(trigger, "correlation_id", "")
                ),
            ).to_prompt()

        event_name = str(SidarAgent._trigger_attr(trigger, "event_name", "event"))
        if payload_dict.get("kind") == "action_feedback" or event_name == "action_feedback":
            return ActionFeedback(
                feedback_id=str(payload_dict.get("feedback_id") or SidarAgent._trigger_attr(trigger, "trigger_id", "")),
                source_system=str(payload_dict.get("source_system") or SidarAgent._trigger_attr(trigger, "source", "external")),
                source_agent=str(payload_dict.get("source_agent") or "external"),
                action_name=str(payload_dict.get("action_name") or event_name),
                status=str(payload_dict.get("status") or "received"),
                summary=str(
                    payload_dict.get("summary") or "Dış sistem action feedback sinyali alındı."
                ),
                related_task_id=str(payload_dict.get("related_task_id") or ""),
                related_trigger_id=str(payload_dict.get("related_trigger_id") or ""),
                details=dict(payload_dict.get("details") or {}),
                meta=dict(payload_dict.get("meta") or SidarAgent._trigger_meta(trigger) or {}),
                correlation_id=str(
                    payload_dict.get("correlation_id")
                    or SidarAgent._trigger_attr(trigger, "correlation_id", "")
                ),
            ).to_prompt()

        return SidarAgent._trigger_to_prompt(trigger)

    def _build_trigger_correlation(
        self,
        trigger: ExternalTriggerType | dict[str, Any],
        payload_dict: dict[str, Any],
    ) -> dict[str, Any]:
        self._ensure_autonomy_runtime_state()
        trigger_meta = SidarAgent._trigger_meta(trigger)
        correlation_id = derive_correlation_id(
            SidarAgent._trigger_attr(trigger, "correlation_id", ""),
            trigger_meta.get("correlation_id", ""),
            payload_dict.get("correlation_id", ""),
            payload_dict.get("related_task_id", ""),
            payload_dict.get("task_id", ""),
            SidarAgent._trigger_attr(trigger, "trigger_id", ""),
        )
        related_trigger_id = str(payload_dict.get("related_trigger_id") or "").strip()
        related_task_id = str(
            payload_dict.get("related_task_id") or payload_dict.get("task_id") or ""
        ).strip()

        matches: list[dict[str, Any]] = []
        for item in reversed(list(getattr(self, "_autonomy_history", []) or [])):
            item_trigger_id = str(item.get("trigger_id", "") or "")
            item_payload = dict(item.get("payload") or {})
            item_corr = derive_correlation_id(
                item.get("correlation", {}).get("correlation_id", "")
                if isinstance(item.get("correlation"), dict)
                else "",
                item.get("meta", {}).get("correlation_id", "")
                if isinstance(item.get("meta"), dict)
                else "",
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

        unique_matches: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in matches:
            item_id = str(item.get("trigger_id", "") or "")
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            unique_matches.append(item)

        related_trigger_ids = [str(item.get("trigger_id", "") or "") for item in unique_matches[:8]]
        related_sources = list(
            dict.fromkeys(
                str(item.get("source", "") or "")
                for item in unique_matches[:8]
                if str(item.get("source", "") or "")
            )
        )
        return {
            "correlation_id": correlation_id,
            "related_trigger_id": related_trigger_id,
            "related_task_id": related_task_id,
            "matched_records": len(unique_matches),
            "related_trigger_ids": related_trigger_ids,
            "related_sources": related_sources,
            "latest_related_status": str(unique_matches[0].get("status", "") or "")
            if unique_matches
            else "",
        }

    async def handle_external_trigger(
        self, trigger: ExternalTriggerType | dict[str, Any]
    ) -> dict[str, Any]:
        """Webhook/cron/federation kaynaklı proaktif tetikleri işler ve geçmişe kaydeder."""
        await self.initialize()
        self._ensure_autonomy_runtime_state()
        self.mark_activity("external_trigger")

        if isinstance(trigger, dict):
            trigger = ExternalTrigger(
                trigger_id=str(trigger.get("trigger_id", f"trigger-{int(time.time())}")),
                source=str(trigger.get("source", "external")),
                event_name=str(trigger.get("event_name", "event")),
                payload=dict(trigger.get("payload", {}) or {}),
                meta=dict(trigger.get("meta", {}) or {}),
            )

        payload_dict = self._trigger_payload(trigger)
        event_name = str(self._trigger_attr(trigger, "event_name", "event"))
        ci_context = (
            payload_dict
            if payload_dict.get("kind") in {"workflow_run", "check_run", "check_suite"}
            and payload_dict.get("workflow_name")
            else build_ci_failure_context(event_name, payload_dict)
        )
        correlation = self._build_trigger_correlation(trigger, payload_dict)
        prompt = self._build_trigger_prompt(trigger, payload_dict, ci_context)
        started_at = time.time()
        status = "success"
        summary = ""
        remediation: dict[str, Any] | None = None
        try:
            summary = await self._try_multi_agent(prompt)
            if not isinstance(summary, str) or not summary.strip():
                status = "empty"
                summary = "⚠ Proaktif tetik işlendikten sonra boş çıktı üretildi."
            elif ci_context:
                remediation = build_ci_remediation_payload(ci_context, summary)
                try:
                    await self._attempt_autonomous_self_heal(
                        ci_context=ci_context,
                        diagnosis=summary,
                        remediation=remediation,
                    )
                except Exception as exc:
                    remediation["self_heal_execution"] = {
                        "status": "failed",
                        "summary": f"Autonomous self-heal hata verdi: {exc}",
                    }
        except Exception as exc:
            status = "failed"
            summary = f"⚠ Proaktif tetik işlenemedi: {exc}"

        record = {
            "trigger_id": str(self._trigger_attr(trigger, "trigger_id", "")),
            "source": str(self._trigger_attr(trigger, "source", "external")),
            "event_name": event_name,
            "status": status,
            "summary": summary,
            "payload": payload_dict,
            "meta": self._trigger_meta(trigger),
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

    async def run_nightly_memory_maintenance(
        self,
        *,
        force: bool = False,
        reason: str = "nightly_idle",
    ) -> dict[str, Any]:
        """Uzun süreli kullanım için sohbet/RAG belleğini sıkıştırır ve temizler."""
        await self.initialize()
        if not bool(getattr(self.cfg, "ENABLE_NIGHTLY_MEMORY_PRUNING", False)):
            return {"status": "disabled", "reason": "config_disabled"}

        idle_seconds = max(60, int(getattr(self.cfg, "NIGHTLY_MEMORY_IDLE_SECONDS", 1800) or 1800))
        idle_for = self.seconds_since_last_activity()
        if not force and idle_for < idle_seconds:
            return {
                "status": "skipped",
                "reason": "not_idle",
                "idle_for_seconds": round(idle_for, 2),
                "idle_threshold_seconds": idle_seconds,
            }

        if self._nightly_maintenance_lock is None:
            self._nightly_maintenance_lock = asyncio.Lock()
        if self._nightly_maintenance_lock.locked():
            return {
                "status": "skipped",
                "reason": "already_running",
                "idle_for_seconds": round(idle_for, 2),
            }

        async with self._nightly_maintenance_lock:
            entity_report: dict[str, Any] = {"purged": 0, "status": "disabled"}
            try:
                entity_memory = get_entity_memory(self.cfg)
                await entity_memory.initialize()
                entity_report = {
                    "status": "completed",
                    "purged": await entity_memory.purge_expired(),
                }
            except Exception as exc:
                entity_report = {"status": "failed", "error": str(exc), "purged": 0}

            memory_report = await self.memory.run_nightly_consolidation(
                keep_recent_sessions=max(
                    0, int(getattr(self.cfg, "NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS", 2) or 2)
                ),
                min_messages=max(
                    2, int(getattr(self.cfg, "NIGHTLY_MEMORY_SESSION_MIN_MESSAGES", 12) or 12)
                ),
            )

            rag_reports: list[dict[str, Any]] = []
            keep_recent_docs = max(
                1, int(getattr(self.cfg, "NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS", 2) or 2)
            )
            raw_session_ids = memory_report.get("session_ids", [])
            session_ids = raw_session_ids if isinstance(raw_session_ids, list) else []
            for session_id in session_ids:
                report = await asyncio.to_thread(
                    self.docs.consolidate_session_documents,
                    str(session_id),
                    keep_recent_docs=keep_recent_docs,
                )
                rag_reports.append(report)

            removed_docs = sum(int(item.get("removed_docs", 0) or 0) for item in rag_reports)
            raw_sessions_compacted = memory_report.get("sessions_compacted", 0)
            sessions_compacted = (
                raw_sessions_compacted
                if isinstance(raw_sessions_compacted, int)
                else int(raw_sessions_compacted)
                if isinstance(raw_sessions_compacted, str) and raw_sessions_compacted.isdigit()
                else 0
            )
            result = {
                "status": "completed",
                "reason": reason,
                "idle_for_seconds": round(idle_for, 2),
                "memory_report": memory_report,
                "entity_report": entity_report,
                "rag_reports": rag_reports,
                "sessions_compacted": sessions_compacted,
                "rag_docs_pruned": removed_docs,
            }
            self._last_nightly_maintenance_ts = time.time()
            await self._append_autonomy_history(
                {
                    "trigger_id": f"nightly-{int(self._last_nightly_maintenance_ts)}",
                    "source": "nightly_memory",
                    "event_name": "memory_consolidation",
                    "status": result["status"],
                    "summary": (
                        f"Nightly maintenance tamamlandı: "
                        f"{result['sessions_compacted']} oturum sıkıştırıldı, "
                        f"{removed_docs} RAG dokümanı budandı, "
                        f"{entity_report.get('purged', 0)} entity kaydı temizlendi."
                    ),
                    "payload": {
                        "reason": reason,
                        "idle_for_seconds": round(idle_for, 2),
                    },
                    "meta": {
                        "kind": "nightly_memory_maintenance",
                        "force": str(bool(force)).lower(),
                    },
                    "created_at": self._last_nightly_maintenance_ts,
                    "completed_at": self._last_nightly_maintenance_ts,
                }
            )
            return result

    def get_autonomy_activity(self, limit: int = 20) -> dict[str, Any]:
        """Son proaktif tetik kayıtlarını özet metriklerle birlikte döndürür."""
        self._ensure_autonomy_runtime_state()
        normalized_limit = max(1, int(limit or 20))
        items = [dict(item) for item in self._autonomy_history[-normalized_limit:]]
        counts_by_status: dict[str, int] = {}
        counts_by_source: dict[str, int] = {}
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
            supervisor_mod = import_module("agent.core.supervisor")
            # Bazı izolasyon testleri `agent.core.supervisor` modülünü stub rol sınıflarıyla
            # import eder ve modülü cache'te bırakabilir. Bu durumda gerçek role-agent
            # zinciri yerine `stub:*` çıktıları dönebilir. Role sınıflarının kaynak modülünü
            # doğrulayarak gerekiyorsa supervisor modülünü yeniden yükle.
            role_symbols = (
                "ResearcherAgent",
                "CoderAgent",
                "ReviewerAgent",
                "PoyrazAgent",
                "QAAgent",
                "CoverageAgent",
            )
            needs_reload = any(
                not str(
                    getattr(getattr(supervisor_mod, symbol, None), "__module__", "")
                ).startswith("agent.roles.")
                for symbol in role_symbols
            )
            if needs_reload:
                supervisor_mod = importlib.reload(supervisor_mod)
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
        """
        Proje genelindeki SIDAR.md ve CLAUDE.md dosyalarını hiyerarşik şekilde yükle.
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
            return f"✗ Doküman araması başarısız: {exc}"

        if not isinstance(resolved_result, tuple) or len(resolved_result) != 2:
            return "✗ Doküman araması geçersiz yanıt döndürdü."

        _ok, result = resolved_result
        text = str(result or "").strip()
        if not text:
            return "ℹ Doküman araması boş yanıt döndürdü."
        return text

    async def _execute_tool(self, tool: str, argument: str) -> str:
        normalized_tool = str(tool or "").strip().lower()
        if not normalized_tool:
            raise ValueError("Araç adı boş olamaz.")

        handler_name = f"_tool_{normalized_tool}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            raise ValueError(f"Bilinmeyen araç: {normalized_tool}")
        if not callable(handler):
            raise TypeError(f"Araç işleyicisi çağrılabilir değil: {handler_name}")

        result = handler(argument)
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)

    async def _tool_subtask(self, arg: str) -> str:
        task = (arg or "").strip()
        if not task:
            return "⚠ Alt görev belirtilmedi."

        try:
            _metrics = get_agent_metrics_collector()
        except Exception:
            _metrics = None

        max_steps = int(getattr(self.cfg, "SUBTASK_MAX_STEPS", 5))
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
                feedback = f"Araç çağrısı başarısız: {exc}"

        return SUBTASK_MAX_STEPS_MESSAGE

    async def _tool_github_smart_pr(self, arg: str) -> str:
        if not self.github.is_available():
            return GITHUB_SMART_PR_NO_TOKEN_MESSAGE

        parts = [p.strip() for p in (arg or "").split("|||")]
        title = parts[0] if len(parts) > 0 and parts[0] else "Otomatik PR"
        base = parts[1] if len(parts) > 1 and parts[1] else ""
        notes = parts[2] if len(parts) > 2 else ""

        ok, branch = self.code.run_shell("git branch --show-current")
        head = (branch or "").strip() if ok else ""
        if not head:
            return GITHUB_SMART_PR_NO_BRANCH_MESSAGE

        if not base:
            try:
                base = self.github.default_branch
            except Exception:
                base = "main"

        ok_status, status_out = self.code.run_shell("git status --short")
        if not ok_status or not str(status_out).strip():
            return GITHUB_SMART_PR_NO_CHANGES_MESSAGE

        self.code.run_shell("git diff --stat HEAD")
        ok_diff, diff_out = self.code.run_shell("git diff --no-color HEAD")
        diff_text = str(diff_out or "") if ok_diff else ""
        max_diff_chars = 10000
        if len(diff_text) > max_diff_chars:
            diff_text = (
                diff_text[:max_diff_chars]
                + "\n\n[Not] Diff çok büyük olduğu için geri kalanı kırpıldı."
            )

        _ok_log, commits = self.code.run_shell(f"git log --oneline {base}..HEAD")
        body = (
            f"{notes}\n\n"
            f"### Commitler\n{commits}\n\n"
            f"### Diff Özeti\n```diff\n{diff_text}\n```"
        )
        try:
            ok_pr, pr_out = self.github.create_pull_request(title, body, head, base)
        except TimeoutError:
            return f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} zaman aşımı"
        except Exception as exc:
            return f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} {exc}"

        if not ok_pr:
            reason = str(pr_out or "bilinmeyen hata")
            return f"{GITHUB_SMART_PR_CREATE_FAILED_PREFIX} {reason}"
        return f"{GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX} {pr_out}"

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
