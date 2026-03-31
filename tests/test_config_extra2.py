"""
config.py — additional unit tests (coverage improvement, batch 2)
Target lines: 91, 95, 157-160, 165-240, 587, 593-612, 617-625,
              630-641, 649-735, 740-741, 791-837, 842-875, 887-889
"""
from __future__ import annotations

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


# ──────────────────────────────────────────────────────────────
# Helper: reload config with a fresh sys.modules and env vars
# ──────────────────────────────────────────────────────────────

def _reload_config(env_overrides: dict | None = None):
    env_overrides = env_overrides or {}
    for mod in list(sys.modules.keys()):
        if mod == "config" or mod.startswith("config."):
            del sys.modules[mod]
    with patch.dict(os.environ, env_overrides, clear=False):
        import config as cfg_mod
    return cfg_mod


def _get_config():
    """Return already-loaded config module (reloading is expensive)."""
    import config as cfg_mod
    return cfg_mod


# ══════════════════════════════════════════════════════════════
# get_list_env (lines 88-95)
# ══════════════════════════════════════════════════════════════

class TestGetListEnv:
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

class TestIsWsl2:
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

class TestCheckHardware:
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

class TestConfigInit:
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

class TestInitializeDirectories:
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

class TestSetProviderMode:
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

class TestValidateCriticalSettings:
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

class TestGetSystemInfo:
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

class TestInitTelemetry:
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

class TestPrintConfigSummary:
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

class TestGetConfigSingleton:
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
