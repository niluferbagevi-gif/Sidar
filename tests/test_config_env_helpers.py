from pathlib import Path


def test_get_bool_env_handles_empty_and_whitespace_values():
    src = Path("config.py").read_text(encoding="utf-8")
    assert "raw_val = os.getenv(key)" in src
    assert "if raw_val is None or not raw_val.strip():" in src
    assert "val = raw_val.strip().lower()" in src


def test_config_exposes_subtask_rate_limit_and_hf_fields():
    src = Path("config.py").read_text(encoding="utf-8")
    assert "SUBTASK_MAX_STEPS" in src
    assert "AUTO_HANDLE_TIMEOUT" in src
    assert "RATE_LIMIT_WINDOW" in src
    assert "RATE_LIMIT_CHAT" in src
    assert "RATE_LIMIT_MUTATIONS" in src
    assert "RATE_LIMIT_GET_IO" in src
    assert "HF_TOKEN" in src
    assert "HF_HUB_OFFLINE" in src
    assert "PACKAGE_INFO_CACHE_TTL" in src


def test_env_example_matches_ollama_timeout_default_and_new_limits():
    src = Path(".env.example").read_text(encoding="utf-8")
    assert "OLLAMA_TIMEOUT=30" in src
    assert "SUBTASK_MAX_STEPS=5" in src
    assert "RATE_LIMIT_WINDOW=60" in src
    assert "RATE_LIMIT_CHAT=20" in src
    assert "AUTO_HANDLE_TIMEOUT=12" in src
    assert "PACKAGE_INFO_CACHE_TTL=1800" in src