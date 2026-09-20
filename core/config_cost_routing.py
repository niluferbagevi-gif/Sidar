"""Cost-aware model routing settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_float_env, get_int_env


@dataclass(frozen=True)
class CostRoutingSettings:
    """Complexity-threshold/budget-based local-vs-cloud model routing settings."""

    enable_cost_routing: bool
    cost_routing_complexity_threshold: float
    cost_routing_local_provider: str
    cost_routing_local_model: str
    cost_routing_cloud_provider: str
    cost_routing_cloud_model: str
    cost_routing_daily_budget_usd: float
    cost_routing_token_threshold: int
    cost_routing_shared_budget_db_path: str
    cost_routing_redis_budget_url: str
    cost_routing_redis_budget_namespace: str


def load_cost_routing_settings() -> CostRoutingSettings:
    """Load cost-aware model routing settings from environment variables."""
    return CostRoutingSettings(
        enable_cost_routing=get_bool_env("ENABLE_COST_ROUTING", False),
        cost_routing_complexity_threshold=get_float_env("COST_ROUTING_COMPLEXITY_THRESHOLD", 0.55),
        cost_routing_local_provider=os.getenv("COST_ROUTING_LOCAL_PROVIDER", "ollama"),
        cost_routing_local_model=os.getenv("COST_ROUTING_LOCAL_MODEL", ""),
        cost_routing_cloud_provider=os.getenv("COST_ROUTING_CLOUD_PROVIDER", ""),
        cost_routing_cloud_model=os.getenv("COST_ROUTING_CLOUD_MODEL", ""),
        cost_routing_daily_budget_usd=get_float_env("COST_ROUTING_DAILY_BUDGET_USD", 1.0),
        cost_routing_token_threshold=get_int_env("COST_ROUTING_TOKEN_THRESHOLD", 0),
        cost_routing_shared_budget_db_path=os.getenv("COST_ROUTING_SHARED_BUDGET_DB_PATH", ""),
        cost_routing_redis_budget_url=os.getenv("COST_ROUTING_REDIS_BUDGET_URL", ""),
        cost_routing_redis_budget_namespace=os.getenv(
            "COST_ROUTING_REDIS_BUDGET_NAMESPACE", "sidar"
        ),
    )
