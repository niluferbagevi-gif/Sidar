"""Tests for continuous-learning bundle settings resolution."""

from core.config_continuous_learning import load_continuous_learning_settings

_ALL_KEYS = (
    "ENABLE_CONTINUOUS_LEARNING",
    "CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES",
    "CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES",
    "CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS",
    "CONTINUOUS_LEARNING_COOLDOWN_SECONDS",
    "CONTINUOUS_LEARNING_OUTPUT_DIR",
    "CONTINUOUS_LEARNING_SFT_FORMAT",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_continuous_learning_settings()

    assert settings.enable_continuous_learning is False
    assert settings.continuous_learning_min_sft_examples == 20
    assert settings.continuous_learning_min_preference_examples == 10
    assert settings.continuous_learning_max_pending_signals == 5000
    assert settings.continuous_learning_cooldown_seconds == 3600
    assert settings.continuous_learning_output_dir == "data/continuous_learning"
    assert settings.continuous_learning_sft_format == "alpaca"


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("ENABLE_CONTINUOUS_LEARNING", "true")
    monkeypatch.setenv("CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES", "50")
    monkeypatch.setenv("CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES", "25")
    monkeypatch.setenv("CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS", "10000")
    monkeypatch.setenv("CONTINUOUS_LEARNING_COOLDOWN_SECONDS", "7200")
    monkeypatch.setenv("CONTINUOUS_LEARNING_OUTPUT_DIR", "/data/cl")
    monkeypatch.setenv("CONTINUOUS_LEARNING_SFT_FORMAT", "sharegpt")

    settings = load_continuous_learning_settings()

    assert settings.enable_continuous_learning is True
    assert settings.continuous_learning_min_sft_examples == 50
    assert settings.continuous_learning_min_preference_examples == 25
    assert settings.continuous_learning_max_pending_signals == 10000
    assert settings.continuous_learning_cooldown_seconds == 7200
    assert settings.continuous_learning_output_dir == "/data/cl"
    assert settings.continuous_learning_sft_format == "sharegpt"


def test_malformed_integer_envs_fall_back_to_defaults(monkeypatch):
    """Non-integer count/threshold env values fall back to their defaults."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES", "not-an-int")
    monkeypatch.setenv("CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES", "not-an-int")
    monkeypatch.setenv("CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS", "not-an-int")
    monkeypatch.setenv("CONTINUOUS_LEARNING_COOLDOWN_SECONDS", "not-an-int")

    settings = load_continuous_learning_settings()

    assert settings.continuous_learning_min_sft_examples == 20
    assert settings.continuous_learning_min_preference_examples == 10
    assert settings.continuous_learning_max_pending_signals == 5000
    assert settings.continuous_learning_cooldown_seconds == 3600
