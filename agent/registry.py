"""
Sidar Agent Catalog — Çalışma Zamanı Ajan Keşfi ve Eklenti Pazaryeri.

Kayıtlı ajan türlerini, yeteneklerini ve meta verilerini yönetir.
Yeni uzman ajanlar `@AgentCatalog.register(...)` dekoratörü ile
veya `AgentCatalog.register_type(...)` metoduyla eklenir.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
    ) -> None:
        spec = AgentSpec(
            role_name=role_name,
            agent_class=agent_class,
            capabilities=capabilities or [],
            description=description,
            version=version,
            is_builtin=is_builtin,
        )
        cls._registry[role_name] = spec
        logger.debug("AgentCatalog: '%s' kaydedildi (yetenekler: %s)", role_name, capabilities)

    @classmethod
    def get(cls, role_name: str) -> AgentSpec | None:
        return cls._registry.get(role_name)

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
    def create(cls, role_name: str, **kwargs: Any) -> object:
        spec = cls.get(role_name)
        if spec is None:
            available = list(cls._registry.keys())
            raise KeyError(
                f"'{role_name}' ajan tipi kayıt defterinde bulunamadı. Mevcut tipler: {available}"
            )
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


def _import_builtin_roles() -> None:
    """Yerleşik ajan modüllerini içe aktararak dekoratör tabanlı kaydı tetikler."""
    import importlib

    for module_name in (
        "agent.roles.coder_agent",
        "agent.roles.researcher_agent",
        "agent.roles.reviewer_agent",
        "agent.roles.poyraz_agent",
        "agent.roles.coverage_agent",
        "agent.roles.qa_agent",
    ):
        try:
            importlib.import_module(module_name)
        except Exception:
            logger.debug("Builtin role import'u atlandı: %s", module_name, exc_info=True)


_import_builtin_roles()

# Geriye dönük uyumluluk
AgentRegistry = AgentCatalog
