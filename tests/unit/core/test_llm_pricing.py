from __future__ import annotations

from core import llm_client, llm_metrics, llm_pricing


def test_llm_client_reads_the_shared_routing_pricing_table() -> None:
    """Regression for two unsynchronized pricing catalogs found via code review.

    core.llm_client.MODEL_COSTS_PER_TOKEN_USD must be the exact same object
    as core.llm_pricing.MODEL_COSTS_PER_TOKEN_USD (not a copy) so the two
    can never drift apart again — editing the shared table is the only way
    to change either consumer's data.
    """
    assert llm_client.MODEL_COSTS_PER_TOKEN_USD is llm_pricing.MODEL_COSTS_PER_TOKEN_USD


def test_llm_metrics_reads_the_shared_dashboard_pricing_table() -> None:
    assert llm_metrics._MODEL_PRICES_PER_1M is llm_pricing.MODEL_PRICES_PER_1M_TOKENS_USD


def test_pricing_tables_are_intentionally_different_shapes() -> None:
    """Lock in that the two tables keep their distinct, documented shapes.

    They are not meant to hold identical values (see core/llm_pricing.py's
    module docstring): one is a coarse blended $/token routing estimate, the
    other a real prompt/completion-per-1M-token dashboard estimate. This
    guards against a future "helpful" merge attempt silently collapsing them
    into one inconsistent shape.
    """
    assert all(isinstance(v, float) for v in llm_pricing.MODEL_COSTS_PER_TOKEN_USD.values())
    assert all(
        isinstance(v, dict) and {"prompt", "completion"} <= v.keys()
        for v in llm_pricing.MODEL_PRICES_PER_1M_TOKENS_USD.values()
    )
