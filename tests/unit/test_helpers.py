from __future__ import annotations

import builtins
import sys
from types import ModuleType

import pytest

from tests.helpers import collect_async_chunks, make_test_config


async def _agen():
    for item in ("a", "b", "c"):
        yield item


@pytest.mark.asyncio
async def test_collect_async_chunks_collects_all_items() -> None:
    assert await collect_async_chunks(_agen()) == ["a", "b", "c"]


def test_make_test_config_uses_spec_set_with_full_app_config(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_config = ModuleType("config")

    class FullConfig:
        AI_PROVIDER = "ollama"
        LLM_MAX_RETRIES = 1
        LLM_RETRY_BASE_DELAY = 0.1
        LLM_RETRY_MAX_DELAY = 0.2
        ENABLE_SEMANTIC_CACHE = True
        SEMANTIC_CACHE_THRESHOLD = 0.9
        SEMANTIC_CACHE_TTL = 60
        SEMANTIC_CACHE_MAX_ITEMS = 2
        COST_ROUTING_ENABLED = True
        COST_ROUTING_THRESHOLD = 0.05
        COST_ROUTING_DAILY_BUDGET_USD = 1.0
        COST_ROUTING_SHARED_BUDGET_DB_PATH = ""
        COST_ROUTING_REDIS_BUDGET_URL = ""
        ENTITY_MEMORY_TTL = 3600
        MAX_MEMORY_ENTITIES = 100
        REDIS_URL = "redis://localhost:6379/0"
        REDIS_MAX_CONNECTIONS = 5

        def initialize_directories(self):
            return True

        def validate_critical_settings(self):
            return True

    fake_config.Config = FullConfig
    monkeypatch.setitem(sys.modules, "config", fake_config)

    cfg = make_test_config()
    assert FullConfig().initialize_directories() is True
    assert FullConfig().validate_critical_settings() is True

    with pytest.raises(AttributeError):
        cfg.NON_EXISTENT = 1


def test_make_test_config_falls_back_to_flexible_mock_when_override_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_config = ModuleType("config")

    class MinimalConfig:
        AI_PROVIDER = "ollama"

        def initialize_directories(self):
            return True

        def validate_critical_settings(self):
            return True

    fake_config.Config = MinimalConfig
    monkeypatch.setitem(sys.modules, "config", fake_config)

    cfg = make_test_config(NEW_FLAG=True)
    assert MinimalConfig().initialize_directories() is True
    assert MinimalConfig().validate_critical_settings() is True

    cfg.ANOTHER_DYNAMIC = "ok"
    assert cfg.NEW_FLAG is True
    assert cfg.ANOTHER_DYNAMIC == "ok"


def test_make_test_config_falls_back_when_config_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def raising_import(name, *args, **kwargs):
        if name == "config":
            raise ImportError("forced import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", raising_import)

    cfg = make_test_config()
    assert builtins.__import__("math").__name__ == "math"

    cfg.DYNAMIC_FIELD = 123
    assert cfg.DYNAMIC_FIELD == 123


def test_make_test_config_falls_back_when_required_methods_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_config = ModuleType("config")

    class MissingMethodsConfig:
        AI_PROVIDER = "ollama"

    fake_config.Config = MissingMethodsConfig
    monkeypatch.setitem(sys.modules, "config", fake_config)

    cfg = make_test_config()

    cfg.FLEX = "enabled"
    assert cfg.FLEX == "enabled"
