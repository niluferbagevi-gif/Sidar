"""Circuit breakers for swarm/P2P coordination paths."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: float = 0.0


class SwarmCircuitBreaker:
    """Small failure-count circuit breaker for delegated swarm calls."""

    MAX_FAILURES = 3
    RESET_AFTER_SECONDS = 60

    def __init__(
        self, *, max_failures: int | None = None, reset_after_seconds: float | None = None
    ) -> None:
        self.max_failures = max(1, int(max_failures or self.MAX_FAILURES))
        self.reset_after_seconds = max(1.0, float(reset_after_seconds or self.RESET_AFTER_SECONDS))
        self._states: dict[str, _BreakerState] = {}

    def is_open(self, key: str) -> bool:
        """Return whether the circuit is currently open for ``key``."""
        state = self._states.get(str(key or "default"))
        if state is None or state.failures < self.max_failures:
            return False
        if time.time() - state.opened_at >= self.reset_after_seconds:
            self.reset(str(key or "default"))
            return False
        return True

    def record_success(self, key: str) -> None:
        """Close/reset the circuit after a successful delegated call."""
        self.reset(key)

    def record_failure(self, key: str) -> None:
        """Record one delegated-call failure and open the circuit at threshold."""
        normalized = str(key or "default")
        state = self._states.setdefault(normalized, _BreakerState())
        state.failures += 1
        if state.failures >= self.max_failures and state.opened_at <= 0:
            state.opened_at = time.time()

    def reset(self, key: str) -> None:
        """Forget breaker state for ``key``."""
        self._states.pop(str(key or "default"), None)
