"""
Sidar Agent Catalog — Çalışma Zamanı Ajan Keşfi ve Eklenti Pazaryeri.

Kayıtlı ajan türlerini, yeteneklerini ve meta verilerini yönetir.
Yeni uzman ajanlar `@AgentCatalog.register(...)` dekoratörü ile
veya `AgentCatalog.register_type(...)` metoduyla eklenir.
"""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

logger = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    """Kayıtlı bir ajan tipinin meta verisi."""

    role_name: str
    agent_class: type[Any] | None = None
    capabilities: list[str] = field(default_factory=list)
    description: str = ""
    version: str = "1.0.0"
    is_builtin: bool = True
    side_effect_level: str = "none"


@dataclass(frozen=True)
class BuiltinRoleContract:
    """Built-in role wiring contract shared by registry/router/health tests."""

    role_name: str
    class_name: str
    module_name: str
    capabilities: tuple[str, ...]
    supervisor_intents: tuple[str, ...] = ()
    swarm_intents: tuple[str, ...] = ()


BUILTIN_ROLE_CONTRACTS: tuple[BuiltinRoleContract, ...] = (
    BuiltinRoleContract(
        role_name="coder",
        class_name="CoderAgent",
        module_name="agent.roles.coder_agent",
        capabilities=("code_generation", "file_io", "shell_execution", "code_review"),
        supervisor_intents=("code",),
        swarm_intents=("code", "mixed", "code_generation", "file_io", "shell_execution"),
    ),
    BuiltinRoleContract(
        role_name="researcher",
        class_name="ResearcherAgent",
        module_name="agent.roles.researcher_agent",
        capabilities=("web_search", "rag_search", "summarization"),
        supervisor_intents=("research",),
        swarm_intents=("research", "web_search", "rag_search", "summarization"),
    ),
    BuiltinRoleContract(
        role_name="reviewer",
        class_name="ReviewerAgent",
        module_name="agent.roles.reviewer_agent",
        capabilities=("code_review", "security_audit", "quality_check"),
        supervisor_intents=("review",),
        swarm_intents=("review", "code_review", "security", "security_audit", "quality_check"),
    ),
    BuiltinRoleContract(
        role_name="poyraz",
        class_name="PoyrazAgent",
        module_name="agent.roles.poyraz_agent",
        capabilities=("marketing_strategy", "seo_analysis", "campaign_copy", "audience_ops"),
        supervisor_intents=("marketing",),
        swarm_intents=(
            "marketing",
            "seo",
            "campaign",
            "marketing_strategy",
            "seo_analysis",
            "campaign_copy",
            "audience_ops",
        ),
    ),
    BuiltinRoleContract(
        role_name="coverage",
        class_name="CoverageAgent",
        module_name="agent.roles.coverage_agent",
        capabilities=("coverage_analysis", "pytest_output_analysis", "autonomous_test_generation"),
        supervisor_intents=("coverage",),
        swarm_intents=("coverage", "coverage_analysis"),
    ),
    BuiltinRoleContract(
        role_name="qa",
        class_name="QAAgent",
        module_name="agent.roles.qa_agent",
        capabilities=("test_generation", "ci_remediation"),
        supervisor_intents=("qa",),
        swarm_intents=("qa", "tests", "test_generation", "ci_remediation"),
    ),
)
BUILTIN_ROLE_MODULES: tuple[str, ...] = tuple(
    contract.module_name for contract in BUILTIN_ROLE_CONTRACTS
)
EXPECTED_BUILTIN_ROLE_NAMES: tuple[str, ...] = tuple(
    contract.role_name for contract in BUILTIN_ROLE_CONTRACTS
)
_BUILTIN_IMPORT_FAILURES: dict[str, str] = {}


def _builtin_contract_by_role(role_name: str) -> BuiltinRoleContract | None:
    """Return the built-in role contract for ``role_name`` when it exists."""
    for contract in BUILTIN_ROLE_CONTRACTS:
        if contract.role_name == role_name:
            return contract
    return None


def _plugin_manifest_side_effect_level(role_name: str) -> str:
    """Return the manifest side-effect level for a plugin role, if declared."""

    try:
        from plugins.manifest import PLUGIN_MANIFESTS
    except Exception as exc:  # pragma: no cover - optional plugin package guard
        logger.debug("Plugin manifest side-effect lookup skipped: %s", exc)
        return "none"

    for manifest in PLUGIN_MANIFESTS.values():
        if manifest.role_name == role_name:
            return str(manifest.side_effect_level)
    return "none"


def _side_effect_requires_shell_gate(side_effect_level: str) -> bool:
    """Return whether the side effect level must pass shell-access authorization."""

    return str(side_effect_level or "none").startswith("external_")


def _assert_runtime_side_effect_allowed(spec: AgentSpec, cfg: Any | None = None) -> None:
    """Fail closed when a plugin manifest declares host/external side effects."""

    if spec.is_builtin or not _side_effect_requires_shell_gate(spec.side_effect_level):
        return
    try:
        from config import Config
        from managers.security import SecurityManager

        security = SecurityManager(cfg=cfg or Config())
    except Exception as exc:  # pragma: no cover - fail-closed defensive branch
        raise PermissionError(
            f"'{spec.role_name}' ajanı için güvenlik yöneticisi başlatılamadı; "
            "external side-effect plugin oluşturma reddedildi."
        ) from exc
    if not security.can_run_shell():
        raise PermissionError(
            f"'{spec.role_name}' ajanı side_effect_level={spec.side_effect_level!r} bildiriyor; "
            "ACCESS_LEVEL=full olmadan çalışma zamanı oluşturma reddedildi."
        )


def _resolve_canonical_builtin_class(
    *, role_name: str, agent_class: type[Any], is_builtin: bool
) -> type[Any]:
    """Prefer canonical class objects for built-in roles imported via temp module names.

    Some tests and loaders execute a built-in role file with an ad-hoc module name
    (for example ``reviewer_agent_under_test``). Python then creates a distinct
    class object even though the source file is the same. Built-in registry
    entries must point at the canonical import path declared in
    ``BUILTIN_ROLE_CONTRACTS`` so exports, router/supervisor checks, and runtime
    creation agree on class identity.
    """
    contract = _builtin_contract_by_role(role_name)
    if not is_builtin or contract is None:
        return agent_class
    if agent_class.__module__ == contract.module_name:
        return agent_class

    try:
        module = importlib.import_module(contract.module_name)
        canonical_class = cast(type[Any], getattr(module, contract.class_name))
    except Exception as exc:  # pragma: no cover - defensive fallback for optional deps
        _BUILTIN_IMPORT_FAILURES[contract.module_name] = _format_import_failure(exc)
        logger.debug(
            "Builtin role canonical import'u başarısız; geçici sınıf korunuyor: %s",
            contract.module_name,
            exc_info=True,
        )
        return agent_class

    if not isinstance(canonical_class, type):
        logger.debug(
            "Builtin role canonical sembolü bir sınıf değil; geçici sınıf korunuyor: %s.%s",
            contract.module_name,
            contract.class_name,
        )
        return agent_class

    logger.debug(
        "AgentCatalog: '%s' için geçici modül sınıfı canonical sınıfa normalize edildi (%s -> %s).",
        role_name,
        agent_class.__module__,
        contract.module_name,
    )
    return canonical_class


class AgentCatalog:
    """Sınıf-tabanlı ajan tip kataloğu."""

    _registry: dict[str, AgentSpec] = {}

    @classmethod
    def register(
        cls,
        *,
        capabilities: list[str] | None = None,
        description: str = "",
        version: str = "1.0.0",
        is_builtin: bool = False,
    ) -> Callable[[type], type]:
        """Decorate an agent class and add it to the catalog.

        ``is_builtin`` intentionally defaults to ``False`` for decorator-based
        registration so external/plugin roles are not marked built-in by
        accident. Built-in role modules must pass ``is_builtin=True`` explicitly.
        """

        def _decorator(agent_cls: type) -> type:
            role = getattr(agent_cls, "ROLE_NAME", agent_cls.__name__.lower().replace("agent", ""))
            cls.register_type(
                role_name=role,
                agent_class=agent_cls,
                capabilities=capabilities or [],
                description=description or (agent_cls.__doc__ or "").strip().split("\n")[0],
                version=version,
                is_builtin=is_builtin,
            )
            return agent_cls

        return _decorator

    @classmethod
    def register_type(
        cls,
        *,
        role_name: str,
        agent_class: type,
        capabilities: list[str] | None = None,
        description: str = "",
        version: str = "1.0.0",
        is_builtin: bool = True,
        side_effect_level: str | None = None,
    ) -> None:
        """Register an agent type programmatically.

        The programmatic API keeps ``is_builtin=True`` as its historical default.
        Runtime/plugin callers should pass ``is_builtin=False`` explicitly.
        """
        resolved_agent_class = _resolve_canonical_builtin_class(
            role_name=role_name, agent_class=agent_class, is_builtin=is_builtin
        )
        resolved_side_effect_level = (
            "none"
            if is_builtin
            else (side_effect_level or _plugin_manifest_side_effect_level(role_name))
        )
        spec = AgentSpec(
            role_name=role_name,
            agent_class=resolved_agent_class,
            capabilities=capabilities or [],
            description=description,
            version=version,
            is_builtin=is_builtin,
            side_effect_level=resolved_side_effect_level,
        )
        cls._registry[role_name] = spec
        contract = _builtin_contract_by_role(role_name)
        if (
            is_builtin
            and contract is not None
            and resolved_agent_class.__module__ == contract.module_name
        ):
            canonical_module = sys.modules.get(contract.module_name)
            canonical_export = (
                getattr(canonical_module, contract.class_name, None)
                if canonical_module is not None
                else None
            )
            role_exports = sys.modules.get("agent.roles")
            if role_exports is not None and canonical_export is resolved_agent_class:
                setattr(role_exports, contract.class_name, resolved_agent_class)
        logger.debug("AgentCatalog: '%s' kaydedildi (yetenekler: %s)", role_name, capabilities)

    @classmethod
    def get(cls, role_name: str) -> AgentSpec | None:
        """Return a registered agent spec without re-normalizing canonical classes.

        Built-in role class normalization belongs to registration/sync paths so
        tests and bootstrap callers that explicitly provide a canonical module
        cache keep their deterministic class identity. ``get`` only repairs
        stale export aliases for built-in specs whose class still points at a
        non-canonical module.
        """
        spec = cls._registry.get(role_name)
        contract = _builtin_contract_by_role(role_name)
        if (
            spec is not None
            and spec.is_builtin
            and contract is not None
            and spec.agent_class is not None
            and spec.agent_class.__module__ != contract.module_name
        ):
            role_exports = sys.modules.get("agent.roles")
            exported_cls = (
                getattr(role_exports, contract.class_name, None) if role_exports else None
            )
            if isinstance(exported_cls, type) and spec.agent_class is not exported_cls:
                spec.agent_class = exported_cls
        return spec

    @classmethod
    def find_by_capability(cls, capability: str) -> list[AgentSpec]:
        matches: list[AgentSpec] = []
        for spec in cls._registry.values():
            capabilities = getattr(spec, "capabilities", []) or []
            if capability in capabilities:
                matches.append(spec)
        return matches

    @classmethod
    def list_all(cls) -> list[AgentSpec]:
        return list(cls._registry.values())

    @classmethod
    def health_summary(cls) -> dict[str, Any]:
        """Return a structured health view for built-in role catalog wiring."""
        return get_agent_catalog_health()

    @classmethod
    def create(cls, role_name: str, **kwargs: Any) -> object:
        spec = cls.get(role_name)
        if spec is None:
            available = list(cls._registry.keys())
            raise KeyError(
                f"'{role_name}' ajan tipi kayıt defterinde bulunamadı. Mevcut tipler: {available}"
            )
        cfg = kwargs.get("cfg")
        _assert_runtime_side_effect_allowed(spec, cfg=cfg)

        if spec.agent_class is not None:
            return spec.agent_class(**kwargs)

        factory = getattr(spec, "_agent_factory", None)
        if callable(factory):
            return factory(**kwargs)

        raise TypeError(f"'{role_name}' için agent_class veya _agent_factory tanımlı değil.")

    @classmethod
    def unregister(cls, role_name: str) -> bool:
        if role_name in cls._registry:
            del cls._registry[role_name]
            return True
        return False


def _sync_builtin_contract_registry(module_cache: dict[str, Any] | None = None) -> None:
    """Synchronize built-in specs with canonical module classes.

    Built-in modules may already be present in ``sys.modules`` when this bootstrap
    runs, so their decorators will not necessarily execute again. Re-reading each
    successfully imported contract class and registering it programmatically keeps
    ``AgentCatalog`` aligned with the canonical module object and the
    ``agent.roles`` package exports, even after test stubs or reloads.
    """
    role_exports = sys.modules.get("agent.roles")
    for contract in BUILTIN_ROLE_CONTRACTS:
        if contract.module_name in _BUILTIN_IMPORT_FAILURES:
            continue
        try:
            module = (module_cache or {}).get(contract.module_name)
            if module is None:
                module = importlib.import_module(contract.module_name)
            agent_cls = getattr(module, contract.class_name)
        except Exception as exc:  # pragma: no cover - defensive fallback for optional deps/stubs
            logger.debug(
                "Builtin role canonical sync'i atlandı: %s",
                contract.module_name,
                exc_info=True,
            )
            if contract.module_name not in _BUILTIN_IMPORT_FAILURES:
                _BUILTIN_IMPORT_FAILURES[contract.module_name] = _format_import_failure(exc)
            continue

        if not isinstance(agent_cls, type):
            logger.debug(
                "Builtin role canonical sync'i atlandı; sembol bir sınıf değil: %s.%s",
                contract.module_name,
                contract.class_name,
            )
            continue

        if role_exports is not None:
            setattr(role_exports, contract.class_name, agent_cls)
        AgentCatalog.register_type(
            role_name=contract.role_name,
            agent_class=agent_cls,
            capabilities=list(contract.capabilities),
            is_builtin=True,
        )


def _has_builtin_specs() -> bool:
    """Katalogda en az bir yerleşik ajan kaydı olup olmadığını döndürür."""
    return any(spec.is_builtin for spec in AgentCatalog.list_all())


def _format_import_failure(exc: Exception) -> str:
    """Import hatasını checklist/operasyon logları için kısa ve okunabilir biçimlendirir."""
    if isinstance(exc, ModuleNotFoundError):
        missing_name = getattr(exc, "name", "") or str(exc)
        return f"eksik Python modülü: {missing_name}"
    return f"{type(exc).__name__}: {exc}"


def get_agent_catalog_health() -> dict[str, Any]:
    """Expose AgentCatalog readiness for health endpoints and diagnostics."""
    specs_by_role = {spec.role_name: spec for spec in AgentCatalog.list_all()}
    registered_builtin_roles = sorted(
        spec.role_name for spec in specs_by_role.values() if spec.is_builtin
    )
    missing_builtin_roles: list[str] = []
    non_builtin_builtin_roles: list[str] = []
    capability_mismatches: dict[str, dict[str, list[str]]] = {}

    for contract in BUILTIN_ROLE_CONTRACTS:
        spec = specs_by_role.get(contract.role_name)
        if spec is None:
            missing_builtin_roles.append(contract.role_name)
            continue
        if not spec.is_builtin:
            non_builtin_builtin_roles.append(contract.role_name)
        expected_capabilities = set(contract.capabilities)
        actual_capabilities = set(spec.capabilities or [])
        missing_capabilities = sorted(expected_capabilities - actual_capabilities)
        if missing_capabilities:
            capability_mismatches[contract.role_name] = {"missing": missing_capabilities}

    degraded = bool(
        _BUILTIN_IMPORT_FAILURES
        or missing_builtin_roles
        or non_builtin_builtin_roles
        or capability_mismatches
    )
    return {
        "status": "degraded" if degraded else "healthy",
        "degraded": degraded,
        "expected_builtin_roles": list(EXPECTED_BUILTIN_ROLE_NAMES),
        "registered_builtin_roles": registered_builtin_roles,
        "missing_builtin_roles": missing_builtin_roles,
        "non_builtin_builtin_roles": non_builtin_builtin_roles,
        "import_failures": dict(_BUILTIN_IMPORT_FAILURES),
        "capability_mismatches": capability_mismatches,
    }


def _clear_builtin_import_failures() -> None:
    """Reset recorded built-in import failures (primarily for deterministic tests)."""
    _BUILTIN_IMPORT_FAILURES.clear()


def _import_builtin_roles() -> None:
    """Yerleşik ajan modüllerini içe aktararak dekoratör tabanlı kaydı tetikler."""
    import importlib

    # Keep this literal list in sync with ``agent.roles.__init__`` so lightweight
    # AST contract tests can detect drift without importing optional role dependencies.
    builtin_role_modules = (
        "agent.roles.coder_agent",
        "agent.roles.researcher_agent",
        "agent.roles.reviewer_agent",
        "agent.roles.poyraz_agent",
        "agent.roles.coverage_agent",
        "agent.roles.qa_agent",
    )
    if set(builtin_role_modules) != set(BUILTIN_ROLE_MODULES):
        logger.warning(
            "Yerleşik ajan rol kontratı ile import listesi uyumsuz: %s != %s",
            builtin_role_modules,
            BUILTIN_ROLE_MODULES,
        )

    failures: list[tuple[str, Exception]] = []
    imported_modules: dict[str, Any] = {}
    _clear_builtin_import_failures()

    for module_name in builtin_role_modules:
        try:
            imported_modules[module_name] = importlib.import_module(module_name)
        except Exception as exc:
            failures.append((module_name, exc))
            _BUILTIN_IMPORT_FAILURES[module_name] = _format_import_failure(exc)
            logger.debug("Builtin role import'u atlandı: %s", module_name, exc_info=True)

    _sync_builtin_contract_registry(imported_modules)

    if failures and not _has_builtin_specs():
        first_module, first_exc = failures[0]
        logger.warning(
            "Yerleşik ajan rolleri yüklenemedi; AgentCatalog.list_all() boş dönebilir. "
            "Proje bağımlılıklarını uv ile senkronize edin (örn. `uv sync --all-extras`). "
            "İlk hata: %s (%s).",
            _format_import_failure(first_exc),
            first_module,
        )


_import_builtin_roles()

# Geriye dönük uyumluluk
AgentRegistry = AgentCatalog
