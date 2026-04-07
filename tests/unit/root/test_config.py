import config


def test_get_bool_env_truthy_and_default(monkeypatch):
    monkeypatch.setenv("FLAG_A", " yes ")
    monkeypatch.setenv("FLAG_B", "0")
    monkeypatch.delenv("FLAG_C", raising=False)

    assert config.get_bool_env("FLAG_A", False) is True
    assert config.get_bool_env("FLAG_B", True) is False
    assert config.get_bool_env("FLAG_C", True) is True


def test_get_int_float_and_list_env_parsing(monkeypatch):
    monkeypatch.setenv("INT_OK", "42")
    monkeypatch.setenv("INT_BAD", "abc")
    monkeypatch.setenv("FLOAT_OK", "3.14")
    monkeypatch.setenv("FLOAT_BAD", "-")
    monkeypatch.setenv("LIST_VAL", " a, b ,, c ")
    monkeypatch.delenv("LIST_EMPTY", raising=False)

    assert config.get_int_env("INT_OK", 7) == 42
    assert config.get_int_env("INT_BAD", 7) == 7
    assert config.get_float_env("FLOAT_OK", 1.2) == 3.14
    assert config.get_float_env("FLOAT_BAD", 1.2) == 1.2
    assert config.get_list_env("LIST_VAL", []) == ["a", "b", "c"]
    assert config.get_list_env("LIST_EMPTY", ["fallback"]) == ["fallback"]


def test_set_provider_mode_maps_and_rejects_invalid(monkeypatch):
    original = config.Config.AI_PROVIDER
    config.Config.AI_PROVIDER = "ollama"

    config.Config.set_provider_mode("online")
    assert config.Config.AI_PROVIDER == "gemini"

    config.Config.set_provider_mode("local")
    assert config.Config.AI_PROVIDER == "ollama"

    config.Config.set_provider_mode("invalid-provider")
    assert config.Config.AI_PROVIDER == "ollama"

    config.Config.AI_PROVIDER = original


def test_ensure_hardware_info_loaded_cpu_only(monkeypatch):
    monkeypatch.setattr(config.Config, "_hardware_loaded", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "x")
    monkeypatch.setattr(config.Config, "GPU_COUNT", 99)
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "x")
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "x")

    config.Config._ensure_hardware_info_loaded()

    assert config.Config._hardware_loaded is True
    assert config.Config.USE_GPU is False
    assert config.Config.GPU_INFO == "Devre Dışı / CPU Modu"
    assert config.Config.GPU_COUNT == 0
    assert config.Config.CUDA_VERSION == "N/A"
    assert config.Config.DRIVER_VERSION == "N/A"
    assert config.Config.CPU_COUNT >= 1


def test_get_system_info_sanitizes_sensitive_fields(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full")
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "CPU")
    monkeypatch.setattr(config.Config, "GPU_COUNT", 0)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", 0)
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "N/A")
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "N/A")
    monkeypatch.setattr(config.Config, "MULTI_GPU", False)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", False)
    monkeypatch.setattr(config.Config, "GPU_MEMORY_FRACTION", 0.8)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.8)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.2)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 4)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False)
    monkeypatch.setattr(config.Config, "WEB_PORT", 7860)
    monkeypatch.setattr(config.Config, "WEB_GPU_PORT", 7861)
    monkeypatch.setattr(config.Config, "HF_HUB_OFFLINE", False)
    monkeypatch.setattr(config.Config, "RATE_LIMIT_WINDOW", 60)
    monkeypatch.setattr(config.Config, "RATE_LIMIT_CHAT", 20)
    monkeypatch.setattr(config.Config, "RATE_LIMIT_MUTATIONS", 60)
    monkeypatch.setattr(config.Config, "RATE_LIMIT_GET_IO", 30)
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", False)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://jaeger:4317")
    monkeypatch.setattr(config.Config, "ENABLE_SEMANTIC_CACHE", False)
    monkeypatch.setattr(config.Config, "SEMANTIC_CACHE_THRESHOLD", 0.95)
    monkeypatch.setattr(config.Config, "SEMANTIC_CACHE_TTL", 3600)
    monkeypatch.setattr(config.Config, "SEMANTIC_CACHE_MAX_ITEMS", 500)

    info = config.Config.get_system_info()

    assert info["provider"] == "ollama"
    assert info["gpu_enabled"] is False
    assert "REDIS_URL" not in info


def test_get_config_returns_singleton(monkeypatch):
    monkeypatch.setattr(config, "_config_instance", None)
    first = config.get_config()
    second = config.get_config()

    assert first is second
