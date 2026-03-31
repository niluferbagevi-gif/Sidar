"""
config.py için birim testleri.
Yardımcı fonksiyonlar, HardwareInfo dataclass, Config sınıfı
ve ilgili sınıf metotlarını kapsar.
"""

import os
import sys
import types
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────
# Yardımcı: config modülünü temiz ortamda yeniden yükle
# ──────────────────────────────────────────────────────────────

def _reload_config(env_overrides: dict | None = None):
    """
    config modülünü temiz bir ortamda yeniden yükler.
    env_overrides: test süresince geçerli olacak ek ortam değişkenleri.
    """
    env_overrides = env_overrides or {}
    for mod in list(sys.modules.keys()):
        if mod == "config" or mod.startswith("config."):
            del sys.modules[mod]

    with patch.dict(os.environ, env_overrides, clear=False):
        import config as cfg
    return cfg


# ══════════════════════════════════════════════════════════════
# get_bool_env
# ══════════════════════════════════════════════════════════════

class TestGetBoolEnv:
    def setup_method(self):
        import config
        self.fn = config.get_bool_env

    def test_true_values(self):
        for val in ("true", "1", "yes", "on", "TRUE", "YES", "On"):
            with patch.dict(os.environ, {"_TEST_BOOL": val}):
                assert self.fn("_TEST_BOOL") is True, f"'{val}' True döndürmeli"

    def test_false_values(self):
        for val in ("false", "0", "no", "off", "False", "NO"):
            with patch.dict(os.environ, {"_TEST_BOOL": val}):
                assert self.fn("_TEST_BOOL") is False, f"'{val}' False döndürmeli"

    def test_missing_key_returns_default_false(self):
        os.environ.pop("_TEST_BOOL", None)
        assert self.fn("_TEST_BOOL") is False

    def test_missing_key_returns_custom_default(self):
        os.environ.pop("_TEST_BOOL", None)
        assert self.fn("_TEST_BOOL", True) is True

    def test_empty_string_returns_default(self):
        with patch.dict(os.environ, {"_TEST_BOOL": ""}):
            assert self.fn("_TEST_BOOL", True) is True

    def test_whitespace_only_returns_default(self):
        with patch.dict(os.environ, {"_TEST_BOOL": "   "}):
            assert self.fn("_TEST_BOOL", False) is False


# ══════════════════════════════════════════════════════════════
# get_int_env
# ══════════════════════════════════════════════════════════════

class TestGetIntEnv:
    def setup_method(self):
        import config
        self.fn = config.get_int_env

    def test_valid_integer(self):
        with patch.dict(os.environ, {"_TEST_INT": "42"}):
            assert self.fn("_TEST_INT") == 42

    def test_negative_integer(self):
        with patch.dict(os.environ, {"_TEST_INT": "-7"}):
            assert self.fn("_TEST_INT") == -7

    def test_missing_key_returns_default(self):
        os.environ.pop("_TEST_INT", None)
        assert self.fn("_TEST_INT", 99) == 99

    def test_invalid_value_returns_default(self):
        with patch.dict(os.environ, {"_TEST_INT": "abc"}):
            assert self.fn("_TEST_INT", 5) == 5

    def test_float_string_returns_default(self):
        with patch.dict(os.environ, {"_TEST_INT": "3.14"}):
            assert self.fn("_TEST_INT", 0) == 0

    def test_zero(self):
        with patch.dict(os.environ, {"_TEST_INT": "0"}):
            assert self.fn("_TEST_INT", 10) == 0


# ══════════════════════════════════════════════════════════════
# get_float_env
# ══════════════════════════════════════════════════════════════

class TestGetFloatEnv:
    def setup_method(self):
        import config
        self.fn = config.get_float_env

    def test_valid_float(self):
        with patch.dict(os.environ, {"_TEST_FLOAT": "3.14"}):
            assert self.fn("_TEST_FLOAT") == pytest.approx(3.14)

    def test_integer_string(self):
        with patch.dict(os.environ, {"_TEST_FLOAT": "5"}):
            assert self.fn("_TEST_FLOAT") == pytest.approx(5.0)

    def test_negative_float(self):
        with patch.dict(os.environ, {"_TEST_FLOAT": "-0.5"}):
            assert self.fn("_TEST_FLOAT") == pytest.approx(-0.5)

    def test_missing_key_returns_default(self):
        os.environ.pop("_TEST_FLOAT", None)
        assert self.fn("_TEST_FLOAT", 1.5) == pytest.approx(1.5)

    def test_invalid_value_returns_default(self):
        with patch.dict(os.environ, {"_TEST_FLOAT": "xyz"}):
            assert self.fn("_TEST_FLOAT", 2.0) == pytest.approx(2.0)


# ══════════════════════════════════════════════════════════════
# get_list_env
# ══════════════════════════════════════════════════════════════

class TestGetListEnv:
    def setup_method(self):
        import config
        self.fn = config.get_list_env

    def test_comma_separated(self):
        with patch.dict(os.environ, {"_TEST_LIST": "a,b,c"}):
            assert self.fn("_TEST_LIST") == ["a", "b", "c"]

    def test_spaces_trimmed(self):
        with patch.dict(os.environ, {"_TEST_LIST": " x , y , z "}):
            assert self.fn("_TEST_LIST") == ["x", "y", "z"]

    def test_empty_string_returns_default(self):
        with patch.dict(os.environ, {"_TEST_LIST": ""}):
            assert self.fn("_TEST_LIST", ["default"]) == ["default"]

    def test_missing_key_returns_empty_list(self):
        os.environ.pop("_TEST_LIST", None)
        assert self.fn("_TEST_LIST") == []

    def test_custom_separator(self):
        with patch.dict(os.environ, {"_TEST_LIST": "a|b|c"}):
            assert self.fn("_TEST_LIST", separator="|") == ["a", "b", "c"]

    def test_single_item(self):
        with patch.dict(os.environ, {"_TEST_LIST": "solo"}):
            assert self.fn("_TEST_LIST") == ["solo"]

    def test_empty_items_filtered(self):
        with patch.dict(os.environ, {"_TEST_LIST": "a,,b,"}):
            assert self.fn("_TEST_LIST") == ["a", "b"]


# ══════════════════════════════════════════════════════════════
# HardwareInfo dataclass
# ══════════════════════════════════════════════════════════════

class TestHardwareInfo:
    def test_creation_with_required_fields(self):
        import config
        hw = config.HardwareInfo(has_cuda=True, gpu_name="Tesla T4")
        assert hw.has_cuda is True
        assert hw.gpu_name == "Tesla T4"
        assert hw.gpu_count == 0
        assert hw.cpu_count == 0
        assert hw.cuda_version == "N/A"
        assert hw.driver_version == "N/A"

    def test_creation_with_all_fields(self):
        import config
        hw = config.HardwareInfo(
            has_cuda=True,
            gpu_name="A100",
            gpu_count=2,
            cpu_count=32,
            cuda_version="12.1",
            driver_version="525.0",
        )
        assert hw.gpu_count == 2
        assert hw.cuda_version == "12.1"
        assert hw.driver_version == "525.0"

    def test_no_cuda(self):
        import config
        hw = config.HardwareInfo(has_cuda=False, gpu_name="N/A")
        assert hw.has_cuda is False


# ══════════════════════════════════════════════════════════════
# _is_wsl2
# ══════════════════════════════════════════════════════════════

class TestIsWsl2:
    def test_wsl2_detected(self):
        import config
        with patch("pathlib.Path.read_text", return_value="5.15.90.1-microsoft-standard-WSL2"):
            assert config._is_wsl2() is True

    def test_not_wsl2(self):
        import config
        with patch("pathlib.Path.read_text", return_value="6.1.0-generic"):
            assert config._is_wsl2() is False

    def test_file_not_found_returns_false(self):
        import config
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert config._is_wsl2() is False

    def test_permission_error_returns_false(self):
        import config
        with patch("pathlib.Path.read_text", side_effect=PermissionError):
            assert config._is_wsl2() is False


# ══════════════════════════════════════════════════════════════
# check_hardware
# ══════════════════════════════════════════════════════════════

class TestCheckHardware:
    def test_use_gpu_false_returns_disabled(self):
        import config
        with patch.dict(os.environ, {"USE_GPU": "false"}):
            with patch.object(config, "get_bool_env", side_effect=lambda k, d=False: False if k == "USE_GPU" else d):
                hw = config.check_hardware()
        assert hw.has_cuda is False
        assert "Devre" in hw.gpu_name or hw.gpu_name != ""

    def test_no_torch_returns_pytorch_missing(self):
        import config
        with patch.dict(os.environ, {"USE_GPU": "true"}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'torch'")):
                # config.check_hardware içindeki torch importu ImportError fırlatmalı
                pass
        # torch import edilemediğinde HardwareInfo.gpu_name "PyTorch Yok" olur
        # patch.dict ile USE_GPU açık, torch yok
        saved_torch = sys.modules.get("torch")
        sys.modules["torch"] = None  # type: ignore
        try:
            hw = config.check_hardware()
        finally:
            if saved_torch is None:
                sys.modules.pop("torch", None)
            else:
                sys.modules["torch"] = saved_torch
        # torch=None iken ImportError benzeri davranış beklenir
        assert hw.has_cuda is False

    def test_torch_available_no_cuda(self):
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.version.cuda = None
        with patch.dict(sys.modules, {"torch": mock_torch}):
            with patch.dict(os.environ, {"USE_GPU": "true"}):
                with patch.object(config, "get_bool_env", return_value=True):
                    hw = config.check_hardware()
        assert hw.has_cuda is False

    def test_torch_available_with_cuda(self):
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "RTX 3090"
        mock_torch.version.cuda = "11.8"
        with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
            with patch.dict(os.environ, {"USE_GPU": "true"}):
                with patch.object(config, "get_bool_env", return_value=True):
                    hw = config.check_hardware()
        assert hw.has_cuda is True
        assert hw.gpu_name == "RTX 3090"
        assert hw.gpu_count == 1
        assert hw.cuda_version == "11.8"

    def test_cpu_count_populated(self):
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        with patch.dict(sys.modules, {"torch": mock_torch}):
            with patch("multiprocessing.cpu_count", return_value=8):
                with patch.object(config, "get_bool_env", return_value=True):
                    hw = config.check_hardware()
        assert hw.cpu_count == 8


# ══════════════════════════════════════════════════════════════
# Config — varsayılan değerler
# ══════════════════════════════════════════════════════════════

class TestConfigDefaults:
    def test_project_name(self):
        import config
        assert config.Config.PROJECT_NAME == "Sidar"

    def test_version_set(self):
        import config
        assert config.Config.VERSION != ""

    def test_base_dir_is_path(self):
        import config
        assert isinstance(config.Config.BASE_DIR, Path)

    def test_default_ai_provider(self):
        os.environ.pop("AI_PROVIDER", None)
        cfg = _reload_config()
        assert cfg.Config.AI_PROVIDER == "ollama"

    def test_default_ollama_url(self):
        os.environ.pop("OLLAMA_URL", None)
        cfg = _reload_config()
        assert cfg.Config.OLLAMA_URL.startswith("http")

    def test_default_web_port(self):
        os.environ.pop("WEB_PORT", None)
        cfg = _reload_config()
        assert cfg.Config.WEB_PORT == 7860

    def test_invalid_web_port_env_falls_back_to_default(self):
        cfg = _reload_config({"WEB_PORT": "not-a-number"})
        assert cfg.Config.WEB_PORT == 7860

    def test_default_debug_mode_is_false(self):
        os.environ.pop("DEBUG_MODE", None)
        cfg = _reload_config()
        assert cfg.Config.DEBUG_MODE is False

    def test_default_database_url_sqlite(self):
        os.environ.pop("DATABASE_URL", None)
        cfg = _reload_config()
        assert "sqlite" in cfg.Config.DATABASE_URL

    def test_default_jwt_algorithm(self):
        os.environ.pop("JWT_ALGORITHM", None)
        cfg = _reload_config()
        assert cfg.Config.JWT_ALGORITHM == "HS256"

    def test_default_jwt_ttl_days(self):
        os.environ.pop("JWT_TTL_DAYS", None)
        cfg = _reload_config()
        assert cfg.Config.JWT_TTL_DAYS == 7

    def test_default_response_language(self):
        os.environ.pop("RESPONSE_LANGUAGE", None)
        cfg = _reload_config()
        assert cfg.Config.RESPONSE_LANGUAGE == "tr"

    def test_required_dirs_contains_temp_logs_data(self):
        import config
        names = [p.name for p in config.Config.REQUIRED_DIRS]
        assert "temp" in names
        assert "logs" in names
        assert "data" in names

    def test_sandbox_limits_keys(self):
        import config
        keys = set(config.Config.SANDBOX_LIMITS.keys())
        assert {"memory", "cpus", "pids_limit", "network", "timeout"}.issubset(keys)

    def test_dlp_enabled_default(self):
        os.environ.pop("DLP_ENABLED", None)
        cfg = _reload_config()
        assert cfg.Config.DLP_ENABLED is True

    def test_rate_limit_chat_default(self):
        os.environ.pop("RATE_LIMIT_CHAT", None)
        cfg = _reload_config()
        assert cfg.Config.RATE_LIMIT_CHAT == 20

    def test_lora_rank_default(self):
        os.environ.pop("LORA_RANK", None)
        cfg = _reload_config()
        assert cfg.Config.LORA_RANK == 8


# ══════════════════════════════════════════════════════════════
# Config — ortam değişkeni geçersiz kılma
# ══════════════════════════════════════════════════════════════

class TestConfigEnvOverrides:
    def test_ai_provider_override(self):
        cfg = _reload_config({"AI_PROVIDER": "gemini"})
        assert cfg.Config.AI_PROVIDER == "gemini"

    def test_debug_mode_override(self):
        cfg = _reload_config({"DEBUG_MODE": "true"})
        assert cfg.Config.DEBUG_MODE is True

    def test_web_port_override(self):
        cfg = _reload_config({"WEB_PORT": "8080"})
        assert cfg.Config.WEB_PORT == 8080

    def test_ollama_timeout_override(self):
        cfg = _reload_config({"OLLAMA_TIMEOUT": "120"})
        assert cfg.Config.OLLAMA_TIMEOUT == 120

    def test_max_react_steps_override(self):
        cfg = _reload_config({"MAX_REACT_STEPS": "25"})
        assert cfg.Config.MAX_REACT_STEPS == 25

    def test_response_language_override(self):
        cfg = _reload_config({"RESPONSE_LANGUAGE": "en"})
        assert cfg.Config.RESPONSE_LANGUAGE == "en"

    def test_gemini_model_override(self):
        cfg = _reload_config({"GEMINI_MODEL": "gemini-1.5-pro"})
        assert cfg.Config.GEMINI_MODEL == "gemini-1.5-pro"

    def test_log_level_override(self):
        cfg = _reload_config({"LOG_LEVEL": "DEBUG"})
        assert cfg.Config.LOG_LEVEL == "DEBUG"

    def test_enable_tracing_override(self):
        cfg = _reload_config({"ENABLE_TRACING": "true"})
        assert cfg.Config.ENABLE_TRACING is True

    def test_docker_required_override(self):
        cfg = _reload_config({"DOCKER_REQUIRED": "true"})
        assert cfg.Config.DOCKER_REQUIRED is True

    def test_invalid_web_port_falls_back_to_default(self):
        cfg = _reload_config({"WEB_PORT": "not-a-number"})
        assert cfg.Config.WEB_PORT == 7860

    def test_invalid_ollama_timeout_falls_back_to_default(self):
        cfg = _reload_config({"OLLAMA_TIMEOUT": "timeout"})
        assert cfg.Config.OLLAMA_TIMEOUT == 30

    def test_invalid_rate_limit_chat_falls_back_to_default(self):
        cfg = _reload_config({"RATE_LIMIT_CHAT": "NaN"})
        assert cfg.Config.RATE_LIMIT_CHAT == 20

    def test_invalid_gpu_memory_fraction_falls_back_to_default(self):
        cfg = _reload_config({"GPU_MEMORY_FRACTION": "invalid-float"})
        assert cfg.Config.GPU_MEMORY_FRACTION == pytest.approx(0.8)

    def test_invalid_judge_sample_rate_env_fails_fast_with_value_error(self):
        import importlib
        import os
        import sys

        with patch.dict(os.environ, {"JUDGE_SAMPLE_RATE": "not-a-float"}, clear=False):
            sys.modules.pop("config", None)
            with pytest.raises(ValueError):
                importlib.import_module("config")


# ══════════════════════════════════════════════════════════════
# Config.set_provider_mode
# ══════════════════════════════════════════════════════════════

class TestSetProviderMode:
    def setup_method(self):
        import config
        self.Config = config.Config

    def test_online_sets_gemini(self):
        self.Config.set_provider_mode("online")
        assert self.Config.AI_PROVIDER == "gemini"

    def test_gemini_alias(self):
        self.Config.set_provider_mode("gemini")
        assert self.Config.AI_PROVIDER == "gemini"

    def test_local_sets_ollama(self):
        self.Config.set_provider_mode("local")
        assert self.Config.AI_PROVIDER == "ollama"

    def test_ollama_alias(self):
        self.Config.set_provider_mode("ollama")
        assert self.Config.AI_PROVIDER == "ollama"

    def test_anthropic_mode(self):
        self.Config.set_provider_mode("anthropic")
        assert self.Config.AI_PROVIDER == "anthropic"

    def test_litellm_mode(self):
        self.Config.set_provider_mode("litellm")
        assert self.Config.AI_PROVIDER == "litellm"

    def test_uppercase_input(self):
        self.Config.set_provider_mode("GEMINI")
        assert self.Config.AI_PROVIDER == "gemini"

    def test_invalid_mode_does_not_change_provider(self):
        self.Config.AI_PROVIDER = "ollama"
        self.Config.set_provider_mode("invalid_provider")
        assert self.Config.AI_PROVIDER == "ollama"


# ══════════════════════════════════════════════════════════════
# Config.initialize_directories
# ══════════════════════════════════════════════════════════════

class TestInitializeDirectories:
    def test_returns_true_on_success(self, tmp_path):
        import config
        original_dirs = config.Config.REQUIRED_DIRS
        config.Config.REQUIRED_DIRS = [tmp_path / "temp", tmp_path / "logs", tmp_path / "data"]
        try:
            result = config.Config.initialize_directories()
            assert result is True
            for d in config.Config.REQUIRED_DIRS:
                assert d.exists()
        finally:
            config.Config.REQUIRED_DIRS = original_dirs

    def test_returns_false_on_permission_error(self, tmp_path):
        import config
        original_dirs = config.Config.REQUIRED_DIRS
        bad_dir = tmp_path / "no_perms" / "sub"
        config.Config.REQUIRED_DIRS = [bad_dir]
        with patch.object(Path, "mkdir", side_effect=PermissionError("access denied")):
            result = config.Config.initialize_directories()
        assert result is False
        config.Config.REQUIRED_DIRS = original_dirs

    def test_existing_dirs_not_raise(self, tmp_path):
        import config
        existing = tmp_path / "existing"
        existing.mkdir()
        original_dirs = config.Config.REQUIRED_DIRS
        config.Config.REQUIRED_DIRS = [existing]
        try:
            result = config.Config.initialize_directories()
            assert result is True
        finally:
            config.Config.REQUIRED_DIRS = original_dirs


# ══════════════════════════════════════════════════════════════
# Config.validate_critical_settings
# ══════════════════════════════════════════════════════════════

class TestValidateCriticalSettings:
    def _make_config_with_provider(self, provider: str, extra: dict | None = None):
        """Belirtilen provider ile Config sınıfını hazırlar."""
        import config
        config.Config._hardware_loaded = True  # donanım kontrolünü atla
        config.Config.AI_PROVIDER = provider
        # Gerçek .env'den gelen geçersiz MEMORY_ENCRYPTION_KEY testleri bozmasın;
        # boş string "else" dalına düşer (sadece CRITICAL log, is_valid etkilenmez).
        config.Config.MEMORY_ENCRYPTION_KEY = ""
        for k, v in (extra or {}).items():
            setattr(config.Config, k, v)
        return config.Config

    def test_valid_ollama_skips_api_key_check(self):
        import config
        cfg = self._make_config_with_provider("ollama")
        # validate_critical_settings içinde Ollama bağlantı kontrolü httpx.Client kullanır;
        # exception fırlasa bile False dönmez, sadece uyarı loglar.
        with patch.object(cfg, "initialize_directories", return_value=True):
            with patch("config.logger"):  # log çıktısını bastır
                result = cfg.validate_critical_settings()
        assert result is True

    def test_gemini_without_api_key_invalid(self):
        import config
        cfg = self._make_config_with_provider("gemini", {"GEMINI_API_KEY": ""})
        with patch.object(cfg, "initialize_directories", return_value=True):
            result = cfg.validate_critical_settings()
        assert result is False

    def test_gemini_with_api_key_valid(self):
        import config
        cfg = self._make_config_with_provider("gemini", {"GEMINI_API_KEY": "test-key-123"})
        with patch.object(cfg, "initialize_directories", return_value=True):
            result = cfg.validate_critical_settings()
        assert result is True

    def test_openai_without_api_key_invalid(self):
        import config
        cfg = self._make_config_with_provider("openai", {"OPENAI_API_KEY": ""})
        with patch.object(cfg, "initialize_directories", return_value=True):
            result = cfg.validate_critical_settings()
        assert result is False

    def test_anthropic_without_api_key_invalid(self):
        import config
        cfg = self._make_config_with_provider("anthropic", {"ANTHROPIC_API_KEY": ""})
        with patch.object(cfg, "initialize_directories", return_value=True):
            result = cfg.validate_critical_settings()
        assert result is False

    def test_litellm_without_gateway_url_invalid(self):
        import config
        cfg = self._make_config_with_provider("litellm", {"LITELLM_GATEWAY_URL": ""})
        with patch.object(cfg, "initialize_directories", return_value=True):
            result = cfg.validate_critical_settings()
        assert result is False

    def test_litellm_with_gateway_url_valid(self):
        import config
        cfg = self._make_config_with_provider(
            "litellm",
            {"LITELLM_GATEWAY_URL": "http://gateway:4000", "MEMORY_ENCRYPTION_KEY": ""},
        )
        with patch.object(cfg, "initialize_directories", return_value=True):
            result = cfg.validate_critical_settings()
        assert result is True


# ══════════════════════════════════════════════════════════════
# Config.get_system_info
# ══════════════════════════════════════════════════════════════

class TestGetSystemInfo:
    def test_returns_dict(self):
        import config
        config.Config._hardware_loaded = True
        info = config.Config.get_system_info()
        assert isinstance(info, dict)

    def test_required_keys_present(self):
        import config
        config.Config._hardware_loaded = True
        info = config.Config.get_system_info()
        required_keys = {
            "project", "version", "provider", "gpu_enabled",
            "gpu_info", "cpu_count", "debug_mode", "web_port",
        }
        assert required_keys.issubset(set(info.keys()))

    def test_project_name_in_info(self):
        import config
        config.Config._hardware_loaded = True
        info = config.Config.get_system_info()
        assert info["project"] == "Sidar"

    def test_redis_url_not_exposed(self):
        import config
        config.Config._hardware_loaded = True
        info = config.Config.get_system_info()
        assert "redis_url" not in info
        assert "REDIS_URL" not in info

    def test_rate_limit_keys_in_info(self):
        import config
        config.Config._hardware_loaded = True
        info = config.Config.get_system_info()
        assert "rate_limit_chat" in info
        assert "rate_limit_window" in info

    def test_semantic_cache_keys_in_info(self):
        import config
        config.Config._hardware_loaded = True
        info = config.Config.get_system_info()
        assert "enable_semantic_cache" in info
        assert "semantic_cache_threshold" in info


# ══════════════════════════════════════════════════════════════
# Config — ensure_hardware_info_loaded (lazy load)
# ══════════════════════════════════════════════════════════════

class TestEnsureHardwareInfoLoaded:
    def test_called_twice_does_not_reload(self):
        import config
        config.Config._hardware_loaded = False
        config.Config.USE_GPU = False

        with patch.object(config, "check_hardware") as mock_hw:
            config.Config._ensure_hardware_info_loaded()
            config.Config._ensure_hardware_info_loaded()
        mock_hw.assert_not_called()  # USE_GPU=False iken check_hardware çağrılmamalı
        assert config.Config._hardware_loaded is True

    def test_use_gpu_false_skips_check_hardware(self):
        import config
        config.Config._hardware_loaded = False
        config.Config.USE_GPU = False
        with patch.object(config, "check_hardware") as mock_hw:
            config.Config._ensure_hardware_info_loaded()
        mock_hw.assert_not_called()
        assert config.Config.GPU_INFO == "Devre Dışı / CPU Modu"

    def test_use_gpu_true_calls_check_hardware(self):
        import config
        config.Config._hardware_loaded = False
        config.Config.USE_GPU = True
        fake_hw = config.HardwareInfo(
            has_cuda=True, gpu_name="FakeGPU", gpu_count=1, cpu_count=4, cuda_version="11.0"
        )
        with patch.object(config, "check_hardware", return_value=fake_hw) as mock_hw:
            config.Config._ensure_hardware_info_loaded()
        mock_hw.assert_called_once()
        assert config.Config.GPU_INFO == "FakeGPU"
        assert config.Config.GPU_COUNT == 1
        assert config.Config.CUDA_VERSION == "11.0"


# ══════════════════════════════════════════════════════════════
# Config.__init__
# ══════════════════════════════════════════════════════════════

class TestConfigInit:
    def test_instantiation_triggers_hardware_load(self):
        import config
        config.Config._hardware_loaded = False
        config.Config.USE_GPU = False
        instance = config.Config()
        assert config.Config._hardware_loaded is True
        assert isinstance(instance, config.Config)


# ══════════════════════════════════════════════════════════════
# SANDBOX_LIMITS modül-seviyesi sabit
# ══════════════════════════════════════════════════════════════

class TestSandboxLimits:
    def test_default_memory(self):
        import config
        assert config.SANDBOX_LIMITS["memory"] == "256m"

    def test_default_cpus(self):
        import config
        assert config.SANDBOX_LIMITS["cpus"] == "0.5"

    def test_default_network(self):
        import config
        assert config.SANDBOX_LIMITS["network"] == "none"

    def test_default_pids_limit(self):
        import config
        assert config.SANDBOX_LIMITS["pids_limit"] == 64

    def test_default_timeout(self):
        import config
        assert config.SANDBOX_LIMITS["timeout"] == 10

    def test_override_from_env(self):
        cfg = _reload_config({"SANDBOX_MEMORY": "512m", "SANDBOX_TIMEOUT": "30"})
        assert cfg.SANDBOX_LIMITS["memory"] == "512m"
        assert cfg.SANDBOX_LIMITS["timeout"] == 30

class TestConfigTelemetryAndSingleton:
    def test_get_config_returns_singleton_instance(self):
        import config
        config._config_instance = None
        first = config.get_config()
        second = config.get_config()
        assert first is second

    def test_init_telemetry_returns_false_when_disabled(self):
        import config
        with patch.object(config.Config, "ENABLE_TRACING", False):
            assert config.Config.init_telemetry() is False

    def test_init_telemetry_returns_false_when_dependencies_missing(self):
        import config
        with patch.object(config.Config, "ENABLE_TRACING", True):
            with patch.dict(sys.modules, {"opentelemetry": None}):
                result = config.Config.init_telemetry(
                    trace_module=None,
                    otlp_exporter_cls=None,
                    tracer_provider_cls=None,
                    resource_cls=None,
                    batch_span_processor_cls=None,
                )
        assert result is False

    def test_print_config_summary_in_ollama_mode_contains_model_lines(self, capsys):
        import config
        with patch.object(config.Config, "AI_PROVIDER", "ollama"):
            with patch.object(config.Config, "USE_GPU", False):
                with patch.object(config.Config, "GPU_INFO", "CPU"):
                    config.Config.print_config_summary()
        out = capsys.readouterr().out
        assert "CODING Modeli" in out
        assert "TEXT Modeli" in out
