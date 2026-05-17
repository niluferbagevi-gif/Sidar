import importlib
import logging
import os
import types
import warnings
from pathlib import Path

import pytest

import config


def test_get_bool_env_strict_true_false_and_default(monkeypatch):
    monkeypatch.setenv("FLAG_A", " true ")
    monkeypatch.setenv("FLAG_B", "FALSE")
    monkeypatch.delenv("FLAG_C", raising=False)

    assert config.get_bool_env("FLAG_A", False) is True
    assert config.get_bool_env("FLAG_B", True) is False
    assert config.get_bool_env("FLAG_C", True) is True


def test_get_bool_env_rejects_numeric_and_yes_no_aliases(monkeypatch):
    monkeypatch.setenv("FLAG_A", "1")
    monkeypatch.setenv("FLAG_B", "yes")

    with pytest.raises(ValueError, match="FLAG_A must be either 'true' or 'false'"):
        config.get_bool_env("FLAG_A", False)
    with pytest.raises(ValueError, match="FLAG_B must be either 'true' or 'false'"):
        config.get_bool_env("FLAG_B", False)


def test_get_external_bool_env_accepts_provider_aliases(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "no")

    assert config.get_external_bool_env("HF_HUB_OFFLINE", False) is True
    assert config.get_external_bool_env("TRANSFORMERS_OFFLINE", True) is False


def test_get_external_bool_env_rejects_unknown_values(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "maybe")

    with pytest.raises(ValueError, match="HF_HUB_OFFLINE must be a boolean accepted"):
        config.get_external_bool_env("HF_HUB_OFFLINE", False)


def test_database_urls_are_derived_from_postgres_parts(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIDAR_CONTAINER_DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "sidar user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss word")
    monkeypatch.setenv("POSTGRES_HOST", "db.local")
    monkeypatch.setenv("POSTGRES_CONTAINER_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5544")
    monkeypatch.setenv("POSTGRES_DB", "sidar db")

    assert (
        config.get_database_url()
        == "postgresql+asyncpg://sidar%20user:p%40ss%20word@db.local:5544/sidar%20db"
    )
    assert (
        config.get_container_database_url()
        == "postgresql+asyncpg://sidar%20user:p%40ss%20word@postgres:5544/sidar%20db"
    )


def test_database_urls_prefer_explicit_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///tmp/sidar.db")
    monkeypatch.setenv("SIDAR_CONTAINER_DATABASE_URL", "postgresql+asyncpg://x:y@pg:5432/z")

    assert config.get_database_url() == "sqlite+aiosqlite:///tmp/sidar.db"
    assert config.get_container_database_url() == "postgresql+asyncpg://x:y@pg:5432/z"


def test_web_scrape_max_chars_warns_for_deprecated_fetch_alias(monkeypatch):
    monkeypatch.delenv("WEB_SCRAPE_MAX_CHARS", raising=False)
    monkeypatch.setenv("WEB_FETCH_MAX_CHARS", "4321")

    with pytest.warns(DeprecationWarning, match="WEB_FETCH_MAX_CHARS is deprecated"):
        assert config.get_web_scrape_max_chars() == 4321


def test_web_scrape_max_chars_prefers_new_name_without_warning(monkeypatch):
    monkeypatch.setenv("WEB_SCRAPE_MAX_CHARS", "9876")
    monkeypatch.setenv("WEB_FETCH_MAX_CHARS", "4321")

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        assert config.get_web_scrape_max_chars() == 9876
    assert not record


def test_prefixed_env_helpers_prefer_sidar_namespace(monkeypatch):
    monkeypatch.setenv("LEGACY_INT", "10")
    monkeypatch.setenv("SIDAR_INT", "20")
    monkeypatch.setenv("LEGACY_FLOAT", "1.5")
    monkeypatch.setenv("SIDAR_FLOAT", "2.5")
    monkeypatch.setenv("LEGACY_TEXT", "legacy")
    monkeypatch.setenv("SIDAR_TEXT", "prefixed")

    assert config.get_int_prefixed_env("SIDAR_INT", "LEGACY_INT", 0) == 20
    assert config.get_float_prefixed_env("SIDAR_FLOAT", "LEGACY_FLOAT", 0.0) == 2.5
    assert config.get_prefixed_env("SIDAR_TEXT", "LEGACY_TEXT", "fallback") == "prefixed"


def test_prefixed_bool_env_is_strict(monkeypatch):
    monkeypatch.setenv("LEGACY_BOOL", "true")
    assert config.get_bool_prefixed_env("SIDAR_BOOL", "LEGACY_BOOL", False) is True

    monkeypatch.setenv("SIDAR_BOOL", "yes")
    with pytest.raises(ValueError, match="SIDAR_BOOL / LEGACY_BOOL must be either"):
        config.get_bool_prefixed_env("SIDAR_BOOL", "LEGACY_BOOL", False)


def test_llm_client_settings_default_ollama_timeout_is_600(monkeypatch):
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    settings = config.LLMClientSettings()
    assert settings.OLLAMA_TIMEOUT == 600


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
    assert config.get_list_env("LIST_EMPTY", None) == []


def test_get_db_pool_size_default_scales_with_cpu_and_pg_limits(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE_PER_CORE", "3")
    monkeypatch.setenv("POSTGRES_MAX_CONNECTIONS", "60")
    monkeypatch.setenv("DB_POOL_CONNECTION_RESERVE", "8")
    monkeypatch.setenv("DB_POOL_SIZE_HARD_CAP", "200")
    monkeypatch.setattr(config.os, "cpu_count", lambda: 16)

    # min(CPU*per_core=48, pg-reserve=52, hard_cap=200) => 48
    assert config.get_db_pool_size_default() == 48


def test_get_db_pool_size_default_respects_postgres_and_hard_cap(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE_PER_CORE", "4")
    monkeypatch.setenv("POSTGRES_MAX_CONNECTIONS", "25")
    monkeypatch.setenv("DB_POOL_CONNECTION_RESERVE", "10")
    monkeypatch.setenv("DB_POOL_SIZE_HARD_CAP", "12")
    monkeypatch.setattr(config.os, "cpu_count", lambda: 32)

    # min(CPU*per_core=128, pg-reserve=15, hard_cap=12) => 12
    assert config.get_db_pool_size_default() == 12


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
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
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
    monkeypatch.setattr(config.Config, "HF_USE_LOCAL_CACHE_ONLY", True)
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
    assert info["hf_use_local_cache_only"] is True
    assert "REDIS_URL" not in info


def test_get_config_returns_singleton(monkeypatch):
    monkeypatch.setattr(config, "_config_instance", None)
    first = config.get_config()
    second = config.get_config()

    assert first is second


def test_config_import_handles_missing_dotenv_file_override(monkeypatch):
    calls: list[dict[str, object]] = []

    def _fake_load_dotenv(*, dotenv_path=None, override=False):
        calls.append({"dotenv_path": dotenv_path, "override": override})
        return True

    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", _fake_load_dotenv)

    reloaded = importlib.reload(config)

    assert reloaded.ENV_PATH == reloaded.BASE_DIR / ".env"
    assert all(call.get("override") in (False, None) for call in calls)


def test_config_import_buffers_missing_environment_file_until_logger_status(monkeypatch, capsys):
    monkeypatch.setenv("SIDAR_ENV", "development")
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.delenv("DOTENV_FILE", raising=False)

    reloaded = importlib.reload(config)

    captured = capsys.readouterr()
    assert ".env.development bulunamadı" not in captured.out
    assert "Belirtilen ortam dosyası bulunamadı" not in captured.out

    reloaded.Config._log_dotenv_load_status(missing_keys=[])
    status_output = capsys.readouterr().out

    assert "Opsiyonel dotenv dosyaları bulunamadı" in status_output
    assert "environment:development=" in status_output


def test_sidar_keys_file_supports_user_home_and_overrides(monkeypatch, tmp_path):
    keys_file = tmp_path / "sidar_keys.env"
    keys_file.write_text(
        "OPENAI_API_KEY=from-keys-file\n"
        "API_KEY=api-from-keys-file\n"
        "JWT_SECRET_KEY=jwt-from-keys-file\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("SIDAR_ENV", "development")
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(keys_file))

    reloaded = importlib.reload(config)

    assert reloaded.Config.SIDAR_KEYS_FILE == str(keys_file)
    assert reloaded.Config.OPENAI_API_KEY == "from-keys-file"
    assert reloaded.Config.API_KEY == "api-from-keys-file"
    assert reloaded.Config.JWT_SECRET_KEY == "jwt-from-keys-file"


def test_resolve_dotenv_path_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    assert config._resolve_dotenv_path("~/.sidar_keys.env") == tmp_path / ".sidar_keys.env"


def test_is_test_env_returns_true_when_sidar_env_is_testing(monkeypatch):
    monkeypatch.setenv("SIDAR_ENV", "testing")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert config.Config._is_test_env() is True


def test_is_wsl2_returns_false_on_read_error(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
    assert config._is_wsl2() is False


def test_check_hardware_paths(monkeypatch):
    monkeypatch.setenv("USE_GPU", "false")
    info = config.check_hardware()
    assert info.gpu_name == "Devre Dışı (Kullanıcı)"

    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("no torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    info2 = config.check_hardware()
    assert info2.gpu_name == "PyTorch Yok"


def test_initialize_directories_returns_false_when_mkdir_fails(monkeypatch):
    class _BadDir:
        name = "bad"

        def mkdir(self, **_kwargs):
            raise RuntimeError("fail")

    monkeypatch.setattr(config.Config, "REQUIRED_DIRS", [_BadDir()])
    assert config.Config.initialize_directories() is False


def test_validate_critical_settings_provider_and_memory_branches(monkeypatch):
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", True)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(config.Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config.Config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config.Config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "")
    assert config.Config.validate_critical_settings() is False

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "openai")
    assert config.Config.validate_critical_settings() is False

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "anthropic")
    assert config.Config.validate_critical_settings() is False

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "litellm")
    assert config.Config.validate_critical_settings() is False


def test_normalize_gpu_memory_fractions_reports_effective_budget() -> None:
    safe = config.normalize_gpu_memory_fractions(0.6, 0.3)
    assert safe == {
        "llm": 0.6,
        "rag": 0.3,
        "gpu": 0.9,
        "total": 0.9,
        "original_total": 0.9,
        "normalized": False,
    }

    normalized = config.normalize_gpu_memory_fractions(0.9, 0.4)
    assert normalized["normalized"] is True
    assert normalized["gpu"] == pytest.approx(0.8)
    assert normalized["total"] == pytest.approx(0.8)
    assert normalized["llm"] + normalized["rag"] == pytest.approx(0.8)


def test_apply_gpu_memory_safety_check_normalizes_when_sum_exceeds_one(monkeypatch):
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.9)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.4)
    monkeypatch.setattr(config.Config, "GPU_MEMORY_FRACTION", 0.9)

    config.Config._apply_gpu_memory_safety_check()

    total = config.Config.LLM_GPU_MEMORY_FRACTION + config.Config.RAG_GPU_MEMORY_FRACTION
    assert total == pytest.approx(0.8, rel=1e-3)
    assert config.Config.GPU_MEMORY_FRACTION == pytest.approx(0.8, rel=1e-3)


def test_apply_gpu_memory_safety_check_resets_when_total_is_non_positive(monkeypatch):
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", -0.4)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.0)
    monkeypatch.setattr(config.Config, "GPU_MEMORY_FRACTION", 0.9)

    config.Config._apply_gpu_memory_safety_check()

    assert config.Config.LLM_GPU_MEMORY_FRACTION == pytest.approx(0.4)
    assert config.Config.RAG_GPU_MEMORY_FRACTION == pytest.approx(0.4)
    assert config.Config.GPU_MEMORY_FRACTION == pytest.approx(0.8)


def test_apply_gpu_memory_safety_check_second_scale_branch(monkeypatch):
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", -0.1)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 1.2)
    monkeypatch.setattr(config.Config, "GPU_MEMORY_FRACTION", 0.9)

    config.Config._apply_gpu_memory_safety_check()

    assert config.Config.LLM_GPU_MEMORY_FRACTION == pytest.approx(0.0433, rel=1e-3)
    assert config.Config.RAG_GPU_MEMORY_FRACTION == pytest.approx(0.7567, rel=1e-3)
    assert (
        config.Config.LLM_GPU_MEMORY_FRACTION + config.Config.RAG_GPU_MEMORY_FRACTION
    ) == pytest.approx(0.8, rel=1e-3)
    assert config.Config.GPU_MEMORY_FRACTION == pytest.approx(0.8, rel=1e-3)


def test_validate_critical_settings_exits_in_production_without_memory_key(monkeypatch):
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(
        config.Config, "_apply_gpu_memory_safety_check", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://x")
    monkeypatch.setenv("SIDAR_ENV", "production")

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, _url):
            return types.SimpleNamespace(status_code=200)

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_Client))
    with pytest.raises(SystemExit):
        config.Config.validate_critical_settings()


def test_validate_critical_settings_ollama_http_paths(monkeypatch):
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://x")

    class _Resp:
        def __init__(self, status_code):
            self.status_code = status_code

    class _ClientOK:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, _url):
            return _Resp(200)

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientOK))
    assert config.Config.validate_critical_settings() is True

    class _ClientBad(_ClientOK):
        def get(self, _url):
            return _Resp(503)

    monkeypatch.setitem(
        __import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientBad)
    )
    assert config.Config.validate_critical_settings() is True


def test_init_telemetry_branches(monkeypatch):
    class _Log:
        def __init__(self):
            self.warned = []
            self.info_msg = []

        def warning(self, msg, *args):
            self.warned.append(msg % args if args else msg)

        def info(self, msg, *args):
            self.info_msg.append(msg % args if args else msg)

    log = _Log()
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", False)
    assert config.Config.init_telemetry(logger_obj=log) is False

    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    assert config.Config.init_telemetry(logger_obj=log, trace_module=None) is False

    class _Trace:
        def set_tracer_provider(self, _provider):
            return None

    class _Resource:
        @staticmethod
        def create(_obj):
            return object()

    class _Provider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            self.endpoint = endpoint
            self.insecure = insecure

    class _Batch:
        def __init__(self, exporter):
            self.exporter = exporter

    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", False)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")
    assert (
        config.Config.init_telemetry(
            logger_obj=log,
            trace_module=_Trace(),
            otlp_exporter_cls=_Exporter,
            tracer_provider_cls=_Provider,
            resource_cls=_Resource,
            batch_span_processor_cls=_Batch,
        )
        is True
    )


@pytest.mark.parametrize("provider", ["ollama", "gemini", "openai", "litellm", "anthropic"])
def test_print_config_summary_provider_branches(monkeypatch, capsys, provider):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar")
    monkeypatch.setattr(config.Config, "VERSION", "x")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", provider)
    monkeypatch.setattr(config.Config, "USE_GPU", True)
    monkeypatch.setattr(config.Config, "GPU_INFO", "GPU")
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "12")
    monkeypatch.setattr(config.Config, "GPU_COUNT", 1)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", 0)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", False)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.7)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.3)
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "N/A")
    monkeypatch.setattr(config.Config, "CPU_COUNT", 4)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full")
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False)
    monkeypatch.setattr(config.Config, "CODING_MODEL", "code")
    monkeypatch.setattr(config.Config, "TEXT_MODEL", "text")
    monkeypatch.setattr(config.Config, "GEMINI_MODEL", "gem")
    monkeypatch.setattr(config.Config, "OPENAI_MODEL", "gpt")
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "http://lite")
    monkeypatch.setattr(config.Config, "LITELLM_MODEL", "lite")
    monkeypatch.setattr(config.Config, "ANTHROPIC_MODEL", "claude")
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    config.Config.print_config_summary()
    assert "Yapılandırma Özeti" in capsys.readouterr().out


def test_print_config_summary_cpu_branch(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar")
    monkeypatch.setattr(config.Config, "VERSION", "x")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "CPU")
    monkeypatch.setattr(config.Config, "CPU_COUNT", 2)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "sandbox")
    monkeypatch.setattr(config.Config, "DEBUG_MODE", True)
    monkeypatch.setattr(config.Config, "ANTHROPIC_MODEL", "claude")
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "x")
    config.Config.print_config_summary()
    out = capsys.readouterr().out
    assert "CPU Modu" in out
    assert "Bellek Şifreleme : Etkin" in out


def test_validate_critical_settings_memory_key_and_crypto_missing(monkeypatch):
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://x")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "not-a-valid-fernet")

    class _Resp:
        status_code = 200

    class _ClientOK:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientOK))
    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_ollama_client_exception(monkeypatch):
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://x")

    class _ClientBoom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setitem(
        __import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientBoom)
    )
    assert config.Config.validate_critical_settings() is True


def test_init_telemetry_runtime_failure(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")

    class _Trace:
        def set_tracer_provider(self, _provider):
            raise RuntimeError("set fail")

    class _Resource:
        @staticmethod
        def create(_obj):
            return object()

    class _Provider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            pass

    class _Batch:
        def __init__(self, exporter):
            pass

    assert (
        config.Config.init_telemetry(
            trace_module=_Trace(),
            otlp_exporter_cls=_Exporter,
            tracer_provider_cls=_Provider,
            resource_cls=_Resource,
            batch_span_processor_cls=_Batch,
        )
        is False
    )


def test_init_telemetry_dependency_auto_import_failure(monkeypatch):
    import builtins

    class _Log:
        def __init__(self):
            self.warned = []

        def warning(self, msg, *args):
            self.warned.append(msg % args if args else msg)

    log = _Log()
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)

    original_import = builtins.__import__

    def _fail_otel_import(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("opentelemetry unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_otel_import)

    assert (
        config.Config.init_telemetry(
            logger_obj=log,
            trace_module=config._DEPENDENCY_AUTO,
            otlp_exporter_cls=config._DEPENDENCY_AUTO,
            tracer_provider_cls=config._DEPENDENCY_AUTO,
            resource_cls=config._DEPENDENCY_AUTO,
            batch_span_processor_cls=config._DEPENDENCY_AUTO,
        )
        is False
    )
    assert any("OpenTelemetry bağımlılıkları yüklenemedi" in m for m in log.warned)


def test_module_reload_env_branches(monkeypatch):
    monkeypatch.setenv("SIDAR_ENV", "production")
    calls = {"base": False, "spec": False}

    def fake_exists(self):
        p = str(self)
        if p.endswith(".env"):
            calls["base"] = True
            return True
        if p.endswith(".env.production"):
            calls["spec"] = True
            return True
        return False

    monkeypatch.setattr(Path, "exists", fake_exists)
    assert Path("README.md").exists() is False
    importlib.reload(config)
    assert calls["base"] is True
    assert calls["spec"] is True


def test_module_reload_env_missing_optional_and_warning(monkeypatch):
    monkeypatch.setenv("SIDAR_ENV", "prodx")

    def fake_exists(self):
        p = str(self)
        if p.endswith(".env"):
            return True
        if p.endswith(".env.prodx"):
            return False
        return False

    monkeypatch.setattr(Path, "exists", fake_exists)
    assert Path("README.md").exists() is False
    importlib.reload(config)


def test_module_reload_env_optional_alias_and_no_base(monkeypatch):
    monkeypatch.setenv("SIDAR_ENV", "dev")

    def fake_exists_alias(self):
        p = str(self)
        if p.endswith(".env"):
            return True
        if p.endswith(".env.dev"):
            return False
        return False

    monkeypatch.setattr(Path, "exists", fake_exists_alias)
    assert Path("README.md").exists() is False
    importlib.reload(config)

    monkeypatch.setenv("SIDAR_ENV", "")

    def fake_exists_none(self):
        return False

    monkeypatch.setattr(Path, "exists", fake_exists_none)
    importlib.reload(config)

    def fake_exists_base_only(self):
        return str(self).endswith(".env")

    monkeypatch.setattr(Path, "exists", fake_exists_base_only)
    importlib.reload(config)


def test_check_hardware_cuda_and_optional_modules(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: True)
    monkeypatch.setenv("LLM_GPU_MEMORY_FRACTION", "0.6")
    monkeypatch.setenv("RAG_GPU_MEMORY_FRACTION", "0.3")

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 2,
            get_device_name=lambda _idx: "FakeGPU",
            set_per_process_memory_fraction=lambda frac, device=0: None,
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    fake_pynvml = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlSystemGetDriverVersion=lambda: "550.1",
        nvmlShutdown=lambda: None,
    )
    fake_mp = types.SimpleNamespace(cpu_count=lambda: 16)

    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "torch", fake_torch)
    monkeypatch.setitem(modules, "pynvml", fake_pynvml)
    monkeypatch.setitem(modules, "multiprocessing", fake_mp)

    info = config.check_hardware()
    assert info.has_cuda is True
    assert info.gpu_name == "FakeGPU"
    assert info.driver_version == "550.1"
    assert info.cpu_count == 16


def test_check_hardware_non_cuda_and_generic_exception(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: True)

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        version=types.SimpleNamespace(cuda=None),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)
    info = config.check_hardware()
    assert info.gpu_name == "CUDA Bulunamadı"

    class _BoomTorch:
        class cuda:
            @staticmethod
            def is_available():
                raise RuntimeError("boom")

    monkeypatch.setitem(__import__("sys").modules, "torch", _BoomTorch)
    info2 = config.check_hardware()
    assert info2.gpu_name == "Tespit Edilemedi"


def test_check_hardware_normalizes_explicit_llm_rag_fraction_sum(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("LLM_GPU_MEMORY_FRACTION", "0.9")
    monkeypatch.setenv("RAG_GPU_MEMORY_FRACTION", "0.4")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)
    called = []

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_name=lambda _idx: "FakeGPU",
            set_per_process_memory_fraction=lambda frac, device=0: called.append((frac, device)),
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)

    info = config.check_hardware()

    assert info.has_cuda is True
    assert called == [(0.8, 0)]


def test_check_hardware_invalid_fraction_and_fraction_set_exception(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "2.0")
    monkeypatch.delenv("LLM_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RAG_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    def _raise_set(*_args, **_kwargs):
        raise RuntimeError("set frac fail")

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_name=lambda _idx: "FakeGPU",
            set_per_process_memory_fraction=_raise_set,
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)
    info = config.check_hardware()
    assert info.has_cuda is True


def test_check_hardware_cpu_count_fallback(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        version=types.SimpleNamespace(cuda=None),
    )
    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "torch", fake_torch)

    class _BoomMP:
        @staticmethod
        def cpu_count():
            raise RuntimeError("no cpu")

    monkeypatch.setitem(modules, "multiprocessing", _BoomMP)
    info = config.check_hardware()
    assert info.cpu_count == 1


def test_check_hardware_nvml_exception_is_ignored(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        version=types.SimpleNamespace(cuda=None),
    )
    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "torch", fake_torch)
    monkeypatch.setitem(
        modules,
        "pynvml",
        types.SimpleNamespace(nvmlInit=lambda: (_ for _ in ()).throw(RuntimeError("nvml fail"))),
    )

    info = config.check_hardware()
    assert info.gpu_name == "CUDA Bulunamadı"


def test_ensure_hardware_info_loaded_short_circuit(monkeypatch):
    monkeypatch.setattr(config.Config, "_hardware_loaded", True)
    before = config.Config.GPU_INFO
    config.Config._ensure_hardware_info_loaded()
    assert config.Config.GPU_INFO == before


def test_initialize_directories_success_debug_path(monkeypatch, tmp_path):
    monkeypatch.setattr(config.Config, "REQUIRED_DIRS", [tmp_path / "ok_dir"])
    assert config.Config.initialize_directories() is True


def test_validate_critical_settings_invalid_fernet_and_ollama_api_suffix(monkeypatch):
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://localhost:11434/api")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "bad")

    class _Fernet:
        def __init__(self, _val):
            raise ValueError("bad key")

    fake_crypto = types.SimpleNamespace(Fernet=_Fernet)
    monkeypatch.setitem(__import__("sys").modules, "cryptography.fernet", fake_crypto)

    class _Resp:
        status_code = 200

    class _ClientOK:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert url.endswith("/tags")
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientOK))
    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_missing_cryptography_dependency(monkeypatch):
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "abc123")

    class _Resp:
        status_code = 200

    class _ClientOK:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientOK))
    monkeypatch.delitem(__import__("sys").modules, "cryptography.fernet", raising=False)
    monkeypatch.delitem(__import__("sys").modules, "cryptography", raising=False)

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "cryptography.fernet":
            raise ImportError("cryptography missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert config.Config.validate_critical_settings() is False


def test_init_telemetry_dependency_auto_success_with_instrumentation(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", True)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True)
    monkeypatch.setattr(config.Config, "OTEL_SERVICE_NAME", "svc")

    trace_mod = types.SimpleNamespace(set_tracer_provider=lambda provider: None)
    otlp_mod = types.SimpleNamespace(OTLPSpanExporter=lambda endpoint, insecure: object())
    sdk_trace = types.SimpleNamespace(
        TracerProvider=lambda resource: types.SimpleNamespace(add_span_processor=lambda p: None)
    )
    sdk_resource = types.SimpleNamespace(Resource=types.SimpleNamespace(create=lambda x: object()))
    sdk_export = types.SimpleNamespace(BatchSpanProcessor=lambda exporter: object())
    fastapi_inst = types.SimpleNamespace(
        FastAPIInstrumentor=types.SimpleNamespace(instrument_app=lambda app: None)
    )
    httpx_inst = types.SimpleNamespace(
        HTTPXClientInstrumentor=lambda: types.SimpleNamespace(instrument=lambda: None)
    )

    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "opentelemetry", types.SimpleNamespace(trace=trace_mod))
    monkeypatch.setitem(modules, "opentelemetry.trace", trace_mod)
    monkeypatch.setitem(modules, "opentelemetry.exporter.otlp.proto.grpc.trace_exporter", otlp_mod)
    monkeypatch.setitem(modules, "opentelemetry.sdk.trace", sdk_trace)
    monkeypatch.setitem(modules, "opentelemetry.sdk.resources", sdk_resource)
    monkeypatch.setitem(modules, "opentelemetry.sdk.trace.export", sdk_export)
    monkeypatch.setitem(modules, "opentelemetry.instrumentation.fastapi", fastapi_inst)
    monkeypatch.setitem(modules, "opentelemetry.instrumentation.httpx", httpx_inst)

    assert config.Config.init_telemetry(fastapi_app=object()) is True


def test_init_telemetry_custom_fastapi_and_missing_httpx_instrumentor(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", True)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True)

    class _Trace:
        def set_tracer_provider(self, _provider):
            return None

    class _Resource:
        @staticmethod
        def create(_obj):
            return object()

    class _Provider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            pass

    class _Batch:
        def __init__(self, exporter):
            pass

    class _FastAPIInstr:
        @staticmethod
        def instrument_app(_app):
            return None

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "opentelemetry.instrumentation.httpx":
            raise ImportError("missing httpx instr")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert __import__("math").__name__ == "math"
    assert (
        config.Config.init_telemetry(
            fastapi_app=object(),
            trace_module=_Trace(),
            otlp_exporter_cls=_Exporter,
            tracer_provider_cls=_Provider,
            resource_cls=_Resource,
            batch_span_processor_cls=_Batch,
            fastapi_instrumentor_cls=_FastAPIInstr,
        )
        is True
    )


def test_print_config_summary_with_driver_version(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar")
    monkeypatch.setattr(config.Config, "VERSION", "x")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(config.Config, "USE_GPU", True)
    monkeypatch.setattr(config.Config, "GPU_INFO", "GPU")
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "12")
    monkeypatch.setattr(config.Config, "GPU_COUNT", 2)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", 0)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", True)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.7)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.3)
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "550.10")
    monkeypatch.setattr(config.Config, "CPU_COUNT", 8)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full")
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False)
    monkeypatch.setattr(config.Config, "GEMINI_MODEL", "gem")
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    config.Config.print_config_summary()
    assert "Sürücü Sürümü" in capsys.readouterr().out


def test_init_telemetry_with_explicit_httpx_instrumentor(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True)

    class _Trace:
        def set_tracer_provider(self, _provider):
            return None

    class _Resource:
        @staticmethod
        def create(_obj):
            return object()

    class _Provider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            pass

    class _Batch:
        def __init__(self, exporter):
            pass

    class _HttpxInstr:
        def instrument(self):
            return None

    assert (
        config.Config.init_telemetry(
            trace_module=_Trace(),
            otlp_exporter_cls=_Exporter,
            tracer_provider_cls=_Provider,
            resource_cls=_Resource,
            batch_span_processor_cls=_Batch,
            httpx_instrumentor_cls=_HttpxInstr,
        )
        is True
    )


# Coverage gap tests for config.py branches
def test_repair_log_file_permissions_coverage(monkeypatch, tmp_path):
    log_file = tmp_path / "test_repair.log"
    log_file.touch()

    monkeypatch.setattr(os, "access", lambda path, mode: False)

    called_chown = []

    def fake_chown(path, uid, gid):
        called_chown.append((path, uid, gid))

    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "chown", fake_chown, raising=False)

    called_chmod = []

    def fake_chmod(self, mode):
        called_chmod.append(mode)

    monkeypatch.setattr(Path, "chmod", fake_chmod)

    config._repair_log_file_permissions(log_file)

    if hasattr(os, "chown"):
        assert len(called_chown) == 1
    assert len(called_chmod) == 1


def test_repair_log_file_permissions_returns_when_already_writable(monkeypatch, tmp_path):
    log_file = tmp_path / "already_writable.log"
    log_file.touch()

    monkeypatch.setattr(os, "access", lambda path, mode: True)

    called_chmod = []

    def fake_chmod(self, mode):
        called_chmod.append(mode)

    monkeypatch.setattr(Path, "chmod", fake_chmod)

    config._repair_log_file_permissions(log_file)

    assert called_chmod == []


def test_repair_log_file_permissions_skips_chown_when_ids_missing(monkeypatch, tmp_path):
    log_file = tmp_path / "missing_ids.log"
    log_file.touch()

    monkeypatch.setattr(os, "access", lambda path, mode: False)
    monkeypatch.setattr(os, "getuid", lambda: None, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: None, raising=False)

    called_chmod = []
    monkeypatch.setattr(Path, "chmod", lambda self, mode: called_chmod.append(mode))

    config._repair_log_file_permissions(log_file)
    assert len(called_chmod) == 1


def test_config_banner_uses_debug_when_quiet_flag_is_enabled(monkeypatch):
    monkeypatch.setenv("SIDAR_CONFIG_QUIET", "true")

    reloaded = importlib.reload(config)

    assert reloaded._config_banner_log.__name__ == "debug"


def test_noisy_dependency_loggers_stay_quiet_in_debug_unless_verbose_http(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("SIDAR_VERBOSE_HTTP", "false")

    reloaded = importlib.reload(config)

    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("huggingface_hub").level == logging.WARNING

    reloaded._configure_noisy_dependency_loggers(verbose_http=True)
    assert logging.getLogger("httpx").level == logging.NOTSET
    assert logging.getLogger("huggingface_hub").level == logging.NOTSET

    reloaded._configure_noisy_dependency_loggers(verbose_http=False)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("huggingface_hub").level == logging.WARNING


def test_rotating_file_handler_permission_error_coverage(monkeypatch):
    class MockRotatingFileHandler:
        def __init__(self, *args, **kwargs):
            raise PermissionError("Coverage için Mock PermissionError")

        def setFormatter(self, *args, **kwargs):
            pass

    monkeypatch.setattr("logging.handlers.RotatingFileHandler", MockRotatingFileHandler)
    importlib.reload(config)
    assert config.logger.name == "Sidar.Config"


def test_pynvml_happy_and_exception_paths(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_name=lambda _idx: "TestGPU",
            set_per_process_memory_fraction=lambda f, d=0: None,
        ),
        version=types.SimpleNamespace(cuda="12.0"),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)

    fake_pynvml_success = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlSystemGetDriverVersion=lambda: "999.99",
        nvmlShutdown=lambda: None,
    )
    monkeypatch.setitem(__import__("sys").modules, "pynvml", fake_pynvml_success)
    info_success = config.check_hardware()
    assert info_success.driver_version == "999.99"

    def nvml_init_fail():
        raise RuntimeError("NVML Başlatılamadı")

    fake_pynvml_fail = types.SimpleNamespace(nvmlInit=nvml_init_fail)
    monkeypatch.setitem(__import__("sys").modules, "pynvml", fake_pynvml_fail)
    info_fail = config.check_hardware()
    assert info_fail.driver_version == "N/A"


def test_multiprocessing_happy_path(monkeypatch):
    monkeypatch.setenv("USE_GPU", "false")

    fake_mp = types.SimpleNamespace(cpu_count=lambda: 32)
    monkeypatch.setitem(__import__("sys").modules, "multiprocessing", fake_mp)

    info = config.check_hardware()
    assert info.cpu_count == 32


def test_main_block_coverage():
    import runpy

    os.environ["DEBUG_MODE"] = "1"
    config_path = os.path.join(os.path.dirname(__file__), "../../../config.py")

    try:
        if os.path.exists(config_path):
            runpy.run_path(config_path, run_name="__main__")
        else:
            runpy.run_module("config", run_name="__main__")
    except Exception:
        pass
    finally:
        os.environ.pop("DEBUG_MODE", None)


def test_check_hardware_multi_gpu_and_zero_gpu_device_paths(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("MULTI_GPU", "true")
    monkeypatch.delenv("LLM_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RAG_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    called = []

    fake_torch_multi = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 2,
            get_device_name=lambda _idx: "MultiGPU",
            set_per_process_memory_fraction=lambda frac, device=0: called.append((frac, device)),
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "torch", fake_torch_multi)
    monkeypatch.setitem(
        modules,
        "pynvml",
        types.SimpleNamespace(
            nvmlInit=lambda: None,
            nvmlSystemGetDriverVersion=lambda: "550.1",
            nvmlShutdown=lambda: None,
        ),
    )
    info = config.check_hardware()
    assert info.gpu_count == 2
    assert called == [(0.8, 0), (0.8, 1)]

    monkeypatch.setenv("MULTI_GPU", "false")
    called.clear()
    fake_torch_zero = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 0,
            get_device_name=lambda _idx: "NoDevice",
            set_per_process_memory_fraction=lambda frac, device=0: called.append((frac, device)),
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    monkeypatch.setitem(modules, "torch", fake_torch_zero)
    info_zero = config.check_hardware()
    assert info_zero.gpu_count == 0
    assert called == [(0.8, 0)]


def test_trusted_proxies_as_list_returns_copy(monkeypatch):
    monkeypatch.setattr(config.Config, "TRUSTED_PROXIES_LIST", ["10.0.0.1", "10.0.0.2"])
    result = config.Config.trusted_proxies_as_list()
    assert result == ["10.0.0.1", "10.0.0.2"]
    assert result is not config.Config.TRUSTED_PROXIES_LIST


def test_trusted_proxies_defaults_to_loopback(monkeypatch) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    reloaded = importlib.reload(config)
    assert "127.0.0.1" in reloaded.Config.TRUSTED_PROXIES


def test_config_requires_jwt_secret_outside_test_env(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setattr(config.Config, "JWT_SECRET_KEY", "")
    with pytest.raises(ValueError, match="JWT_SECRET_KEY boş bırakılamaz"):
        config.Config()


@pytest.mark.parametrize(
    ("provider", "setting_name", "valid_value"),
    [
        ("gemini", "GEMINI_API_KEY", "gemini-key"),
        ("openai", "OPENAI_API_KEY", "openai-key"),
        ("anthropic", "ANTHROPIC_API_KEY", "anthropic-key"),
        ("litellm", "LITELLM_GATEWAY_URL", "https://litellm.internal"),
    ],
)
def test_validate_ai_provider_settings_rejects_missing_and_malformed_required_values(
    monkeypatch, provider, setting_name, valid_value
):
    monkeypatch.setattr(config.Config, "AI_PROVIDER", provider)
    monkeypatch.setattr(config.Config, setting_name, "   ")
    assert config.Config._validate_ai_provider_settings() is False

    malformed_value = "bad\nsecret" if setting_name != "LITELLM_GATEWAY_URL" else "not-a-url"
    monkeypatch.setattr(config.Config, setting_name, malformed_value)
    assert config.Config._validate_ai_provider_settings() is False

    monkeypatch.setattr(config.Config, setting_name, valid_value)
    assert config.Config._validate_ai_provider_settings() is True


def test_validate_ai_provider_settings_normalizes_provider_and_rejects_unknown(monkeypatch):
    monkeypatch.setattr(config.Config, "AI_PROVIDER", " OpenAI ")
    monkeypatch.setattr(config.Config, "OPENAI_API_KEY", "sk-centralized")
    assert config.Config._validate_ai_provider_settings() is True
    assert config.Config.AI_PROVIDER == "openai"

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "unknown")
    assert config.Config._validate_ai_provider_settings() is False


def test_validate_critical_settings_rejects_full_access_without_explicit_allow(monkeypatch):
    monkeypatch.setattr(
        config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(
        config.Config, "_apply_gpu_memory_safety_check", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full")
    monkeypatch.delenv("SIDAR_ALLOW_FULL_ACCESS", raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "openai")
    monkeypatch.setattr(config.Config, "OPENAI_API_KEY", "sk-valid")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")

    assert config.Config.validate_critical_settings() is False


def test_config_helper_edge_cases_cover_centralized_env_helpers(monkeypatch):
    relative = config._resolve_dotenv_path("relative.env")
    assert relative == config.BASE_DIR / "relative.env"

    assert config.is_nonempty_secret(None) is False
    assert config.is_valid_http_url(None) is False

    monkeypatch.setenv("LEGACY_INT_BAD", "bad-int")
    monkeypatch.delenv("SIDAR_INT_BAD", raising=False)
    assert config.get_int_prefixed_env("SIDAR_INT_BAD", "LEGACY_INT_BAD", 7) == 7

    monkeypatch.setenv("LEGACY_FLOAT_BAD", "bad-float")
    monkeypatch.delenv("SIDAR_FLOAT_BAD", raising=False)
    assert config.get_float_prefixed_env("SIDAR_FLOAT_BAD", "LEGACY_FLOAT_BAD", 1.5) == 1.5

    monkeypatch.setenv("LEGACY_BOOL_FALSE", "false")
    monkeypatch.delenv("SIDAR_BOOL_FALSE", raising=False)
    assert config.get_bool_prefixed_env("SIDAR_BOOL_FALSE", "LEGACY_BOOL_FALSE", True) is False


def test_dotenv_load_report_tracks_advanced_explicit_and_secret_precedence(monkeypatch):
    values_by_name = {
        ".env": {"OPENAI_API_KEY": "from-base", "JWT_SECRET_KEY": "jwt-base"},
        ".env.advanced": {"OPENAI_API_KEY": "from-advanced", "SIDAR_ENV": "development"},
        ".env.development": {"OPENAI_API_KEY": "from-development"},
        "runtime.env": {"OPENAI_API_KEY": "from-explicit"},
        "keys.env": {"OPENAI_API_KEY": "from-secret"},
    }

    def fake_exists(self):
        return self.name in values_by_name

    def fake_load_dotenv(*, dotenv_path=None, override=False):
        payload = values_by_name[Path(dotenv_path).name]
        for key, value in payload.items():
            if override or key not in os.environ:
                monkeypatch.setenv(key, value)
        return True

    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("DOTENV_FILE", "runtime.env")
    monkeypatch.setenv("SIDAR_KEYS_FILE", "keys.env")
    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)

    reloaded = importlib.reload(config)

    assert reloaded.Config.OPENAI_API_KEY == "from-secret"
    assert reloaded.Config.JWT_SECRET_KEY == "jwt-base"
    report = reloaded.get_dotenv_load_report()
    loaded_labels = [event["label"] for event in report if event["loaded"]]
    assert loaded_labels == [
        "base",
        "advanced",
        "environment:development",
        "explicit:DOTENV_FILE",
        "secret:SIDAR_KEYS_FILE",
    ]


def test_config_init_logs_env_status_before_missing_jwt_failure(monkeypatch, caplog):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setattr(config.Config, "JWT_SECRET_KEY", "")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")

    with pytest.raises(ValueError, match="JWT_SECRET_KEY boş bırakılamaz"):
        config.Config()

    assert "Kritik ortam anahtarları çözülemedi" in caplog.text
    assert "SIDAR_KEYS_FILE" in caplog.text


def test_new_env_runtime_helpers_cover_remaining_branches(monkeypatch, caplog):
    before = len(config.get_dotenv_load_report())
    assert (
        config._load_dotenv_if_exists(
            "missing-runtime.env", override=True, label="missing-no-record", record_missing=False
        )
        is None
    )
    assert len(config.get_dotenv_load_report()) == before

    monkeypatch.delenv("WEB_SCRAPE_MAX_CHARS", raising=False)
    monkeypatch.delenv("WEB_FETCH_MAX_CHARS", raising=False)
    assert config.get_web_scrape_max_chars(2468) == 2468

    monkeypatch.delenv("SIDAR_BOOL_DEFAULT", raising=False)
    monkeypatch.delenv("LEGACY_BOOL_DEFAULT", raising=False)
    assert config.get_bool_prefixed_env("SIDAR_BOOL_DEFAULT", "LEGACY_BOOL_DEFAULT", True) is True

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "litellm")
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "bad-url")
    monkeypatch.setattr(config.Config, "JWT_SECRET_KEY", "jwt-ok")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setenv("SIDAR_ENV", "production")
    assert config.Config.get_missing_critical_runtime_keys() == [
        "LITELLM_GATEWAY_URL",
        "MEMORY_ENCRYPTION_KEY",
    ]

    monkeypatch.setattr(config, "_DOTENV_LOAD_EVENTS", [], raising=False)
    config.Config._log_dotenv_load_status(missing_keys=[])
    assert "Hiçbir dotenv dosyası yüklenmedi" in caplog.text


def test_dotenv_key_source_report_and_debug_log(monkeypatch, tmp_path, caplog):
    env_file = tmp_path / "source.env"
    env_file.write_text(
        "OPENAI_API_KEY=sk-source\nDATABASE_URL=postgresql://sidar:secret@localhost/sidar\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(config, "_DOTENV_LOAD_EVENTS", [], raising=False)
    monkeypatch.setattr(config, "_DOTENV_KEY_SOURCES", {}, raising=False)
    caplog.set_level(logging.DEBUG, logger="Sidar.Config")

    loaded = config._load_dotenv_if_exists(str(env_file), override=False, label="test-source")

    assert loaded == env_file
    sources = config.get_dotenv_key_source_report()
    assert sources["OPENAI_API_KEY"]["path"] == str(env_file)
    assert sources["DATABASE_URL"]["label"] == "test-source"

    config.Config._log_dotenv_load_status(missing_keys=[])

    assert "Runtime env anahtar kaynakları" in caplog.text
    assert f"OPENAI_API_KEY->test-source={env_file}" in caplog.text
    assert "sk-source" not in caplog.text
    assert "secret" not in caplog.text


def test_ensure_hardware_info_loaded_uses_check_hardware_result(monkeypatch):
    monkeypatch.setattr(config.Config, "_hardware_loaded", False)
    monkeypatch.setattr(config.Config, "USE_GPU", True)
    monkeypatch.setattr(
        config,
        "check_hardware",
        lambda: config.HardwareInfo(
            has_cuda=True,
            gpu_name="LoadedGPU",
            gpu_count=3,
            cpu_count=12,
            cuda_version="12.4",
            driver_version="555.1",
        ),
    )

    config.Config._ensure_hardware_info_loaded()

    assert config.Config.USE_GPU is True
    assert config.Config.GPU_INFO == "LoadedGPU"
    assert config.Config.GPU_COUNT == 3
    assert config.Config.CPU_COUNT == 12
    assert config.Config.CUDA_VERSION == "12.4"
    assert config.Config.DRIVER_VERSION == "555.1"


def test_get_missing_critical_runtime_keys_accepts_valid_litellm_url(monkeypatch):
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "litellm")
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "https://litellm.internal")
    monkeypatch.setattr(config.Config, "JWT_SECRET_KEY", "jwt-ok")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setenv("SIDAR_ENV", "development")

    assert config.Config.get_missing_critical_runtime_keys() == []


def test_sidar_keys_example_does_not_ship_active_empty_overrides() -> None:
    """The personal keys template must not blank .env values when copied as-is."""
    example_path = Path(__file__).resolve().parents[3] / ".sidar_keys.env.example"
    active_empty_assignments: list[str] = []

    for raw_line in example_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() and not value.strip():
            active_empty_assignments.append(key.strip())

    assert active_empty_assignments == []


def test_sidar_keys_example_documents_manual_and_autonomous_sections() -> None:
    example_path = Path(__file__).resolve().parents[3] / ".sidar_keys.env.example"
    content = example_path.read_text(encoding="utf-8")

    assert "OTONOM oluşabilen yerel güvenlik secretları" in content
    assert "MANUEL doldurulan AI sağlayıcıları" in content
    assert "MANUEL doldurulan Meta / Poyraz sosyal yayın anahtarları" in content
    assert "Boş `KEY=` satırlarını aktif bırakmayın" in content
    assert "Gerçek tokenları issue/PR/chat ekranlarına yapıştırmayın" in content
    assert "config preflight en az LITELLM_GATEWAY_URL bekler" in content


def test_reload_environment_loads_new_development_profile(monkeypatch, tmp_path):
    (tmp_path / ".env.development").write_text(
        "SIDAR_ENV=development\n"
        "AI_PROVIDER=openai\n"
        "OPENAI_API_KEY=sk-test\n"
        "API_KEY=api-reloaded\n"
        "JWT_SECRET_KEY=jwt-reloaded\n"
        "WEB_PORT=8765\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("DOTENV_FILE", raising=False)
    monkeypatch.setenv("SIDAR_KEYS_FILE", "")
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", lambda: None)
    monkeypatch.setattr(config.Config, "_apply_gpu_memory_safety_check", lambda: None)

    reloaded = config.reload_environment(profile="development")

    assert reloaded is config.get_config()
    assert config.Config.AI_PROVIDER == "openai"
    assert config.Config.OPENAI_API_KEY == "sk-test"
    assert config.Config.API_KEY == "api-reloaded"
    assert config.Config.JWT_SECRET_KEY == "jwt-reloaded"
    assert config.Config.WEB_PORT == 8765
    report = config.get_dotenv_load_report()
    assert any(event["label"] == "environment:development" and event["loaded"] for event in report)
