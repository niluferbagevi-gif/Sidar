from types import SimpleNamespace

from core.router import CostAwareRouter, QueryComplexityAnalyzer, record_routing_cost


def _cfg(**overrides):
    base = {
        "ENABLE_COST_ROUTING": True,
        "COST_ROUTING_COMPLEXITY_THRESHOLD": 0.55,
        "COST_ROUTING_LOCAL_PROVIDER": "ollama",
        "COST_ROUTING_CLOUD_PROVIDER": "openai",
        "COST_ROUTING_DAILY_BUDGET_USD": 9999.0,
        "COST_ROUTING_LOCAL_MODEL": "qwen2.5-coder:7b",
        "COST_ROUTING_CLOUD_MODEL": "gpt-4o-mini",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_query_complexity_analyzer_scores_simple_vs_complex():
    analyzer = QueryComplexityAnalyzer()

    simple_score = analyzer.score([{"role": "user", "content": "what is python?"}])
    complex_score = analyzer.score(
        [
            {
                "role": "user",
                "content": (
                    "Analyze and compare algorithm complexity. "
                    "Please design pattern and refactor this code: ```python def f(x): return x ```"
                ),
            }
        ]
    )

    assert simple_score < complex_score
    assert 0.0 <= simple_score <= 1.0
    assert 0.0 <= complex_score <= 1.0


def test_router_returns_default_when_disabled():
    router = CostAwareRouter(_cfg(ENABLE_COST_ROUTING=False))

    provider, model = router.select([{"role": "user", "content": "hi"}], "anthropic", "claude-3-haiku")

    assert provider == "anthropic"
    assert model == "claude-3-haiku"


def test_router_prefers_local_for_simple_query():
    router = CostAwareRouter(_cfg())

    provider, model = router.select([{"role": "user", "content": "kısaca açıkla"}], "openai", "gpt-4o")

    assert provider == "ollama"
    assert model == "qwen2.5-coder:7b"


def test_router_uses_cloud_for_complex_query():
    router = CostAwareRouter(_cfg(COST_ROUTING_COMPLEXITY_THRESHOLD=0.2))

    provider, model = router.select(
        [
            {
                "role": "user",
                "content": "analyze compare optimize algorithm tradeoff design pattern in detail",
            }
        ],
        "ollama",
        "qwen",
    )

    assert provider == "openai"
    assert model == "gpt-4o-mini"


def test_router_falls_back_to_local_when_budget_exceeded():
    router = CostAwareRouter(_cfg(COST_ROUTING_DAILY_BUDGET_USD=0.0))
    record_routing_cost(1.0)

    provider, model = router.select(
        [{"role": "user", "content": "analyze compare optimize algorithm tradeoff"}],
        "openai",
        "gpt-4o",
    )

    assert provider == "ollama"
    assert model == "qwen2.5-coder:7b"
