"""Tests for cost-aware model routing settings resolution."""

from core.config_cost_routing import load_cost_routing_settings

_ALL_KEYS = (
    "ENABLE_COST_ROUTING",
    "COST_ROUTING_COMPLEXITY_THRESHOLD",
    "COST_ROUTING_LOCAL_PROVIDER",
    "COST_ROUTING_LOCAL_MODEL",
    "COST_ROUTING_CLOUD_PROVIDER",
    "COST_ROUTING_CLOUD_MODEL",
    "COST_ROUTING_DAILY_BUDGET_USD",
    "COST_ROUTING_TOKEN_THRESHOLD",
    "COST_ROUTING_SHARED_BUDGET_DB_PATH",
    "COST_ROUTING_REDIS_BUDGET_URL",
    "COST_ROUTING_REDIS_BUDGET_NAMESPACE",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_cost_routing_settings()

    assert settings.enable_cost_routing is False
    assert settings.cost_routing_complexity_threshold == 0.55
    assert settings.cost_routing_local_provider == "ollama"
    assert settings.cost_routing_local_model == ""
    assert settings.cost_routing_cloud_provider == ""
    assert settings.cost_routing_cloud_model == ""
    assert settings.cost_routing_daily_budget_usd == 1.0
    assert settings.cost_routing_token_threshold == 0
    assert settings.cost_routing_shared_budget_db_path == ""
    assert settings.cost_routing_redis_budget_url == ""
    assert settings.cost_routing_redis_budget_namespace == "sidar"


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("ENABLE_COST_ROUTING", "true")
    monkeypatch.setenv("COST_ROUTING_COMPLEXITY_THRESHOLD", "0.7")
    monkeypatch.setenv("COST_ROUTING_LOCAL_PROVIDER", "lmstudio")
    monkeypatch.setenv("COST_ROUTING_LOCAL_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setenv("COST_ROUTING_CLOUD_PROVIDER", "anthropic")
    monkeypatch.setenv("COST_ROUTING_CLOUD_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("COST_ROUTING_DAILY_BUDGET_USD", "5.5")
    monkeypatch.setenv("COST_ROUTING_TOKEN_THRESHOLD", "4096")
    monkeypatch.setenv("COST_ROUTING_SHARED_BUDGET_DB_PATH", "/data/budget.db")
    monkeypatch.setenv("COST_ROUTING_REDIS_BUDGET_URL", "redis://localhost:6379/2")
    monkeypatch.setenv("COST_ROUTING_REDIS_BUDGET_NAMESPACE", "custom-ns")

    settings = load_cost_routing_settings()

    assert settings.enable_cost_routing is True
    assert settings.cost_routing_complexity_threshold == 0.7
    assert settings.cost_routing_local_provider == "lmstudio"
    assert settings.cost_routing_local_model == "qwen2.5-coder:7b"
    assert settings.cost_routing_cloud_provider == "anthropic"
    assert settings.cost_routing_cloud_model == "claude-sonnet-5"
    assert settings.cost_routing_daily_budget_usd == 5.5
    assert settings.cost_routing_token_threshold == 4096
    assert settings.cost_routing_shared_budget_db_path == "/data/budget.db"
    assert settings.cost_routing_redis_budget_url == "redis://localhost:6379/2"
    assert settings.cost_routing_redis_budget_namespace == "custom-ns"


def test_malformed_numeric_envs_fall_back_to_defaults(monkeypatch):
    """Non-numeric threshold/budget/token env values fall back to their defaults."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("COST_ROUTING_COMPLEXITY_THRESHOLD", "not-a-float")
    monkeypatch.setenv("COST_ROUTING_DAILY_BUDGET_USD", "also-not-a-float")
    monkeypatch.setenv("COST_ROUTING_TOKEN_THRESHOLD", "not-an-int")

    settings = load_cost_routing_settings()

    assert settings.cost_routing_complexity_threshold == 0.55
    assert settings.cost_routing_daily_budget_usd == 1.0
    assert settings.cost_routing_token_threshold == 0
