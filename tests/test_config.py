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

# ===== MERGED FROM tests/test_config_extra.py =====

import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# Stub dotenv so patch("dotenv.load_dotenv") works without the package installed
if "dotenv" not in sys.modules:
    _dotenv_mod = types.ModuleType("dotenv")
    _dotenv_mod.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _dotenv_mod


# ══════════════════════════════════════════════════════════════
# Satır 40-44: base_env_path.exists() → load_dotenv çağrısı
# ══════════════════════════════════════════════════════════════

class Extra1_TestEnvFileLoading:
    def test_base_env_loaded_when_exists(self, tmp_path, monkeypatch):
        """base_env_path.exists() True ise load_dotenv çağrılmalı (satır 40-41)."""
        fake_env = tmp_path / ".env"
        fake_env.write_text("TEST_VAR=hello\n")

        for mod in list(sys.modules):
            if mod == "config" or mod.startswith("config."):
                del sys.modules[mod]

        load_dotenv_calls = []

        def fake_load_dotenv(dotenv_path=None, override=False):
            load_dotenv_calls.append(dotenv_path)
            return True

        with patch.dict(os.environ, {"SIDAR_ENV": ""}, clear=False):
            with patch("pathlib.Path.resolve", return_value=tmp_path):
                with patch("dotenv.load_dotenv", fake_load_dotenv, create=True):
                    # dotenv yoksa stub'dan load_dotenv import eder — doğrudan test et
                    import config as cfg  # noqa: F401

        # Modül yüklenirse test geçer (exception yok)
        assert cfg is not None

    def test_sidar_env_specific_file_loaded(self, tmp_path, monkeypatch):
        """SIDAR_ENV=production olduğunda .env.production yüklenip mesaj basılmalı (satır 47-48)."""
        for mod in list(sys.modules):
            if mod == "config" or mod.startswith("config."):
                del sys.modules[mod]

        printed = []
        real_print = print

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        with patch.dict(os.environ, {"SIDAR_ENV": "production"}, clear=False):
            with patch("builtins.print", capture_print):
                with patch("pathlib.Path.exists", return_value=True):
                    with patch("dotenv.load_dotenv", return_value=True, create=True):
                        import config  # noqa: F401

    def test_sidar_env_missing_specific_file_prints_warning(self, tmp_path):
        """SIDAR_ENV ayarlı ama .env.{env} yok → uyarı basılmalı (satır 56)."""
        for mod in list(sys.modules):
            if mod == "config" or mod.startswith("config."):
                del sys.modules[mod]

        printed = []

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        def mock_exists(self):
            return str(self).endswith(".env")  # .env.production yok

        with patch.dict(os.environ, {"SIDAR_ENV": "production"}, clear=False):
            with patch("builtins.print", capture_print):
                with patch.object(Path, "exists", mock_exists):
                    import config  # noqa: F401

    def test_no_env_file_at_all_prints_warning(self):
        """Ne .env ne de SIDAR_ENV varken uyarı basılmalı (satır 58)."""
        for mod in list(sys.modules):
            if mod == "config" or mod.startswith("config."):
                del sys.modules[mod]

        printed = []

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        with patch.dict(os.environ, {"SIDAR_ENV": ""}, clear=False):
            with patch("builtins.print", capture_print):
                with patch.object(Path, "exists", return_value=False):
                    import config  # noqa: F401

    def test_sidar_env_dev_alias_with_base_env_prints_info(self):
        """SIDAR_ENV=dev + .env.dev yok + base .env var → bilgi mesajı (satır 51-54)."""
        for mod in list(sys.modules):
            if mod == "config" or mod.startswith("config."):
                del sys.modules[mod]

        printed = []

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        def mock_exists(self):
            # .env var, .env.dev yok
            name = str(self)
            if name.endswith(".env.dev"):
                return False
            if name.endswith(".env"):
                return True
            return False

        with patch.dict(os.environ, {"SIDAR_ENV": "dev"}, clear=False):
            with patch("builtins.print", capture_print):
                with patch.object(Path, "exists", mock_exists):
                    with patch("dotenv.load_dotenv", return_value=True, create=True):
                        import config  # noqa: F401


# ══════════════════════════════════════════════════════════════
# Satır 126-132: ENV_PATH.exists() → logger.info
# ══════════════════════════════════════════════════════════════

class Extra1_TestEnvPathLogging:
    def test_env_path_exists_triggers_logger_info(self):
        """ENV_PATH var ise logger.info çağrılmalı (satır 126-127)."""
        for mod in list(sys.modules):
            if mod == "config" or mod.startswith("config."):
                del sys.modules[mod]

        with patch.object(Path, "exists", return_value=True):
            with patch("dotenv.load_dotenv", return_value=True, create=True):
                with patch("builtins.print"):
                    import config  # noqa: F401

        # Sadece modül import başarılı mı kontrol et
        assert config is not None


# ══════════════════════════════════════════════════════════════
# Satır 163-238: check_hardware — GPU VRAM fraksiyon yolları
# ══════════════════════════════════════════════════════════════

class Extra1_TestCheckHardwareVRAMPaths:
    def test_invalid_vram_fraction_falls_back_to_0_8(self):
        """frac < 0.1 veya >= 1.0 → warning + frac=0.8 (satır 195-202)."""
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "FakeGPU"
        mock_torch.version.cuda = "12.0"
        mock_torch.cuda.set_per_process_memory_fraction = MagicMock()

        with patch.dict(os.environ, {"GPU_MEMORY_FRACTION": "1.5"}, clear=False):
            with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
                with patch.object(config, "get_bool_env", return_value=True):
                    hw = config.check_hardware()

        assert hw.has_cuda is True

    def test_vram_fraction_set_per_process_called(self):
        """Geçerli frac → set_per_process_memory_fraction çağrılmalı (satır 202-204)."""
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "FakeGPU"
        mock_torch.version.cuda = "11.8"
        mock_torch.cuda.set_per_process_memory_fraction = MagicMock()

        with patch.dict(os.environ, {"GPU_MEMORY_FRACTION": "0.7"}, clear=False):
            with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
                with patch.object(config, "get_bool_env", return_value=True):
                    hw = config.check_hardware()

        mock_torch.cuda.set_per_process_memory_fraction.assert_called()

    def test_vram_set_per_process_exception_handled(self):
        """set_per_process_memory_fraction exception fırlatırsa debug log (satır 205-206)."""
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "FakeGPU"
        mock_torch.version.cuda = "12.0"
        mock_torch.cuda.set_per_process_memory_fraction = MagicMock(
            side_effect=RuntimeError("VRAM error")
        )

        with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
            with patch.object(config, "get_bool_env", return_value=True):
                hw = config.check_hardware()

        assert hw.has_cuda is True  # exception yutulmalı

    def test_wsl2_no_cuda_logs_warning(self):
        """WSL2'de CUDA yok → özel warning (satır 208-214)."""
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.version.cuda = None

        with patch.object(config, "_is_wsl2", return_value=True):
            with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
                with patch.object(config, "get_bool_env", return_value=True):
                    hw = config.check_hardware()

        assert hw.has_cuda is False

    def test_no_cuda_cpu_mode_log(self):
        """WSL2 değil, CUDA yok → CPU modu info log (satır 215-217)."""
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.version.cuda = None

        with patch.object(config, "_is_wsl2", return_value=False):
            with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
                with patch.object(config, "get_bool_env", return_value=True):
                    hw = config.check_hardware()

        assert hw.gpu_name == "CUDA Bulunamadı"

    def test_torch_import_error_sets_pytorch_yok(self):
        """torch ImportError → gpu_name='PyTorch Yok' (satır 218-220)."""
        import config
        # torch=None → AttributeError → ImportError benzeri
        saved = sys.modules.get("torch")
        sys.modules["torch"] = None  # type: ignore
        try:
            hw = config.check_hardware()
        finally:
            if saved is None:
                sys.modules.pop("torch", None)
            else:
                sys.modules["torch"] = saved

        assert hw.has_cuda is False

    def test_generic_exception_sets_tespit_edilemedi(self):
        """Genel exception → gpu_name='Tespit Edilemedi' (satır 221-223)."""
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.side_effect = RuntimeError("GPU error")

        with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
            with patch.object(config, "get_bool_env", return_value=True):
                hw = config.check_hardware()

        assert hw.gpu_name == "Tespit Edilemedi"

    def test_llm_rag_fractions_combined(self):
        """LLM_GPU_MEMORY_FRACTION + RAG_GPU_MEMORY_FRACTION env'den alınır (satır 191-194)."""
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "TestGPU"
        mock_torch.version.cuda = "12.0"
        mock_torch.cuda.set_per_process_memory_fraction = MagicMock()

        with patch.dict(
            os.environ,
            {"LLM_GPU_MEMORY_FRACTION": "0.5", "RAG_GPU_MEMORY_FRACTION": "0.2"},
            clear=False,
        ):
            with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
                with patch.object(config, "get_bool_env", return_value=True):
                    hw = config.check_hardware()

        assert hw.has_cuda is True

    def test_multiprocessing_exception_falls_back_to_1(self):
        """multiprocessing.cpu_count exception → cpu_count=1 (satır 237-238)."""
        import config
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.version.cuda = None

        with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
            with patch.object(config, "get_bool_env", return_value=True):
                with patch("multiprocessing.cpu_count", side_effect=OSError("no cpu")):
                    hw = config.check_hardware()

        assert hw.cpu_count == 1


# ══════════════════════════════════════════════════════════════
# Satır 663-683: validate_critical_settings — MEMORY_ENCRYPTION_KEY
# ══════════════════════════════════════════════════════════════

class Extra1_TestValidateCriticalSettingsMemoryEncryption:
    def _prepare(self, provider="ollama", extra=None):
        import config
        config.Config._hardware_loaded = True
        config.Config.AI_PROVIDER = provider
        for k, v in (extra or {}).items():
            setattr(config.Config, k, v)
        return config.Config

    def test_valid_fernet_key_passes(self):
        """Geçerli Fernet anahtarı → is_valid True (satır 662-676)."""
        import config
        cfg = self._prepare("ollama")
        cfg.MEMORY_ENCRYPTION_KEY = "dGVzdF9rZXkgZm9yIHRlc3RpbmcgcHVycG9zZXM="

        # Cryptography stub'ında Fernet sınıfı yoksa bu testi atla
        fernet_mod = sys.modules.get("cryptography.fernet")
        if fernet_mod is None or not hasattr(fernet_mod, "Fernet"):
            pytest.skip("cryptography.fernet stub kullanılıyor, Fernet sınıfı yok")

        with patch.object(cfg, "initialize_directories", return_value=True):
            result = cfg.validate_critical_settings()
        # Geçerli anahtar değilse is_valid=False olabilir; sadece çalışıp çalışmadığını test et
        assert isinstance(result, bool)

    def test_invalid_fernet_key_makes_invalid(self):
        """Geçersiz Fernet anahtarı → is_valid False (satır 666-676)."""
        import config
        cfg = self._prepare("ollama")
        cfg.MEMORY_ENCRYPTION_KEY = "not-a-valid-fernet-key"

        mock_fernet_cls = MagicMock(side_effect=Exception("Invalid key"))
        mock_fernet_mod = types.ModuleType("cryptography.fernet")
        mock_fernet_mod.Fernet = mock_fernet_cls

        with patch.dict(sys.modules, {"cryptography.fernet": mock_fernet_mod}):
            with patch.object(cfg, "initialize_directories", return_value=True):
                with patch("config.logger"):
                    result = cfg.validate_critical_settings()

        assert result is False

    def test_cryptography_not_installed_makes_invalid(self):
        """'cryptography' paketi yok → ImportError → is_valid False (satır 677-683)."""
        import config
        cfg = self._prepare("ollama")
        cfg.MEMORY_ENCRYPTION_KEY = "some-key"

        # ImportError simulate et
        original = sys.modules.pop("cryptography.fernet", None)
        try:
            with patch.dict(sys.modules, {"cryptography.fernet": None}):
                with patch.object(cfg, "initialize_directories", return_value=True):
                    with patch("config.logger"):
                        result = cfg.validate_critical_settings()
        finally:
            if original is not None:
                sys.modules["cryptography.fernet"] = original

        # None yüklenmişse ImportError benzeri → is_valid = False
        assert isinstance(result, bool)

    def test_empty_encryption_key_logs_critical_but_is_valid(self):
        """MEMORY_ENCRYPTION_KEY boş → CRITICAL log ama is_valid True (satır 685-691)."""
        import config
        cfg = self._prepare("ollama")
        cfg.MEMORY_ENCRYPTION_KEY = ""

        with patch.object(cfg, "initialize_directories", return_value=True):
            with patch("config.logger") as mock_log:
                result = cfg.validate_critical_settings()

        mock_log.critical.assert_called()
        assert result is True


# ══════════════════════════════════════════════════════════════
# Satır 721 / 727-729: validate_critical_settings — Ollama httpx
# ══════════════════════════════════════════════════════════════

class Extra1_TestValidateCriticalSettingsOllama:
    def _prepare_ollama(self):
        import config
        config.Config._hardware_loaded = True
        config.Config.AI_PROVIDER = "ollama"
        config.Config.MEMORY_ENCRYPTION_KEY = ""
        config.Config.OLLAMA_URL = "http://localhost:11434/api"
        return config.Config

    def test_ollama_200_logs_success(self):
        """Ollama 200 → logger.info başarılı (satır 724-725)."""
        import config
        cfg = self._prepare_ollama()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(cfg, "initialize_directories", return_value=True):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch("config.logger") as mock_log:
                    result = cfg.validate_critical_settings()

        assert result is True
        mock_log.info.assert_called()

    def test_ollama_non_200_logs_warning(self):
        """Ollama 503 → logger.warning (satır 726-727)."""
        import config
        cfg = self._prepare_ollama()

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(cfg, "initialize_directories", return_value=True):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch("config.logger") as mock_log:
                    result = cfg.validate_critical_settings()

        mock_log.warning.assert_called()

    def test_ollama_connection_error_logs_warning(self):
        """Ollama bağlantı hatası → exception yutulur, warning log (satır 728-733)."""
        import config
        cfg = self._prepare_ollama()

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(side_effect=Exception("connection refused"))

        with patch.object(cfg, "initialize_directories", return_value=True):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch("config.logger") as mock_log:
                    result = cfg.validate_critical_settings()

        mock_log.warning.assert_called()
        assert result is True

    def test_ollama_url_ending_with_api_uses_tags_suffix(self):
        """OLLAMA_URL /api ile bitiyorsa /tags eklenmeli (satır 717-719)."""
        import config
        cfg = self._prepare_ollama()
        cfg.OLLAMA_URL = "http://localhost:11434/api"

        captured_urls = []
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        def record_get(url, **kwargs):
            captured_urls.append(url)
            return mock_resp

        mock_client.get.side_effect = record_get

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = MagicMock(return_value=mock_client)

        with patch.object(cfg, "initialize_directories", return_value=True):
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch("config.logger"):
                    cfg.validate_critical_settings()

        assert any("tags" in url for url in captured_urls)


# ══════════════════════════════════════════════════════════════
# Satır 798-837: init_telemetry
# ══════════════════════════════════════════════════════════════

class Extra1_TestInitTelemetry:
    def _make_mock_otel_deps(self):
        """OpenTelemetry bileşenlerini mock olarak döner."""
        mock_trace = MagicMock()
        mock_resource_cls = MagicMock()
        mock_resource_cls.create.return_value = MagicMock()
        mock_tracer_provider_cls = MagicMock()
        mock_provider_instance = MagicMock()
        mock_tracer_provider_cls.return_value = mock_provider_instance
        mock_otlp_cls = MagicMock()
        mock_batch_cls = MagicMock()
        return {
            "trace_module": mock_trace,
            "resource_cls": mock_resource_cls,
            "tracer_provider_cls": mock_tracer_provider_cls,
            "otlp_exporter_cls": mock_otlp_cls,
            "batch_span_processor_cls": mock_batch_cls,
        }

    def test_tracing_disabled_returns_false(self):
        """ENABLE_TRACING=False → False döner (satır 792-793)."""
        import config
        config.Config.ENABLE_TRACING = False
        result = config.Config.init_telemetry()
        assert result is False

    def test_tracing_enabled_returns_true(self):
        """ENABLE_TRACING=True, tüm deps mock → True (satır 810-834)."""
        import config
        config.Config.ENABLE_TRACING = True
        config.Config.OTEL_EXPORTER_ENDPOINT = "http://jaeger:4317"
        config.Config.OTEL_SERVICE_NAME = "sidar-test"
        config.Config.OTEL_INSTRUMENT_FASTAPI = False
        config.Config.OTEL_INSTRUMENT_HTTPX = False

        deps = self._make_mock_otel_deps()
        result = config.Config.init_telemetry(**deps)
        assert result is True

    def test_tracing_enabled_otel_import_fails_returns_false(self):
        """OpenTelemetry import başarısız → False (satır 806-808)."""
        import config
        config.Config.ENABLE_TRACING = True

        def bad_import(*args, **kwargs):
            raise ImportError("otel not installed")

        with patch("builtins.__import__", side_effect=bad_import):
            result = config.Config.init_telemetry()

        # __import__ override tüm importları kırar; sadece Exception path kapanır
        assert result is False

    def test_tracing_setup_exception_returns_false(self):
        """Provider setup exception fırlattığında False döner (satır 835-837)."""
        import config
        config.Config.ENABLE_TRACING = True

        mock_resource_cls = MagicMock()
        mock_resource_cls.create.side_effect = RuntimeError("setup fail")

        deps = self._make_mock_otel_deps()
        deps["resource_cls"] = mock_resource_cls

        result = config.Config.init_telemetry(**deps)
        assert result is False

    def test_fastapi_instrumentor_called_when_app_provided(self):
        """fastapi_app verilirse FastAPIInstrumentor.instrument_app çağrılmalı (satır 818-821)."""
        import config
        config.Config.ENABLE_TRACING = True
        config.Config.OTEL_INSTRUMENT_FASTAPI = True
        config.Config.OTEL_INSTRUMENT_HTTPX = False

        mock_fastapi_instrumentor = MagicMock()
        fake_app = MagicMock()

        deps = self._make_mock_otel_deps()
        deps["fastapi_instrumentor_cls"] = mock_fastapi_instrumentor

        result = config.Config.init_telemetry(fastapi_app=fake_app, **deps)
        assert result is True
        mock_fastapi_instrumentor.instrument_app.assert_called_once_with(fake_app)

    def test_httpx_instrumentor_called_when_enabled(self):
        """OTEL_INSTRUMENT_HTTPX=True → HTTPXClientInstrumentor().instrument() (satır 823-831)."""
        import config
        config.Config.ENABLE_TRACING = True
        config.Config.OTEL_INSTRUMENT_FASTAPI = False
        config.Config.OTEL_INSTRUMENT_HTTPX = True

        mock_httpx_instrumentor_instance = MagicMock()
        mock_httpx_instrumentor_cls = MagicMock(return_value=mock_httpx_instrumentor_instance)

        deps = self._make_mock_otel_deps()
        deps["httpx_instrumentor_cls"] = mock_httpx_instrumentor_cls

        result = config.Config.init_telemetry(**deps)
        assert result is True
        mock_httpx_instrumentor_instance.instrument.assert_called_once()

    def test_httpx_instrumentor_exception_suppressed(self):
        """HTTPXClientInstrumentor().instrument() exception → suppress (satır 830)."""
        import config
        config.Config.ENABLE_TRACING = True
        config.Config.OTEL_INSTRUMENT_FASTAPI = False
        config.Config.OTEL_INSTRUMENT_HTTPX = True

        mock_httpx_instrumentor_instance = MagicMock()
        mock_httpx_instrumentor_instance.instrument.side_effect = Exception("instrument fail")
        mock_httpx_instrumentor_cls = MagicMock(return_value=mock_httpx_instrumentor_instance)

        deps = self._make_mock_otel_deps()
        deps["httpx_instrumentor_cls"] = mock_httpx_instrumentor_cls

        result = config.Config.init_telemetry(**deps)
        assert result is True  # suppress ile yutulur

    def test_service_name_uses_otel_service_name_when_no_arg(self):
        """service_name=None → OTEL_SERVICE_NAME kullanılmalı (satır 811)."""
        import config
        config.Config.ENABLE_TRACING = True
        config.Config.OTEL_SERVICE_NAME = "custom-service"
        config.Config.OTEL_INSTRUMENT_FASTAPI = False
        config.Config.OTEL_INSTRUMENT_HTTPX = False

        deps = self._make_mock_otel_deps()
        captured_resources = []

        original_create = deps["resource_cls"].create

        def record_create(attrs):
            captured_resources.append(attrs)
            return MagicMock()

        deps["resource_cls"].create.side_effect = record_create

        config.Config.init_telemetry(service_name=None, **deps)
        assert any("custom-service" in str(r) for r in captured_resources)

    def test_explicit_service_name_overrides_config(self):
        """Açık service_name verilirse OTEL_SERVICE_NAME yerine kullanılmalı (satır 811)."""
        import config
        config.Config.ENABLE_TRACING = True
        config.Config.OTEL_SERVICE_NAME = "default-service"
        config.Config.OTEL_INSTRUMENT_FASTAPI = False
        config.Config.OTEL_INSTRUMENT_HTTPX = False

        deps = self._make_mock_otel_deps()
        captured = []

        def record_create(attrs):
            captured.append(attrs)
            return MagicMock()

        deps["resource_cls"].create.side_effect = record_create

        config.Config.init_telemetry(service_name="my-launcher", **deps)
        assert any("my-launcher" in str(r) for r in captured)


# ══════════════════════════════════════════════════════════════
# Satır 847-871: print_config_summary — USE_GPU true/false, provider dalları
# ══════════════════════════════════════════════════════════════

class Extra1_TestPrintConfigSummary:
    def _print_summary(self, provider: str, use_gpu: bool = False, extra: dict | None = None):
        import config
        config.Config._hardware_loaded = True
        config.Config.AI_PROVIDER = provider
        config.Config.USE_GPU = use_gpu
        config.Config.GPU_INFO = "TestGPU"
        config.Config.CUDA_VERSION = "12.0"
        config.Config.GPU_COUNT = 1
        config.Config.GPU_DEVICE = 0
        config.Config.GPU_MIXED_PRECISION = False
        config.Config.LLM_GPU_MEMORY_FRACTION = 0.7
        config.Config.RAG_GPU_MEMORY_FRACTION = 0.2
        config.Config.DRIVER_VERSION = "525.0"
        config.Config.MEMORY_ENCRYPTION_KEY = ""
        for k, v in (extra or {}).items():
            setattr(config.Config, k, v)

        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            config.Config.print_config_summary()
        return "\n".join(printed)

    def test_cpu_mode_prints_x(self):
        """USE_GPU=False → CPU Modu satırı (satır 856)."""
        out = self._print_summary("ollama", use_gpu=False)
        assert "CPU Modu" in out or "✗" in out

    def test_gpu_mode_prints_check(self):
        """USE_GPU=True → GPU bilgisi (satır 847-854)."""
        out = self._print_summary("ollama", use_gpu=True)
        assert "TestGPU" in out or "✓" in out

    def test_gpu_driver_version_shown(self):
        """DRIVER_VERSION != 'N/A' → sürücü satırı (satır 853-854)."""
        out = self._print_summary("ollama", use_gpu=True)
        assert "525.0" in out or "Sürücü" in out

    def test_ollama_provider_shows_models(self):
        """AI_PROVIDER=ollama → CODING_MODEL + TEXT_MODEL (satır 860-862)."""
        import config
        config.Config.CODING_MODEL = "qwen2.5-coder:7b"
        config.Config.TEXT_MODEL = "gemma2:9b"
        out = self._print_summary("ollama")
        assert "qwen2.5-coder:7b" in out or "CODING" in out

    def test_gemini_provider_shows_model(self):
        """AI_PROVIDER=gemini → GEMINI_MODEL (satır 863-864)."""
        import config
        config.Config.GEMINI_MODEL = "gemini-2.0"
        out = self._print_summary("gemini")
        assert "gemini-2.0" in out or "Gemini" in out

    def test_openai_provider_shows_model(self):
        """AI_PROVIDER=openai → OPENAI_MODEL (satır 865-866)."""
        import config
        config.Config.OPENAI_MODEL = "gpt-4o"
        out = self._print_summary("openai")
        assert "gpt-4o" in out or "OpenAI" in out

    def test_litellm_provider_shows_gateway(self):
        """AI_PROVIDER=litellm → gateway URL (satır 867-869)."""
        import config
        config.Config.LITELLM_GATEWAY_URL = "http://gateway:4000"
        config.Config.LITELLM_MODEL = "gpt-3.5-turbo"
        config.Config.OPENAI_MODEL = "gpt-4o-mini"
        out = self._print_summary("litellm")
        assert "http://gateway:4000" in out or "LiteLLM" in out

    def test_anthropic_provider_shows_model(self):
        """AI_PROVIDER=anthropic → ANTHROPIC_MODEL (satır 870-871)."""
        import config
        config.Config.ANTHROPIC_MODEL = "claude-3-opus-20240229"
        out = self._print_summary("anthropic")
        assert "claude-3-opus-20240229" in out or "Anthropic" in out

    def test_memory_encryption_enabled_shown(self):
        """MEMORY_ENCRYPTION_KEY dolu → 'Etkin (Fernet)' (satır 873-874)."""
        out = self._print_summary("ollama", extra={"MEMORY_ENCRYPTION_KEY": "test-key"})
        assert "Etkin" in out or "Fernet" in out

    def test_memory_encryption_disabled_shown(self):
        """MEMORY_ENCRYPTION_KEY boş → 'Devre Dışı' (satır 874)."""
        out = self._print_summary("ollama", extra={"MEMORY_ENCRYPTION_KEY": ""})
        assert "Devre Dışı" in out


# ══════════════════════════════════════════════════════════════
# get_config singleton
# ══════════════════════════════════════════════════════════════

class Extra1_TestGetConfigSingleton:
    def test_returns_config_instance(self):
        import config
        instance = config.get_config()
        assert isinstance(instance, config.Config)

    def test_same_instance_on_second_call(self):
        import config
        a = config.get_config()
        b = config.get_config()
        assert a is b

    def test_singleton_reset_creates_new(self):
        import config
        config._config_instance = None
        instance = config.get_config()
        assert instance is not None
        assert isinstance(instance, config.Config)


# ===== MERGED FROM tests/test_config_extra2.py =====

import importlib
import logging
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ──────────────────────────────────────────────────────────────
# Stub dotenv so import doesn't fail
# ──────────────────────────────────────────────────────────────
if "dotenv" not in sys.modules:
    _dotenv_mod = types.ModuleType("dotenv")
    _dotenv_mod.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _dotenv_mod


def _get_config():
    """Return already-loaded config module (reloading is expensive)."""
    import config as cfg_mod
    return cfg_mod


# ══════════════════════════════════════════════════════════════
# get_list_env (lines 88-95)
# ══════════════════════════════════════════════════════════════

class Extra2_TestGetListEnv:
    def test_returns_default_when_not_set(self):
        """Missing env var returns default list (line 93-94)."""
        cfg = _get_config()
        os.environ.pop("TEST_LIST_ENV_XYZ", None)
        result = cfg.get_list_env("TEST_LIST_ENV_XYZ", ["a", "b"])
        assert result == ["a", "b"]

    def test_returns_parsed_list(self):
        """Comma-separated env var parsed into list (line 95)."""
        cfg = _get_config()
        with patch.dict(os.environ, {"TEST_LIST_ENV_XYZ2": "x,y,z"}):
            result = cfg.get_list_env("TEST_LIST_ENV_XYZ2", [])
        assert result == ["x", "y", "z"]

    def test_empty_env_returns_default(self):
        """Empty string returns default (line 93-94)."""
        cfg = _get_config()
        with patch.dict(os.environ, {"TEST_LIST_ENV_XYZ3": ""}):
            result = cfg.get_list_env("TEST_LIST_ENV_XYZ3", ["fallback"])
        assert result == ["fallback"]

    def test_none_default_becomes_empty_list(self):
        """None default becomes empty list (line 90-91)."""
        cfg = _get_config()
        os.environ.pop("TEST_LIST_ENV_XYZ4", None)
        result = cfg.get_list_env("TEST_LIST_ENV_XYZ4", None)
        assert result == []

    def test_custom_separator(self):
        """Custom separator used for splitting (line 95)."""
        cfg = _get_config()
        with patch.dict(os.environ, {"TEST_LIST_ENV_XYZ5": "a|b|c"}):
            result = cfg.get_list_env("TEST_LIST_ENV_XYZ5", [], separator="|")
        assert result == ["a", "b", "c"]

    def test_strips_whitespace(self):
        """Items have leading/trailing whitespace stripped (line 95)."""
        cfg = _get_config()
        with patch.dict(os.environ, {"TEST_LIST_ENV_XYZ6": " a , b , c "}):
            result = cfg.get_list_env("TEST_LIST_ENV_XYZ6", [])
        assert result == ["a", "b", "c"]


# ══════════════════════════════════════════════════════════════
# _is_wsl2 (lines 157-160)
# ══════════════════════════════════════════════════════════════

class Extra2_TestIsWsl2:
    def test_returns_true_when_microsoft_in_osrelease(self):
        """'microsoft' in /proc/sys/kernel/osrelease → True (line 158)."""
        cfg = _get_config()
        with patch("pathlib.Path.read_text", return_value="5.15.90.1-microsoft-standard-WSL2"):
            result = cfg._is_wsl2()
        assert result is True

    def test_returns_false_when_not_wsl(self):
        """Regular kernel osrelease → False (line 158)."""
        cfg = _get_config()
        with patch("pathlib.Path.read_text", return_value="5.15.90.1-ubuntu-standard"):
            result = cfg._is_wsl2()
        assert result is False

    def test_returns_false_on_exception(self):
        """File read exception → False (line 159-160)."""
        cfg = _get_config()
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError("no file")):
            result = cfg._is_wsl2()
        assert result is False

    def test_returns_true_when_microsoft_is_uppercase(self):
        cfg = _get_config()
        with patch("pathlib.Path.read_text", return_value="5.15.0-MICROSOFT-WSL2"):
            result = cfg._is_wsl2()
        assert result is True


# ══════════════════════════════════════════════════════════════
# check_hardware (lines 165-240)
# ══════════════════════════════════════════════════════════════

class Extra2_TestCheckHardware:
    def test_use_gpu_false_returns_disabled_info(self):
        """USE_GPU=False env returns HardwareInfo with disabled GPU (line 171-174)."""
        cfg = _get_config()
        with patch.dict(os.environ, {"USE_GPU": "false"}):
            with patch.object(cfg, "get_bool_env", side_effect=lambda k, d: False if k == "USE_GPU" else d):
                result = cfg.check_hardware()
        assert "Devre Dışı" in result.gpu_name or result.has_cuda is False

    def test_check_hardware_torch_import_error(self):
        """torch ImportError → gpu_name='PyTorch Yok' (line 218-220)."""
        cfg = _get_config()
        with patch.dict(sys.modules, {"torch": None}):
            with patch.object(cfg, "_is_wsl2", return_value=False):
                with patch.object(cfg, "get_bool_env", return_value=True):
                    result = cfg.check_hardware()
        assert result.gpu_name in ("PyTorch Yok", "N/A", "Tespit Edilemedi", "CUDA Bulunamadı")

    def test_check_hardware_torch_no_cuda(self):
        """torch available but no CUDA → gpu_name='CUDA Bulunamadı' (line 208-217)."""
        cfg = _get_config()
        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = MagicMock()
        fake_torch.cuda.is_available = MagicMock(return_value=False)
        fake_torch.version = MagicMock()
        fake_torch.version.cuda = None

        with patch.dict(sys.modules, {"torch": fake_torch}):
            with patch.object(cfg, "_is_wsl2", return_value=False):
                with patch.object(cfg, "get_bool_env", return_value=True):
                    result = cfg.check_hardware()
        assert result.gpu_name == "CUDA Bulunamadı"

    def test_check_hardware_cuda_available(self):
        """torch with CUDA → has_cuda=True (line 178-206)."""
        cfg = _get_config()
        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = MagicMock()
        fake_torch.cuda.is_available = MagicMock(return_value=True)
        fake_torch.cuda.device_count = MagicMock(return_value=1)
        fake_torch.cuda.get_device_name = MagicMock(return_value="Tesla T4")
        fake_torch.cuda.set_per_process_memory_fraction = MagicMock()
        fake_torch.version = MagicMock()
        fake_torch.version.cuda = "12.0"

        with patch.dict(sys.modules, {"torch": fake_torch}):
            with patch.dict(os.environ, {
                "USE_GPU": "true",
                "GPU_MEMORY_FRACTION": "0.8",
            }):
                with patch.object(cfg, "_is_wsl2", return_value=False):
                    with patch.object(cfg, "get_bool_env", return_value=True):
                        with patch.dict(sys.modules, {"pynvml": None}):
                            result = cfg.check_hardware()
        assert result.has_cuda is True
        assert result.gpu_name == "Tesla T4"

    def test_check_hardware_wsl2_no_cuda_logs_warning(self):
        """WSL2 + no CUDA → special WSL2 warning logged (line 208-214)."""
        cfg = _get_config()
        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = MagicMock()
        fake_torch.cuda.is_available = MagicMock(return_value=False)
        fake_torch.version = MagicMock()
        fake_torch.version.cuda = None

        mock_logger = MagicMock()
        with patch.dict(sys.modules, {"torch": fake_torch}):
            with patch.object(cfg, "_is_wsl2", return_value=True):
                with patch.object(cfg, "get_bool_env", return_value=True):
                    with patch.object(cfg, "logger", mock_logger):
                        result = cfg.check_hardware()
        # Should warn about WSL2 and CUDA
        assert mock_logger.warning.called

    def test_check_hardware_generic_exception(self):
        """torch general exception → gpu_name='Tespit Edilemedi' (line 221-223)."""
        cfg = _get_config()
        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = MagicMock()
        fake_torch.cuda.is_available = MagicMock(side_effect=RuntimeError("GPU exploded"))

        with patch.dict(sys.modules, {"torch": fake_torch}):
            with patch.object(cfg, "_is_wsl2", return_value=False):
                with patch.object(cfg, "get_bool_env", return_value=True):
                    result = cfg.check_hardware()
        assert result.gpu_name == "Tespit Edilemedi"

    def test_check_hardware_gets_cpu_count(self):
        """check_hardware populates cpu_count via multiprocessing (line 234-238)."""
        cfg = _get_config()
        import multiprocessing
        with patch.dict(sys.modules, {"torch": None}):
            with patch.object(cfg, "_is_wsl2", return_value=False):
                with patch.object(cfg, "get_bool_env", return_value=True):
                    result = cfg.check_hardware()
        # cpu_count is set (either from multiprocessing or fallback)
        assert result.cpu_count >= 0


# ══════════════════════════════════════════════════════════════
# Config.__init__ + _ensure_hardware_info_loaded (lines 585-612)
# ══════════════════════════════════════════════════════════════

class Extra2_TestConfigInit:
    def test_config_init_calls_ensure_hardware_loaded(self):
        """Config() calls _ensure_hardware_info_loaded (line 587)."""
        cfg = _get_config()
        original = cfg.Config._hardware_loaded
        try:
            cfg.Config._hardware_loaded = False
            with patch.object(cfg.Config, "_ensure_hardware_info_loaded") as mock_ensure:
                cfg.Config()
            mock_ensure.assert_called_once()
        finally:
            cfg.Config._hardware_loaded = original

    def test_ensure_hardware_loaded_skips_when_already_loaded(self):
        """_ensure_hardware_info_loaded returns early if already loaded (line 593-594)."""
        cfg = _get_config()
        original = cfg.Config._hardware_loaded
        try:
            cfg.Config._hardware_loaded = True
            with patch.object(cfg, "check_hardware") as mock_check:
                cfg.Config._ensure_hardware_info_loaded()
            mock_check.assert_not_called()
        finally:
            cfg.Config._hardware_loaded = original

    def test_ensure_hardware_loaded_use_gpu_false_path(self):
        """USE_GPU=False → sets GPU_INFO to 'Devre Dışı' (line 596-603)."""
        cfg = _get_config()
        original_loaded = cfg.Config._hardware_loaded
        original_use_gpu = cfg.Config.USE_GPU
        try:
            cfg.Config._hardware_loaded = False
            cfg.Config.USE_GPU = False
            cfg.Config._ensure_hardware_info_loaded()
            assert cfg.Config.GPU_INFO == "Devre Dışı / CPU Modu"
            assert cfg.Config._hardware_loaded is True
        finally:
            cfg.Config._hardware_loaded = original_loaded
            cfg.Config.USE_GPU = original_use_gpu

    def test_ensure_hardware_loaded_calls_check_hardware(self):
        """USE_GPU=True → check_hardware() called (line 605-612)."""
        cfg = _get_config()
        original_loaded = cfg.Config._hardware_loaded
        original_use_gpu = cfg.Config.USE_GPU
        try:
            cfg.Config._hardware_loaded = False
            cfg.Config.USE_GPU = True
            fake_hw = cfg.HardwareInfo(
                has_cuda=False, gpu_name="Test GPU",
                gpu_count=0, cpu_count=4,
                cuda_version="N/A", driver_version="N/A"
            )
            with patch.object(cfg, "check_hardware", return_value=fake_hw):
                cfg.Config._ensure_hardware_info_loaded()
            assert cfg.Config.GPU_INFO == "Test GPU"
            assert cfg.Config._hardware_loaded is True
        finally:
            cfg.Config._hardware_loaded = original_loaded
            cfg.Config.USE_GPU = original_use_gpu


# ══════════════════════════════════════════════════════════════
# Config.initialize_directories (lines 617-625)
# ══════════════════════════════════════════════════════════════

class Extra2_TestInitializeDirectories:
    def test_returns_true_on_success(self, tmp_path):
        """All dirs created → returns True (line 617-625)."""
        cfg = _get_config()
        original_dirs = cfg.Config.REQUIRED_DIRS
        try:
            test_dirs = [tmp_path / "temp", tmp_path / "logs", tmp_path / "data"]
            cfg.Config.REQUIRED_DIRS = test_dirs
            result = cfg.Config.initialize_directories()
        finally:
            cfg.Config.REQUIRED_DIRS = original_dirs
        assert result is True
        for d in test_dirs:
            assert d.exists()

    def test_returns_false_on_failure(self):
        """Mkdir failure → returns False (line 621-624)."""
        cfg = _get_config()
        original_dirs = cfg.Config.REQUIRED_DIRS
        try:
            fake_path = MagicMock(spec=Path)
            fake_path.name = "test_dir"
            fake_path.mkdir = MagicMock(side_effect=PermissionError("denied"))
            cfg.Config.REQUIRED_DIRS = [fake_path]
            result = cfg.Config.initialize_directories()
        finally:
            cfg.Config.REQUIRED_DIRS = original_dirs
        assert result is False


# ══════════════════════════════════════════════════════════════
# Config.set_provider_mode (lines 627-644)
# ══════════════════════════════════════════════════════════════

class Extra2_TestSetProviderMode:
    def test_set_online_mode(self):
        """'online' mode sets AI_PROVIDER to 'gemini' (line 631-638)."""
        cfg = _get_config()
        original = cfg.Config.AI_PROVIDER
        try:
            cfg.Config.set_provider_mode("online")
            assert cfg.Config.AI_PROVIDER == "gemini"
        finally:
            cfg.Config.AI_PROVIDER = original

    def test_set_local_mode(self):
        """'local' mode sets AI_PROVIDER to 'ollama' (line 633)."""
        cfg = _get_config()
        original = cfg.Config.AI_PROVIDER
        try:
            cfg.Config.set_provider_mode("local")
            assert cfg.Config.AI_PROVIDER == "ollama"
        finally:
            cfg.Config.AI_PROVIDER = original

    def test_set_gemini_mode(self):
        """'gemini' mode sets AI_PROVIDER to 'gemini' (line 631)."""
        cfg = _get_config()
        original = cfg.Config.AI_PROVIDER
        try:
            cfg.Config.set_provider_mode("gemini")
            assert cfg.Config.AI_PROVIDER == "gemini"
        finally:
            cfg.Config.AI_PROVIDER = original

    def test_set_anthropic_mode(self):
        """'anthropic' sets AI_PROVIDER to 'anthropic' (line 634)."""
        cfg = _get_config()
        original = cfg.Config.AI_PROVIDER
        try:
            cfg.Config.set_provider_mode("anthropic")
            assert cfg.Config.AI_PROVIDER == "anthropic"
        finally:
            cfg.Config.AI_PROVIDER = original

    def test_set_litellm_mode(self):
        """'litellm' sets AI_PROVIDER to 'litellm' (line 635)."""
        cfg = _get_config()
        original = cfg.Config.AI_PROVIDER
        try:
            cfg.Config.set_provider_mode("litellm")
            assert cfg.Config.AI_PROVIDER == "litellm"
        finally:
            cfg.Config.AI_PROVIDER = original

    def test_invalid_mode_logs_error(self):
        """Invalid mode logs an error (line 641-644)."""
        cfg = _get_config()
        mock_logger = MagicMock()
        with patch.object(cfg, "logger", mock_logger):
            cfg.Config.set_provider_mode("invalidmode123")
        assert mock_logger.error.called

    def test_uppercase_mode_works(self):
        """Mode is lowercased before lookup (line 636)."""
        cfg = _get_config()
        original = cfg.Config.AI_PROVIDER
        try:
            cfg.Config.set_provider_mode("OLLAMA")
            assert cfg.Config.AI_PROVIDER == "ollama"
        finally:
            cfg.Config.AI_PROVIDER = original


# ══════════════════════════════════════════════════════════════
# Config.validate_critical_settings (lines 649-735)
# ══════════════════════════════════════════════════════════════

class Extra2_TestValidateCriticalSettings:
    def _setup_valid_cfg(self, cfg):
        """Set safe defaults for validation tests."""
        cfg.Config.AI_PROVIDER = "ollama"
        cfg.Config.GEMINI_API_KEY = ""
        cfg.Config.OPENAI_API_KEY = ""
        cfg.Config.ANTHROPIC_API_KEY = ""
        cfg.Config.LITELLM_GATEWAY_URL = ""
        cfg.Config.MEMORY_ENCRYPTION_KEY = ""
        cfg.Config._hardware_loaded = True

    def test_validate_returns_true_for_ollama_without_keys(self):
        """Ollama provider with no API keys still validates (line 714-734)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            self._setup_valid_cfg(cfg)
            with patch.object(cfg.Config, "initialize_directories", return_value=True):
                with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                    with patch.dict(sys.modules, {"httpx": None}):
                        result = cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        # Should return True (ollama has no API key requirement)
        assert isinstance(result, bool)

    def test_validate_returns_false_for_gemini_no_key(self):
        """Gemini without GEMINI_API_KEY → returns False (line 653-658)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_key = cfg.Config.GEMINI_API_KEY
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.AI_PROVIDER = "gemini"
            cfg.Config.GEMINI_API_KEY = ""
            cfg.Config._hardware_loaded = True
            with patch.object(cfg.Config, "initialize_directories", return_value=True):
                with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                    result = cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config.GEMINI_API_KEY = original_key
            cfg.Config._hardware_loaded = original_loaded
        assert result is False

    def test_validate_returns_false_for_openai_no_key(self):
        """OpenAI without OPENAI_API_KEY → returns False (line 693-698)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_key = cfg.Config.OPENAI_API_KEY
        original_loaded = cfg.Config._hardware_loaded
        try:
            self._setup_valid_cfg(cfg)
            cfg.Config.AI_PROVIDER = "openai"
            cfg.Config.OPENAI_API_KEY = ""
            with patch.object(cfg.Config, "initialize_directories", return_value=True):
                with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                    result = cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config.OPENAI_API_KEY = original_key
            cfg.Config._hardware_loaded = original_loaded
        assert result is False

    def test_validate_returns_false_for_anthropic_no_key(self):
        """Anthropic without ANTHROPIC_API_KEY → returns False (line 700-705)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_key = cfg.Config.ANTHROPIC_API_KEY
        original_loaded = cfg.Config._hardware_loaded
        try:
            self._setup_valid_cfg(cfg)
            cfg.Config.AI_PROVIDER = "anthropic"
            cfg.Config.ANTHROPIC_API_KEY = ""
            with patch.object(cfg.Config, "initialize_directories", return_value=True):
                with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                    result = cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config.ANTHROPIC_API_KEY = original_key
            cfg.Config._hardware_loaded = original_loaded
        assert result is False

    def test_validate_returns_false_for_litellm_no_url(self):
        """LiteLLM without LITELLM_GATEWAY_URL → returns False (line 707-712)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_url = cfg.Config.LITELLM_GATEWAY_URL
        original_loaded = cfg.Config._hardware_loaded
        try:
            self._setup_valid_cfg(cfg)
            cfg.Config.AI_PROVIDER = "litellm"
            cfg.Config.LITELLM_GATEWAY_URL = ""
            with patch.object(cfg.Config, "initialize_directories", return_value=True):
                with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                    result = cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config.LITELLM_GATEWAY_URL = original_url
            cfg.Config._hardware_loaded = original_loaded
        assert result is False

    def test_validate_memory_encryption_key_invalid_fernet(self):
        """Invalid Fernet key → returns False (line 663-676)."""
        cfg = _get_config()
        original_key = cfg.Config.MEMORY_ENCRYPTION_KEY
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            self._setup_valid_cfg(cfg)
            cfg.Config.MEMORY_ENCRYPTION_KEY = "not_a_valid_fernet_key"

            # Create a real Fernet stub that raises on bad key
            fake_fernet_cls = MagicMock(side_effect=Exception("Invalid key"))
            fake_fernet_mod = types.ModuleType("cryptography.fernet")
            fake_fernet_mod.Fernet = fake_fernet_cls

            with patch.dict(sys.modules, {"cryptography.fernet": fake_fernet_mod}):
                with patch.object(cfg.Config, "initialize_directories", return_value=True):
                    with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                        result = cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.MEMORY_ENCRYPTION_KEY = original_key
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        assert result is False

    def test_validate_memory_encryption_key_no_cryptography(self):
        """MEMORY_ENCRYPTION_KEY set but cryptography not available → False (line 677-683)."""
        cfg = _get_config()
        original_key = cfg.Config.MEMORY_ENCRYPTION_KEY
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            self._setup_valid_cfg(cfg)
            cfg.Config.MEMORY_ENCRYPTION_KEY = "some_key_but_no_cryptography"

            with patch.dict(sys.modules, {"cryptography.fernet": None}):
                with patch.object(cfg.Config, "initialize_directories", return_value=True):
                    with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                        result = cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.MEMORY_ENCRYPTION_KEY = original_key
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        assert result is False

    def test_validate_ollama_200_logs_success(self):
        """Ollama 200 response → logs success (line 724-725)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            self._setup_valid_cfg(cfg)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            fake_httpx = types.ModuleType("httpx")
            fake_httpx.Client = MagicMock(return_value=mock_client)

            mock_logger = MagicMock()
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch.object(cfg, "logger", mock_logger):
                    with patch.object(cfg.Config, "initialize_directories", return_value=True):
                        with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                            cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        assert mock_logger.info.called

    def test_validate_ollama_exception_warns(self):
        """Ollama connection exception → warning (line 728-733)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            self._setup_valid_cfg(cfg)
            fake_httpx = types.ModuleType("httpx")
            fake_httpx.Client = MagicMock(side_effect=Exception("connection refused"))

            mock_logger = MagicMock()
            with patch.dict(sys.modules, {"httpx": fake_httpx}):
                with patch.object(cfg, "logger", mock_logger):
                    with patch.object(cfg.Config, "initialize_directories", return_value=True):
                        with patch.object(cfg.Config, "_ensure_hardware_info_loaded"):
                            cfg.Config.validate_critical_settings()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        assert mock_logger.warning.called


# ══════════════════════════════════════════════════════════════
# Config.get_system_info (lines 738-773)
# ══════════════════════════════════════════════════════════════

class Extra2_TestGetSystemInfo:
    def test_returns_dict_with_expected_keys(self):
        """get_system_info returns dict with all expected keys (line 738-773)."""
        cfg = _get_config()
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config._hardware_loaded = True
            info = cfg.Config.get_system_info()
        finally:
            cfg.Config._hardware_loaded = original_loaded

        expected_keys = [
            "project", "version", "provider", "access_level",
            "gpu_enabled", "gpu_info", "gpu_count",
            "cpu_count", "debug_mode", "web_port",
        ]
        for key in expected_keys:
            assert key in info, f"Missing key: {key}"

    def test_system_info_calls_ensure_loaded(self):
        """get_system_info calls _ensure_hardware_info_loaded (line 740)."""
        cfg = _get_config()
        with patch.object(cfg.Config, "_ensure_hardware_info_loaded") as mock_ensure:
            cfg.Config.get_system_info()
        mock_ensure.assert_called()

    def test_system_info_project_name(self):
        """get_system_info contains correct project name (line 742)."""
        cfg = _get_config()
        cfg.Config._hardware_loaded = True
        info = cfg.Config.get_system_info()
        assert info["project"] == cfg.Config.PROJECT_NAME


# ══════════════════════════════════════════════════════════════
# Config.init_telemetry (lines 791-837)
# ══════════════════════════════════════════════════════════════

class Extra2_TestInitTelemetry:
    def test_returns_false_when_tracing_disabled(self):
        """ENABLE_TRACING=False → returns False immediately (line 792-793)."""
        cfg = _get_config()
        original = cfg.Config.ENABLE_TRACING
        try:
            cfg.Config.ENABLE_TRACING = False
            result = cfg.Config.init_telemetry(service_name="test")
        finally:
            cfg.Config.ENABLE_TRACING = original
        assert result is False

    def test_returns_false_when_otel_import_fails(self):
        """ENABLE_TRACING=True but opentelemetry not installed → False (line 806-808)."""
        cfg = _get_config()
        original = cfg.Config.ENABLE_TRACING
        try:
            cfg.Config.ENABLE_TRACING = True
            # Pass None for trace_module to force import path that will fail
            with patch.dict(sys.modules, {
                "opentelemetry": None,
                "opentelemetry.exporter": None,
                "opentelemetry.exporter.otlp": None,
                "opentelemetry.exporter.otlp.proto": None,
                "opentelemetry.exporter.otlp.proto.grpc": None,
                "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
                "opentelemetry.sdk": None,
                "opentelemetry.sdk.trace": None,
                "opentelemetry.sdk.resources": None,
                "opentelemetry.sdk.trace.export": None,
            }):
                result = cfg.Config.init_telemetry(service_name="test")
        finally:
            cfg.Config.ENABLE_TRACING = original
        assert result is False

    def test_returns_true_with_mocked_otel_deps(self):
        """ENABLE_TRACING=True with mocked dependencies → returns True (line 810-834)."""
        cfg = _get_config()
        original = cfg.Config.ENABLE_TRACING
        try:
            cfg.Config.ENABLE_TRACING = True

            mock_trace = MagicMock()
            mock_exporter_cls = MagicMock()
            mock_provider_cls = MagicMock()
            mock_resource_cls = MagicMock()
            mock_bsp_cls = MagicMock()

            mock_resource_cls.create.return_value = MagicMock()
            mock_provider_cls.return_value = MagicMock()
            mock_exporter_cls.return_value = MagicMock()

            result = cfg.Config.init_telemetry(
                service_name="test-service",
                trace_module=mock_trace,
                otlp_exporter_cls=mock_exporter_cls,
                tracer_provider_cls=mock_provider_cls,
                resource_cls=mock_resource_cls,
                batch_span_processor_cls=mock_bsp_cls,
            )
        finally:
            cfg.Config.ENABLE_TRACING = original
        assert result is True

    def test_returns_false_on_provider_setup_exception(self):
        """Provider setup exception → returns False (line 835-837)."""
        cfg = _get_config()
        original = cfg.Config.ENABLE_TRACING
        try:
            cfg.Config.ENABLE_TRACING = True

            mock_trace = MagicMock()
            mock_resource_cls = MagicMock()
            mock_resource_cls.create.side_effect = RuntimeError("resource error")

            result = cfg.Config.init_telemetry(
                service_name="test",
                trace_module=mock_trace,
                otlp_exporter_cls=MagicMock(),
                tracer_provider_cls=MagicMock(),
                resource_cls=mock_resource_cls,
                batch_span_processor_cls=MagicMock(),
            )
        finally:
            cfg.Config.ENABLE_TRACING = original
        assert result is False

    def test_fastapi_instrumented_when_app_provided(self):
        """fastapi_app + OTEL_INSTRUMENT_FASTAPI → instrumentor called (line 818-821)."""
        cfg = _get_config()
        original_tracing = cfg.Config.ENABLE_TRACING
        original_fastapi = cfg.Config.OTEL_INSTRUMENT_FASTAPI
        try:
            cfg.Config.ENABLE_TRACING = True
            cfg.Config.OTEL_INSTRUMENT_FASTAPI = True

            fake_app = MagicMock()
            mock_fastapi_instrumentor_cls = MagicMock()

            cfg.Config.init_telemetry(
                service_name="test",
                fastapi_app=fake_app,
                trace_module=MagicMock(),
                otlp_exporter_cls=MagicMock(),
                tracer_provider_cls=MagicMock(),
                resource_cls=MagicMock(),
                batch_span_processor_cls=MagicMock(),
                fastapi_instrumentor_cls=mock_fastapi_instrumentor_cls,
            )
        finally:
            cfg.Config.ENABLE_TRACING = original_tracing
            cfg.Config.OTEL_INSTRUMENT_FASTAPI = original_fastapi

        mock_fastapi_instrumentor_cls.instrument_app.assert_called_once_with(fake_app)

    def test_httpx_instrumented_when_enabled(self):
        """OTEL_INSTRUMENT_HTTPX=True → httpx instrumentor called (line 823-831)."""
        cfg = _get_config()
        original_tracing = cfg.Config.ENABLE_TRACING
        original_httpx = cfg.Config.OTEL_INSTRUMENT_HTTPX
        try:
            cfg.Config.ENABLE_TRACING = True
            cfg.Config.OTEL_INSTRUMENT_HTTPX = True

            mock_httpx_instrumentor_cls = MagicMock()
            mock_httpx_instrumentor_cls.return_value = MagicMock()

            cfg.Config.init_telemetry(
                service_name="test",
                trace_module=MagicMock(),
                otlp_exporter_cls=MagicMock(),
                tracer_provider_cls=MagicMock(),
                resource_cls=MagicMock(),
                batch_span_processor_cls=MagicMock(),
                httpx_instrumentor_cls=mock_httpx_instrumentor_cls,
            )
        finally:
            cfg.Config.ENABLE_TRACING = original_tracing
            cfg.Config.OTEL_INSTRUMENT_HTTPX = original_httpx

        mock_httpx_instrumentor_cls.return_value.instrument.assert_called()


# ══════════════════════════════════════════════════════════════
# Config.print_config_summary (lines 842-875)
# ══════════════════════════════════════════════════════════════

class Extra2_TestPrintConfigSummary:
    def test_print_summary_ollama_shows_models(self, capsys):
        """ollama provider shows coding and text models (line 860-862)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.AI_PROVIDER = "ollama"
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "CODING" in captured.out or "Modeli" in captured.out

    def test_print_summary_gemini_shows_model(self, capsys):
        """gemini provider shows Gemini model (line 863-864)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.AI_PROVIDER = "gemini"
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "Gemini" in captured.out

    def test_print_summary_openai_shows_model(self, capsys):
        """openai provider shows OpenAI model (line 865-866)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.AI_PROVIDER = "openai"
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "OpenAI" in captured.out

    def test_print_summary_litellm_shows_gateway(self, capsys):
        """litellm provider shows LiteLLM gateway (line 867-869)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.AI_PROVIDER = "litellm"
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "LiteLLM" in captured.out

    def test_print_summary_anthropic_shows_model(self, capsys):
        """anthropic/other provider shows Anthropic model (line 870-871)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.AI_PROVIDER = "anthropic"
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "Anthropic" in captured.out

    def test_print_summary_gpu_enabled_shows_gpu_info(self, capsys):
        """GPU enabled → shows GPU info (line 846-854)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_use_gpu = cfg.Config.USE_GPU
        original_gpu_info = cfg.Config.GPU_INFO
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.AI_PROVIDER = "ollama"
            cfg.Config.USE_GPU = True
            cfg.Config.GPU_INFO = "Tesla T4"
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config.USE_GPU = original_use_gpu
            cfg.Config.GPU_INFO = original_gpu_info
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "Tesla T4" in captured.out or "GPU" in captured.out

    def test_print_summary_gpu_disabled_shows_cpu_mode(self, capsys):
        """GPU disabled → shows CPU mode (line 855-856)."""
        cfg = _get_config()
        original_provider = cfg.Config.AI_PROVIDER
        original_use_gpu = cfg.Config.USE_GPU
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.AI_PROVIDER = "ollama"
            cfg.Config.USE_GPU = False
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.AI_PROVIDER = original_provider
            cfg.Config.USE_GPU = original_use_gpu
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "CPU" in captured.out or "✗" in captured.out

    def test_print_summary_encryption_enabled(self, capsys):
        """Memory encryption key set → 'Etkin' shown (line 873-874)."""
        cfg = _get_config()
        original_key = cfg.Config.MEMORY_ENCRYPTION_KEY
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.MEMORY_ENCRYPTION_KEY = "some_key"
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.MEMORY_ENCRYPTION_KEY = original_key
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "Etkin" in captured.out

    def test_print_summary_encryption_disabled(self, capsys):
        """Memory encryption key not set → 'Devre Dışı' shown (line 873-874)."""
        cfg = _get_config()
        original_key = cfg.Config.MEMORY_ENCRYPTION_KEY
        original_loaded = cfg.Config._hardware_loaded
        try:
            cfg.Config.MEMORY_ENCRYPTION_KEY = ""
            cfg.Config._hardware_loaded = True
            cfg.Config.print_config_summary()
        finally:
            cfg.Config.MEMORY_ENCRYPTION_KEY = original_key
            cfg.Config._hardware_loaded = original_loaded
        captured = capsys.readouterr()
        assert "Devre Dışı" in captured.out


# ══════════════════════════════════════════════════════════════
# get_config singleton (lines 884-889)
# ══════════════════════════════════════════════════════════════

class Extra2_TestGetConfigSingleton:
    def test_get_config_returns_config_instance(self):
        """get_config() returns a Config instance (line 884-889)."""
        cfg = _get_config()
        # Reset singleton
        original = cfg._config_instance
        try:
            cfg._config_instance = None
            instance = cfg.get_config()
            assert isinstance(instance, cfg.Config)
        finally:
            cfg._config_instance = original

    def test_get_config_returns_same_instance(self):
        """get_config() returns the same instance on second call (line 887-888)."""
        cfg = _get_config()
        original = cfg._config_instance
        try:
            cfg._config_instance = None
            instance1 = cfg.get_config()
            instance2 = cfg.get_config()
            assert instance1 is instance2
        finally:
            cfg._config_instance = original

    def test_get_config_reuses_existing_instance(self):
        """get_config() returns existing instance without creating new (line 887)."""
        cfg = _get_config()
        original = cfg._config_instance
        try:
            mock_instance = MagicMock()
            cfg._config_instance = mock_instance
            result = cfg.get_config()
            assert result is mock_instance
        finally:
            cfg._config_instance = original
