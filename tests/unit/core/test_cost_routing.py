from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.router import CostAwareRouter


def _cfg(**overrides: object) -> SimpleNamespace:
    base = {
        "ENABLE_COST_ROUTING": True,
        "COST_ROUTING_COMPLEXITY_THRESHOLD": 0.60,
        "COST_ROUTING_LOCAL_PROVIDER": "ollama",
        "COST_ROUTING_LOCAL_MODEL": "llama3",
        "COST_ROUTING_CLOUD_PROVIDER": "openai",
        "COST_ROUTING_CLOUD_MODEL": "gpt-4o",
        "COST_ROUTING_DAILY_BUDGET_USD": 10.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_cost_routing_threshold_prefers_local_for_simple_query() -> None:
    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.90))

    provider, model = router.select(
        [{"role": "user", "content": "kısaca açıkla"}],
        default_provider="openai",
        default_model="gpt-4o-mini",
    )

    assert (provider, model) == ("ollama", "llama3")


def test_cost_routing_threshold_prefers_cloud_for_complex_query() -> None:
    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.20))

    provider, model = router.select(
        [
            {
                "role": "user",
                "content": (
                    "Please analyze and compare algorithm complexity tradeoff and "
                    "design pattern choices with examples?"
                ),
            }
        ],
        default_provider="ollama",
        default_model="llama3",
    )

    assert (provider, model) == ("openai", "gpt-4o")


def test_cost_routing_fail_closed_when_cloud_provider_missing() -> None:
    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.10, COST_ROUTING_CLOUD_PROVIDER=""))

    provider, model = router.select(
        [{"role": "user", "content": "analyze algorithm tradeoff in detail?"}],
        default_provider="anthropic",
        default_model="claude-3-5-sonnet",
    )

    # Fail-closed: bulut provider konfigürasyonu yoksa varsayılan korunur.
    assert (provider, model) == ("anthropic", "claude-3-5-sonnet")


def test_cost_routing_budget_exceeded_forces_local(monkeypatch) -> None:
    from core import router as router_module

    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.0, COST_ROUTING_DAILY_BUDGET_USD=0.01))
    monkeypatch.setattr(router_module._budget_tracker, "exceeded", lambda _limit: True)

    provider, model = router.select(
        [{"role": "user", "content": "çok karmaşık analiz yap"}],
        default_provider="openai",
        default_model="gpt-4o",
    )

    assert (provider, model) == ("ollama", "llama3")


def test_cost_routing_disabled_keeps_defaults() -> None:
    router = CostAwareRouter(_cfg(ENABLE_COST_ROUTING=False))

    provider, model = router.select(
        [{"role": "user", "content": "herhangi bir metin"}],
        default_provider="openai",
        default_model="gpt-4o-mini",
    )

    assert (provider, model) == ("openai", "gpt-4o-mini")


@pytest.mark.parametrize("local_provider", ["", None])
def test_cost_routing_simple_query_keeps_defaults_when_local_provider_not_configured(local_provider) -> None:
    router = CostAwareRouter(
        _cfg(
            COST_ROUTING_COMPLEXITY_THRESHOLD=0.95,
            COST_ROUTING_LOCAL_PROVIDER=local_provider,
        )
    )

    provider, model = router.select(
        [{"role": "user", "content": "kısa cevap ver"}],
        default_provider="openai",
        default_model="gpt-4o-mini",
    )

    assert (provider, model) == ("openai", "gpt-4o-mini")
