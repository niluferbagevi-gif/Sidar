from __future__ import annotations

import time

from agent.core.circuit_breaker import SwarmCircuitBreaker


def test_swarm_circuit_breaker_opens_and_resets() -> None:
    breaker = SwarmCircuitBreaker(max_failures=2, reset_after_seconds=60)

    assert breaker.is_open("coder") is False
    breaker.record_failure("coder")
    assert breaker.is_open("coder") is False
    breaker.record_failure("coder")
    assert breaker.is_open("coder") is True

    breaker.record_success("coder")
    assert breaker.is_open("coder") is False


def test_swarm_circuit_breaker_allows_after_reset_window(monkeypatch) -> None:
    now = 1_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    breaker = SwarmCircuitBreaker(max_failures=1, reset_after_seconds=5)
    breaker.record_failure("qa")
    assert breaker.is_open("qa") is True

    monkeypatch.setattr(time, "time", lambda: now + 6)
    assert breaker.is_open("qa") is False
