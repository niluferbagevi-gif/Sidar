import pathlib as _pl
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# Not: Global third-party module stub injection intentionally avoided.
# Testler gerçek bağımlılıklarla çalışmalı; ihtiyaç duyulan mock'lar test bazında
# unittest.mock / monkeypatch ile sağlanmalıdır.

_PROJECT_ROOT = _pl.Path(__file__).parent.parent
# managers paketini erken yükle; conftest save/restore döngüsünde kaybolmasını önle.
try:
    import managers as _managers_pkg  # noqa: F401
except Exception:
    pass


def pytest_configure(config: pytest.Config) -> None:
    """Project-level marker registrations for directory-scoped test suites."""
    config.addinivalue_line("markers", "e2e: uçtan uca testler")
    config.addinivalue_line("markers", "integration: harici sistem entegrasyon testleri")

# pytest-asyncio >= 0.21+ ile session kapsamlı event loop pytest.ini üzerinden
# `asyncio_default_fixture_loop_scope = session` ayarıyla sağlanır.
# Özel event_loop fixture override'ı artık gerekli değildir ve deprecated'dır.

@pytest.fixture(autouse=True)
def _restore_critical_modules_between_tests(monkeypatch: pytest.MonkeyPatch):
    """Testler arasında kritik modül import mutasyonlarını geri al."""
    module_names = (
        "config",
        "managers",
        "managers.browser_manager",
        "managers.system_health",
        "managers.code_manager",
        "managers.github_manager",
        "managers.jira_manager",
        "managers.security",
        "managers.slack_manager",
        "managers.social_media_manager",
        "managers.teams_manager",
        "managers.todo_manager",
        "managers.web_search",
        "managers.package_info",
        "managers.youtube_manager",
        "core",
        "core.llm_metrics",
        "core.llm_client",
        "core.memory",
        "core.rag",
        "core.entity_memory",
        "core.ci_remediation",
        "core.db",
        "httpx",
        "fastapi",
        "starlette",
        "agent",
        "agent.core",
        "agent.core.contracts",
        "agent.core.memory_hub",
        "agent.core.registry",
        "agent.core.event_stream",
        "agent.core.supervisor",
        "agent.registry",
        "agent.definitions",
        "agent.swarm",
        "agent.base_agent",
        "agent.roles",
        "agent.roles.coder_agent",
        "agent.roles.researcher_agent",
        "agent.roles.reviewer_agent",
        "agent.roles.poyraz_agent",
        "agent.roles.qa_agent",
        "agent.roles.coverage_agent",
        "redis",
        "redis.asyncio",
        "redis.exceptions",
        "core.agent_metrics",
        "pydantic",
    )

    saved = {name: sys.modules.get(name) for name in module_names}
    with monkeypatch.context():
        yield

    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


@pytest.fixture(autouse=True)
def _cleanup_logging_handlers():
    """Teste sonra logging handler'larını kapat (ResourceWarning önlemek için)."""
    yield
    import logging
    import gc
    # Tüm handler'ları kapat
    for handler in logging.root.handlers[:]:
        try:
            handler.close()
            logging.root.removeHandler(handler)
        except Exception:
            pass
    # Tüm logger'ları temizle
    for logger_name in list(logging.Logger.manager.loggerDict):
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers[:]:
            try:
                handler.close()
                logger.removeHandler(handler)
            except Exception:
                pass
    # Garbage collection'ı force et
    gc.collect()


@pytest.fixture
def sqlite_test_db_url(tmp_path) -> str:
    """core.db testleri için geçici SQLite veritabanı URL'i."""
    db_file = Path(tmp_path) / "sidar_test.db"
    return f"sqlite+aiosqlite:///{db_file}"


@pytest.fixture
def stub_aws_plugin_dependencies():
    """AWS plugin testleri için ortak modül stub'ları."""
    # agent package stub
    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent")
        pkg.__path__ = [str(_PROJECT_ROOT / "agent")]
        pkg.__package__ = "agent"
        sys.modules["agent"] = pkg

    # agent.core stub
    if "agent.core" not in sys.modules:
        core = types.ModuleType("agent.core")
        core.__path__ = [str(_PROJECT_ROOT / "agent" / "core")]
        core.__package__ = "agent.core"
        sys.modules["agent.core"] = core
    else:
        core = sys.modules["agent.core"]
        if not hasattr(core, "__path__"):
            core.__path__ = [str(_PROJECT_ROOT / "agent" / "core")]

    # agent.core.contracts stub
    if "agent.core.contracts" not in sys.modules:
        contracts = types.ModuleType("agent.core.contracts")
        contracts.is_delegation_request = lambda _value: False
        contracts.DelegationRequest = type("DelegationRequest", (), {})
        contracts.TaskEnvelope = type("TaskEnvelope", (), {})
        contracts.TaskResult = type("TaskResult", (), {})
        sys.modules["agent.core.contracts"] = contracts

    # config stub
    if "config" not in sys.modules:
        cfg_mod = types.ModuleType("config")

        class _Config:
            AI_PROVIDER = "ollama"
            OLLAMA_MODEL = "qwen2.5-coder:7b"
            BASE_DIR = "/tmp/sidar_test"
            USE_GPU = False
            GPU_DEVICE = 0
            GPU_MIXED_PRECISION = False
            RAG_DIR = "/tmp/sidar_test/rag"
            RAG_TOP_K = 3
            RAG_CHUNK_SIZE = 1000
            RAG_CHUNK_OVERLAP = 200
            SLACK_WEBHOOK_URL = ""
            SLACK_DEFAULT_CHANNEL = "general"

        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    # core stubs
    if "core" not in sys.modules:
        sys.modules["core"] = types.ModuleType("core")

    llm_stub = types.ModuleType("core.llm_client")
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value="llm yanıtı")
    llm_stub.LLMClient = MagicMock(return_value=mock_llm)
    sys.modules["core.llm_client"] = llm_stub

    # agent.base_agent stub
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")

        class _BaseAgent:
            SYSTEM_PROMPT = "You are a specialist agent."

            def __init__(self, cfg=None, *, role_name="base", **_kwargs):
                self.cfg = cfg or sys.modules["config"].Config()
                self.role_name = role_name
                self.llm = MagicMock()
                self.llm.chat = AsyncMock(return_value="llm yanıtı")
                self.tools = {}

            def register_tool(self, name, fn):
                self.tools[name] = fn

            async def call_tool(self, name, arg):
                if name not in self.tools:
                    return f"[HATA] '{name}' aracı bu ajan için tanımlı değil."
                return await self.tools[name](arg)

            async def call_llm(self, _msgs, system_prompt=None, temperature=0.3, **_kwargs):
                return "llm yanıtı"

        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod

    # plugins package stub
    if "plugins" not in sys.modules:
        plugins_pkg = types.ModuleType("plugins")
        plugins_pkg.__path__ = [str(_PROJECT_ROOT / "plugins")]
        plugins_pkg.__package__ = "plugins"
        sys.modules["plugins"] = plugins_pkg
