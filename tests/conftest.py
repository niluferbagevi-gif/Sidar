import importlib
import pathlib as _pl
from pathlib import Path
import sys

import pytest

_PROJECT_ROOT = _pl.Path(__file__).parent.parent


def _ensure_config_contract() -> None:
    """Testlerde kullanılan config stub'larını ortak bir minimum arayüze tamamlar."""
    cfg_mod = sys.modules.get("config")
    if not cfg_mod:
        return

    cfg_cls = getattr(cfg_mod, "Config", None)
    if cfg_cls is None:
        return

    defaults = {
        "AI_PROVIDER": "ollama",
        "ACCESS_LEVEL": "full",
        "WEB_HOST": "0.0.0.0",
        "WEB_PORT": 7860,
        "BASE_DIR": ".",
    }
    for key, value in defaults.items():
        if not hasattr(cfg_cls, key):
            setattr(cfg_cls, key, value)

    if not hasattr(cfg_cls, "initialize_directories"):
        setattr(cfg_cls, "initialize_directories", staticmethod(lambda: True))

    if not hasattr(cfg_mod, "get_bool_env"):
        setattr(cfg_mod, "get_bool_env", lambda _key, default=False: default)

    if not hasattr(cfg_mod, "_is_wsl2"):
        setattr(cfg_mod, "_is_wsl2", lambda: False)


_ensure_config_contract()

# managers paketini erken yükle; conftest save/restore döngüsünde kaybolmasını önle.
try:
    import managers as _managers_pkg  # noqa: F401
except Exception:
    pass


@pytest.fixture
def httpx_mock_router(respx_mock):
    """HTTPX çağrılarını standart fixture üzerinden mocklamak için yardımcı alias."""
    return respx_mock


# pytest-asyncio >= 0.21+ ile session kapsamlı event loop pytest.ini üzerinden
# `asyncio_default_fixture_loop_scope = session` ayarıyla sağlanır.
# Özel event_loop fixture override'ı artık gerekli değildir ve deprecated'dır.
@pytest.fixture(autouse=True)
def _restore_critical_modules_between_tests():
    """Bazı testlerin sys.modules üzerinde bıraktığı stub modülleri test sonunda geri al."""

    def _reload_real_config_module() -> None:
        """config modülünü gerçek dosyadan yeniden yükle (stub sızıntısını engelle)."""
        cfg = sys.modules.get("config")
        try:
            if cfg is None:
                importlib.import_module("config")
                return
            cfg_file = getattr(cfg, "__file__", "")
            # Stub modüllerde __file__ olmaz; gerçek modül için reload, stub için fresh import.
            if cfg_file and Path(cfg_file).name == "config.py":
                importlib.reload(cfg)
            else:
                sys.modules.pop("config", None)
                importlib.import_module("config")
        except Exception:
            # Bazı testler config import'unu bilinçli olarak kırabilir; fixture testleri engellemesin.
            pass

    _reload_real_config_module()
    _ensure_config_contract()
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
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
