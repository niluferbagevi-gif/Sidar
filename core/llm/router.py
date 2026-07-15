"""Cost-aware routing adapter for the LLM facade."""

from __future__ import annotations

from typing import Any

from core.router import CostAwareRouter, record_routing_cost


class LLMRoutingService:
    """Wrap CostAwareRouter so the facade does not own router construction details."""

    def __init__(self, config: Any) -> None:
        self._router = CostAwareRouter(config)

    def select(
        self, messages: list[dict[str, str]], provider: str, model: str | None
    ) -> tuple[str, str | None]:
        """Select provider/model for a chat request."""

        return self._router.select(messages, provider, model)

    @staticmethod
    def record_cost(cost_usd: float) -> None:
        """Record estimated routing cost."""

        record_routing_cost(cost_usd)
