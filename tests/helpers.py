"""Shared non-fixture test helpers.

These utilities are intentionally kept outside ``conftest.py`` so test modules
can import them directly without relying on pytest's conftest loading behavior.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator
from unittest.mock import MagicMock


async def collect_async_chunks(gen: AsyncGenerator[Any, None]) -> list[Any]:
    """Collect all chunks from an async generator into a list."""
    return [chunk async for chunk in gen]


def make_test_config(**overrides: Any) -> MagicMock:
    """Create a configurable MagicMock test config object."""
    base = {
        "AI_PROVIDER": "ollama",
        "LLM_MAX_RETRIES": 2,
        "LLM_RETRY_BASE_DELAY": 0.01,
        "LLM_RETRY_MAX_DELAY": 0.02,
        "ENABLE_SEMANTIC_CACHE": True,
        "SEMANTIC_CACHE_THRESHOLD": 0.9,
        "SEMANTIC_CACHE_TTL": 60,
        "SEMANTIC_CACHE_MAX_ITEMS": 2,
        "COST_ROUTING_ENABLED": True,
        "COST_ROUTING_THRESHOLD": 0.05,
        "COST_ROUTING_DAILY_BUDGET_USD": 1.0,
        "COST_ROUTING_SHARED_BUDGET_DB_PATH": "",
        "COST_ROUTING_REDIS_BUDGET_URL": "",
        "ENTITY_MEMORY_TTL": 3600,
        "MAX_MEMORY_ENTITIES": 100,
        "REDIS_URL": "redis://localhost:6379/0",
        "REDIS_MAX_CONNECTIONS": 5,
    }
    base.update(overrides)

    try:
        from config import Config as AppConfig
    except ImportError:
        AppConfig = None

    if AppConfig is not None and all(
        hasattr(AppConfig, attr) for attr in ("initialize_directories", "validate_critical_settings")
    ):
        known_attrs = set(dir(AppConfig))
        # Test override'larında AppConfig üzerinde henüz bulunmayan yeni/deneysel
        # flag'ler gelebilir (örn. v5.x modül bayrakları). Böyle bir durumda katı
        # spec kullanımı AttributeError üreteceği için esnek moda düş.
        if all(key in known_attrs for key in base):
            mock_cfg = MagicMock(spec_set=AppConfig)
        else:
            mock_cfg = MagicMock()
    else:
        # Bazı testler geçici stub Config sınıfları enjekte ediyor olabilir.
        # Bu durumda katı spec, ortak fixture kurulumunda AttributeError üretir.
        mock_cfg = MagicMock()
    for key, value in base.items():
        setattr(mock_cfg, key, value)

    mock_cfg.initialize_directories.return_value = True
    mock_cfg.validate_critical_settings.return_value = True

    return mock_cfg
