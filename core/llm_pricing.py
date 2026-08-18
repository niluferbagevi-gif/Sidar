"""Single source of truth for LLM model pricing data used across the codebase.

Historically ``core.llm_client`` (cost-aware routing) and ``core.llm_metrics``
(cost dashboard/budget tracking) each carried their own independently
hardcoded pricing table for the same models, and had already drifted — e.g.
``gpt-4o-mini`` was priced at a blended $2.00/1M tokens in ``llm_client`` but
$0.15 prompt / $0.60 completion per 1M tokens in ``llm_metrics`` (a code
review flagged this). The two tables serve genuinely different purposes and
are NOT simply the same number in two shapes:

- ``MODEL_COSTS_PER_TOKEN_USD``: a single blended $/token used as a coarse
  pre-flight cost estimate for *routing* decisions (cost-aware model
  selection, daily/total budget gating) before a request is even sent,
  keyed by bare model name with prefix matching. Consumed by
  ``core.llm_client._resolve_cost_per_token_usd``.
- ``MODEL_PRICES_PER_1M_TOKENS_USD``: separate prompt/completion $ per 1M
  tokens for *post-hoc* cost estimation shown on the usage dashboard, keyed
  by ``"provider:model"``. Consumed by
  ``core.llm_metrics.LLMMetricsCollector.estimate_cost_usd``.

Consolidating them into literally identical numeric values was evaluated and
rejected: ``MODEL_COSTS_PER_TOKEN_USD["gpt-4o-mini"] == 2e-6`` is asserted by
an existing test
(``test_resolve_cost_per_token_usd_prefers_model_map_and_known_defaults``) as
a known routing value, and there is no way to verify from this codebase
alone whether that number is a deliberate conservative safety margin or a
stale mistake — silently changing it would change real routing/budget-gating
behavior without any way to validate correctness. Instead, both tables are
collected here, values unchanged, so there is exactly one place to look (and,
going forward, to update together) instead of two, with their relationship
documented instead of guessed at.
"""

from __future__ import annotations

# Blended $/token, keyed by bare model name (prefix-matched). Used only for a
# coarse pre-flight cost-aware ROUTING estimate — NOT a billing source of
# truth. See MODEL_PRICES_PER_1M_TOKENS_USD below for the more precise
# prompt/completion split used for actual cost display.
MODEL_COSTS_PER_TOKEN_USD: dict[str, float] = {
    "gpt-4o": 5e-6,
    "gpt-4o-mini": 2e-6,
    "claude-3-5-sonnet": 3e-6,
    "claude-3-5-sonnet-latest": 3e-6,
    "gemini-1.5-pro": 3.5e-6,
    "gemini-1.5-flash": 7.5e-7,
}

# Approximate prompt/completion $ per 1M tokens, keyed by "provider:model".
# Used for post-hoc cost estimation on the usage dashboard — dashboard-trend
# purposes only, not a billing source of truth. Deliberately not the same
# shape or values as MODEL_COSTS_PER_TOKEN_USD above; see module docstring.
MODEL_PRICES_PER_1M_TOKENS_USD: dict[str, dict[str, float]] = {
    "openai:gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "openai:gpt-4o": {"prompt": 5.00, "completion": 15.00},
    "anthropic:claude-3-5-sonnet-latest": {"prompt": 3.00, "completion": 15.00},
    "anthropic:claude-3-5-haiku-latest": {"prompt": 0.80, "completion": 4.00},
}
