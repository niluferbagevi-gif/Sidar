"""Tests for LoRA/QLoRA fine-tuning settings resolution."""

from core.config_lora_training import load_lora_training_settings

_ALL_KEYS = (
    "ENABLE_LORA_TRAINING",
    "LORA_BASE_MODEL",
    "LORA_RANK",
    "LORA_ALPHA",
    "LORA_DROPOUT",
    "LORA_EPOCHS",
    "LORA_BATCH_SIZE",
    "LORA_USE_4BIT",
    "LORA_OUTPUT_DIR",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_lora_training_settings()

    assert settings.enable_lora_training is False
    assert settings.lora_base_model == ""
    assert settings.lora_rank == 8
    assert settings.lora_alpha == 16
    assert settings.lora_dropout == 0.05
    assert settings.lora_epochs == 3
    assert settings.lora_batch_size == 4
    assert settings.lora_use_4bit is True
    assert settings.lora_output_dir == "data/lora_adapters"


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("ENABLE_LORA_TRAINING", "true")
    monkeypatch.setenv("LORA_BASE_MODEL", "meta-llama/Llama-3-8B")
    monkeypatch.setenv("LORA_RANK", "16")
    monkeypatch.setenv("LORA_ALPHA", "32")
    monkeypatch.setenv("LORA_DROPOUT", "0.1")
    monkeypatch.setenv("LORA_EPOCHS", "5")
    monkeypatch.setenv("LORA_BATCH_SIZE", "8")
    monkeypatch.setenv("LORA_USE_4BIT", "false")
    monkeypatch.setenv("LORA_OUTPUT_DIR", "/data/adapters")

    settings = load_lora_training_settings()

    assert settings.enable_lora_training is True
    assert settings.lora_base_model == "meta-llama/Llama-3-8B"
    assert settings.lora_rank == 16
    assert settings.lora_alpha == 32
    assert settings.lora_dropout == 0.1
    assert settings.lora_epochs == 5
    assert settings.lora_batch_size == 8
    assert settings.lora_use_4bit is False
    assert settings.lora_output_dir == "/data/adapters"


def test_malformed_numeric_envs_fall_back_to_defaults(monkeypatch):
    """Non-numeric rank/alpha/dropout/epochs/batch_size env values fall back to defaults."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("LORA_RANK", "not-an-int")
    monkeypatch.setenv("LORA_ALPHA", "not-an-int")
    monkeypatch.setenv("LORA_DROPOUT", "not-a-float")
    monkeypatch.setenv("LORA_EPOCHS", "not-an-int")
    monkeypatch.setenv("LORA_BATCH_SIZE", "not-an-int")

    settings = load_lora_training_settings()

    assert settings.lora_rank == 8
    assert settings.lora_alpha == 16
    assert settings.lora_dropout == 0.05
    assert settings.lora_epochs == 3
    assert settings.lora_batch_size == 4
