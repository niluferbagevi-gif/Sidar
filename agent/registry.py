"""
Sidar Agent Registry — Çalışma Zamanı Ajan Keşfi ve Eklenti Pazaryeri.

Kayıtlı ajan türlerini, yeteneklerini ve meta verilerini yönetir.
Yeni uzman ajanlar `@AgentRegistry.register(...)` dekoratörü ile
veya `AgentRegistry.register_type(...)` metoduyla eklenir.

Kullanım:
    # Bir ajan tipini kaydet (dekoratör ile)
    @AgentRegistry.register(capabilities=["code_review"])
    class ReviewerAgent(BaseAgent): ...

    # Ajan oluştur
    agent = AgentRegistry.create("reviewer", cfg=cfg)

    # Yetenek bazında arama
    matches = AgentRegistry.find_by_capability("code_review")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    """Kayıtlı bir ajan tipinin meta verisi."""

    role_name: str
    agent_class: Optional[Type[Any]] = None
    capabilities: List[str] = field(default_factory=list)
    description: str = ""
    version: str = "1.0.0"
    is_builtin: bool = True  # False = eklenti (plugin) kaydı


class AgentRegistry:
    """
    Singleton benzeri sınıf-tabanlı ajan kayıt defteri.
    Tüm kayıtlar sınıf değişkeninde tutulur — import sırasında otomatik doldurulur.
    """

    _registry: Dict[str, AgentSpec] = {}

    # ── Kayıt API'si ────────────────────────────────────────────────────

    @classmethod
    def register(
        cls,
        *,
        capabilities: Optional[List[str]] = None,
        description: str = "",
        version: str = "1.0.0",
        is_builtin: bool = False,
    ) -> Callable[[Type], Type]:
        """
        Ajan sınıfını kayıt defterine ekleyen sınıf dekoratörü.

        @AgentRegistry.register(capabilities=["code_generation", "file_io"])
        class CoderAgent(BaseAgent): ...
        """
        def _decorator(agent_cls: Type) -> Type:
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
        agent_class: Type,
        capabilities: Optional[List[str]] = None,
        description: str = "",
        version: str = "1.0.0",
        is_builtin: bool = True,
    ) -> None:
        """Ajan tipini programatik olarak kayıt et."""
        spec = AgentSpec(
            role_name=role_name,
            agent_class=agent_class,
            capabilities=capabilities or [],
            description=description,
            version=version,
            is_builtin=is_builtin,
        )
        cls._registry[role_name] = spec
        logger.debug("AgentRegistry: '%s' kaydedildi (yetenekler: %s)", role_name, capabilities)

    # ── Sorgulama API'si ────────────────────────────────────────────────

    @classmethod
    def get(cls, role_name: str) -> Optional[AgentSpec]:
        """Rol adına göre spec döndür; bulunamazsa None."""
        return cls._registry.get(role_name)

    @classmethod
    def find_by_capability(cls, capability: str) -> List[AgentSpec]:
        """Belirtilen yeteneğe sahip tüm ajan speclerini döndür."""
        return [
            spec for spec in cls._registry.values()
            if capability in spec.capabilities
        ]

    @classmethod
    def list_all(cls) -> List[AgentSpec]:
        """Kayıtlı tüm ajan speclerini döndür."""
        return list(cls._registry.values())

    @classmethod
    def create(cls, role_name: str, **kwargs) -> object:
        """
        Kayıtlı ajan tipinden örnek oluştur.
        kwargs agent_class.__init__'e iletilir (genellikle cfg=).
        """
        spec = cls.get(role_name)
        if spec is None:
            available = list(cls._registry.keys())
            raise KeyError(
                f"'{role_name}' ajan tipi kayıt defterinde bulunamadı. "
                f"Mevcut tipler: {available}"
            )
        if spec.agent_class is not None:
            return spec.agent_class(**kwargs)

        factory = getattr(spec, "_agent_factory", None)
        if callable(factory):
            return factory(**kwargs)

        raise TypeError(
            f"'{role_name}' için agent_class veya _agent_factory tanımlı değil."
        )

    @classmethod
    def unregister(cls, role_name: str) -> bool:
        """Ajan tipini kayıt defterinden kaldır (test/eklenti kaldırma için). True = bulundu."""
        if role_name in cls._registry:
            del cls._registry[role_name]
            return True
        return False


# ── Yerleşik ajanları kaydet (import sırasında yüklenir) ─────────────────

def _register_builtin_agents() -> None:
    """Yerleşik ajan rollerini kayıt defterine ekler (geç import ile döngüsel bağımlılık önlenir)."""
    try:
        from agent.roles.coder_agent import CoderAgent
        AgentRegistry.register_type(
            role_name="coder",
            agent_class=CoderAgent,
            capabilities=["code_generation", "file_io", "shell_execution", "code_review"],
            description="Kod yazma, düzenleme, yama uygulama ve çalıştırma uzmanı",
            is_builtin=True,
        )
    except ImportError:
        pass

    try:
        from agent.roles.researcher_agent import ResearcherAgent
        AgentRegistry.register_type(
            role_name="researcher",
            agent_class=ResearcherAgent,
            capabilities=["web_search", "rag_search", "summarization"],
            description="Web ve RAG tabanlı araştırma ve bilgi sentezi uzmanı",
            is_builtin=True,
        )
    except ImportError:
        pass

    try:
        from agent.roles.reviewer_agent import ReviewerAgent
        AgentRegistry.register_type(
            role_name="reviewer",
            agent_class=ReviewerAgent,
            capabilities=["code_review", "security_audit", "quality_check"],
            description="Kod kalitesi, güvenlik ve mimari inceleme uzmanı",
            is_builtin=True,
        )
    except ImportError:
        pass

    try:
        from agent.roles.poyraz_agent import PoyrazAgent
        AgentRegistry.register_type(
            role_name="poyraz",
            agent_class=PoyrazAgent,
            capabilities=["marketing_strategy", "seo_analysis", "campaign_copy", "audience_ops"],
            description="Pazarlama stratejisi, SEO ve kampanya operasyonu uzmanı",
            is_builtin=True,
        )
    except ImportError:
        pass

    try:
        from agent.roles.coverage_agent import CoverageAgent
        AgentRegistry.register_type(
            role_name="coverage",
            agent_class=CoverageAgent,
            capabilities=["coverage_analysis", "pytest_output_analysis", "autonomous_test_generation"],
            description="Pytest çıktılarını okuyup coverage açığı için test adayı üreten uzman ajan",
            is_builtin=True,
        )
    except ImportError:
        pass

    try:
        from agent.roles.qa_agent import QAAgent
        AgentRegistry.register_type(
            role_name="qa",
            agent_class=QAAgent,
            capabilities=["test_generation", "ci_remediation"],
            description="Coverage analizi ve pytest tabanlı test üretimi uzmanı",
            is_builtin=True,
        )
    except ImportError:
        pass


_register_builtin_agents()
