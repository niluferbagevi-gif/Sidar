"""
tests/test_config.py
====================
config.py modülünün birim testleri.

Kapsanan birimler:
  • get_bool_env()      — ortam değişkeninden bool okuma
  • get_int_env()       — ortam değişkeninden int okuma
  • get_float_env()     — ortam değişkeninden float okuma
  • get_list_env()      — ortam değişkeninden liste okuma
  • HardwareInfo        — donanım bilgisi dataclass'ı
  • _is_wsl2()          — WSL2 ortam tespiti
  • check_hardware()    — GPU/CPU tespiti (torch/pynvml mock'lu)
  • Config              — merkezi yapılandırma sınıfı (varsayılanlar + env override)
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# YARDIMCI: config modülünü temiz ortamda yeniden yükle
# ─────────────────────────────────────────────────────────────────────────────

def _reload_config():
    """sys.modules önbelleğini atlayarak config modülünü taze yükle."""
    sys.modules.pop("config", None)
    return importlib.import_module("config")


# ─────────────────────────────────────────────────────────────────────────────
# get_bool_env
# ─────────────────────────────────────────────────────────────────────────────

class TestGetBoolEnv:
    """get_bool_env() fonksiyonu testleri."""

    def test_varsayilan_false_doner(self, monkeypatch):
        monkeypatch.delenv("TEST_BOOL", raising=False)
        cfg = _reload_config()
        assert cfg.get_bool_env("TEST_BOOL", False) is False

    def test_varsayilan_true_doner(self, monkeypatch):
        monkeypatch.delenv("TEST_BOOL", raising=False)
        cfg = _reload_config()
        assert cfg.get_bool_env("TEST_BOOL", True) is True

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"])
    def test_dogru_degerler(self, monkeypatch, value):
        monkeypatch.setenv("TEST_BOOL", value)
        cfg = _reload_config()
        assert cfg.get_bool_env("TEST_BOOL", False) is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "NO", "off", "OFF"])
    def test_yanlis_degerler(self, monkeypatch, value):
        monkeypatch.setenv("TEST_BOOL", value)
        cfg = _reload_config()
        assert cfg.get_bool_env("TEST_BOOL", True) is False

    def test_bos_string_varsayilana_doner(self, monkeypatch):
        monkeypatch.setenv("TEST_BOOL", "   ")
        cfg = _reload_config()
        assert cfg.get_bool_env("TEST_BOOL", True) is True

    def test_tanimlanmamis_key_varsayilan_doner(self, monkeypatch):
        monkeypatch.delenv("TANIMLANMAMIS_KEY_XYZ", raising=False)
        cfg = _reload_config()
        assert cfg.get_bool_env("TANIMLANMAMIS_KEY_XYZ") is False


# ─────────────────────────────────────────────────────────────────────────────
# get_int_env
# ─────────────────────────────────────────────────────────────────────────────

class TestGetIntEnv:
    """get_int_env() fonksiyonu testleri."""

    def test_gecerli_tam_sayi(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "42")
        cfg = _reload_config()
        assert cfg.get_int_env("TEST_INT", 0) == 42

    def test_negatif_tam_sayi(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "-10")
        cfg = _reload_config()
        assert cfg.get_int_env("TEST_INT", 0) == -10

    def test_gecersiz_deger_varsayilan_doner(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "abc")
        cfg = _reload_config()
        assert cfg.get_int_env("TEST_INT", 99) == 99

    def test_tanimlanmamis_key_varsayilan_doner(self, monkeypatch):
        monkeypatch.delenv("TEST_INT_MISSING", raising=False)
        cfg = _reload_config()
        assert cfg.get_int_env("TEST_INT_MISSING", 7) == 7

    def test_float_string_tamsayiya_donusur(self, monkeypatch):
        # int("3.14") hata verir → varsayılan döner
        monkeypatch.setenv("TEST_INT", "3.14")
        cfg = _reload_config()
        assert cfg.get_int_env("TEST_INT", 5) == 5

    def test_sifir_deger(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "0")
        cfg = _reload_config()
        assert cfg.get_int_env("TEST_INT", 100) == 0


# ─────────────────────────────────────────────────────────────────────────────
# get_float_env
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFloatEnv:
    """get_float_env() fonksiyonu testleri."""

    def test_gecerli_float(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT", "3.14")
        cfg = _reload_config()
        assert cfg.get_float_env("TEST_FLOAT", 0.0) == pytest.approx(3.14)

    def test_tam_sayi_string(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT", "5")
        cfg = _reload_config()
        assert cfg.get_float_env("TEST_FLOAT", 0.0) == pytest.approx(5.0)

    def test_negatif_float(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT", "-1.5")
        cfg = _reload_config()
        assert cfg.get_float_env("TEST_FLOAT", 0.0) == pytest.approx(-1.5)

    def test_gecersiz_deger_varsayilan_doner(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT", "invalid")
        cfg = _reload_config()
        assert cfg.get_float_env("TEST_FLOAT", 2.5) == pytest.approx(2.5)

    def test_tanimlanmamis_key_varsayilan_doner(self, monkeypatch):
        monkeypatch.delenv("TEST_FLOAT_MISSING", raising=False)
        cfg = _reload_config()
        assert cfg.get_float_env("TEST_FLOAT_MISSING", 9.9) == pytest.approx(9.9)

    def test_sifir_deger(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT", "0.0")
        cfg = _reload_config()
        assert cfg.get_float_env("TEST_FLOAT", 1.0) == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# get_list_env
# ─────────────────────────────────────────────────────────────────────────────

class TestGetListEnv:
    """get_list_env() fonksiyonu testleri."""

    def test_virgul_ile_ayrilmis_liste(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", "a,b,c")
        cfg = _reload_config()
        assert cfg.get_list_env("TEST_LIST") == ["a", "b", "c"]

    def test_bosluklu_elemanlar_temizlenir(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", " x , y , z ")
        cfg = _reload_config()
        assert cfg.get_list_env("TEST_LIST") == ["x", "y", "z"]

    def test_bos_string_varsayilan_doner(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", "")
        cfg = _reload_config()
        assert cfg.get_list_env("TEST_LIST", ["default"]) == ["default"]

    def test_tanimlanmamis_key_varsayilan_doner(self, monkeypatch):
        monkeypatch.delenv("TEST_LIST_MISSING", raising=False)
        cfg = _reload_config()
        assert cfg.get_list_env("TEST_LIST_MISSING") == []

    def test_ozel_ayirici(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", "a|b|c")
        cfg = _reload_config()
        assert cfg.get_list_env("TEST_LIST", separator="|") == ["a", "b", "c"]

    def test_tek_eleman(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", "tek")
        cfg = _reload_config()
        assert cfg.get_list_env("TEST_LIST") == ["tek"]

    def test_ardisik_virgul_bos_elemanlar_atlanir(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", "a,,b")
        cfg = _reload_config()
        # Boş string strip → falsy → filtre dışı
        assert cfg.get_list_env("TEST_LIST") == ["a", "b"]


# ─────────────────────────────────────────────────────────────────────────────
# HardwareInfo
# ─────────────────────────────────────────────────────────────────────────────

class TestHardwareInfo:
    """HardwareInfo dataclass testleri."""

    def test_varsayilan_degerler(self):
        cfg = _reload_config()
        hw = cfg.HardwareInfo(has_cuda=False, gpu_name="N/A")
        assert hw.has_cuda is False
        assert hw.gpu_name == "N/A"
        assert hw.gpu_count == 0
        assert hw.cpu_count == 0
        assert hw.cuda_version == "N/A"
        assert hw.driver_version == "N/A"

    def test_cuda_aktif_ornegi(self):
        cfg = _reload_config()
        hw = cfg.HardwareInfo(
            has_cuda=True,
            gpu_name="NVIDIA RTX 4090",
            gpu_count=2,
            cpu_count=16,
            cuda_version="12.1",
            driver_version="535.0",
        )
        assert hw.has_cuda is True
        assert hw.gpu_count == 2
        assert hw.cuda_version == "12.1"


# ─────────────────────────────────────────────────────────────────────────────
# _is_wsl2
# ─────────────────────────────────────────────────────────────────────────────

class TestIsWsl2:
    """_is_wsl2() fonksiyonu testleri."""

    def test_wsl2_tespit_edilir(self):
        cfg = _reload_config()
        wsl_content = "5.15.90.1-microsoft-standard-WSL2"
        with patch("builtins.open", mock_open(read_data=wsl_content)):
            with patch.object(Path, "read_text", return_value=wsl_content):
                assert cfg._is_wsl2() is True

    def test_wsl2_olmayan_ortam(self):
        cfg = _reload_config()
        with patch.object(Path, "read_text", return_value="5.15.0-generic"):
            assert cfg._is_wsl2() is False

    def test_dosya_okunamazsa_false_doner(self):
        cfg = _reload_config()
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            assert cfg._is_wsl2() is False


# ─────────────────────────────────────────────────────────────────────────────
# check_hardware
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckHardware:
    """check_hardware() fonksiyonu testleri."""

    def test_gpu_devre_disi_env(self, monkeypatch):
        """USE_GPU=false olduğunda CUDA kontrolü atlanır."""
        monkeypatch.setenv("USE_GPU", "false")
        cfg = _reload_config()
        hw = cfg.check_hardware()
        assert hw.has_cuda is False
        assert "Devre Dışı" in hw.gpu_name

    def test_torch_kurulu_degil(self, monkeypatch):
        """torch import hatası durumunda has_cuda=False döner."""
        monkeypatch.setenv("USE_GPU", "true")
        cfg = _reload_config()
        with patch.dict(sys.modules, {"torch": None}):
            hw = cfg.check_hardware()
        assert hw.has_cuda is False

    def test_torch_cuda_yokken(self, monkeypatch):
        """torch kurulu ama CUDA yok → has_cuda False."""
        monkeypatch.setenv("USE_GPU", "true")
        cfg = _reload_config()

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": None}):
            with patch("importlib.import_module", side_effect=lambda m: mock_torch if m == "torch" else __import__(m)):
                hw = cfg.check_hardware()

        assert hw.has_cuda is False

    def test_torch_cuda_aktif(self, monkeypatch):
        """torch CUDA aktif → HardwareInfo doğru doldurulur."""
        monkeypatch.setenv("USE_GPU", "true")
        cfg = _reload_config()

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "NVIDIA RTX 4090"
        mock_torch.version.cuda = "12.1"
        mock_torch.cuda.set_per_process_memory_fraction = MagicMock()

        mock_pynvml = MagicMock()
        mock_pynvml.nvmlSystemGetDriverVersion.return_value = "535.0"

        with patch.dict(sys.modules, {"torch": mock_torch, "pynvml": mock_pynvml}):
            hw = cfg.check_hardware()

        assert hw.has_cuda is True
        assert hw.gpu_name == "NVIDIA RTX 4090"
        assert hw.gpu_count == 1
        assert hw.cuda_version == "12.1"


# ─────────────────────────────────────────────────────────────────────────────
# Config sınıfı — varsayılan değerler
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigDefaults:
    """Config sınıfının varsayılan değerlerini doğrular."""

    def setup_method(self):
        self.cfg = _reload_config()

    def test_proje_adi(self):
        assert self.cfg.Config.PROJECT_NAME == "Sidar"

    def test_versiyon(self):
        assert self.cfg.Config.VERSION == "5.2.0"

    def test_varsayilan_ai_saglayici(self):
        # Env set edilmemişse "ollama" döner
        assert self.cfg.Config.AI_PROVIDER in ("ollama", os.getenv("AI_PROVIDER", "ollama"))

    def test_varsayilan_veritabani_url(self):
        db_url = self.cfg.Config.DATABASE_URL
        assert db_url.startswith("sqlite") or "://" in db_url

    def test_varsayilan_web_portu(self):
        assert isinstance(self.cfg.Config.WEB_PORT, int)
        assert self.cfg.Config.WEB_PORT > 0

    def test_sandbox_limits_dict(self):
        limits = self.cfg.Config.SANDBOX_LIMITS
        assert isinstance(limits, dict)
        assert "memory" in limits
        assert "timeout" in limits

    def test_rag_top_k_pozitif(self):
        assert self.cfg.Config.RAG_TOP_K > 0

    def test_max_memory_turns_pozitif(self):
        assert self.cfg.Config.MAX_MEMORY_TURNS > 0

    def test_llm_max_retries_non_negatif(self):
        assert self.cfg.Config.LLM_MAX_RETRIES >= 0

    def test_base_dir_path_nesnesi(self):
        assert isinstance(self.cfg.Config.BASE_DIR, Path)

    def test_data_dir_base_dir_alt_klasoru(self):
        assert self.cfg.Config.DATA_DIR.parent == self.cfg.Config.BASE_DIR

    def test_rate_limit_window_pozitif(self):
        assert self.cfg.Config.RATE_LIMIT_WINDOW > 0

    def test_jwt_algorithm_hs256(self):
        assert self.cfg.Config.JWT_ALGORITHM == "HS256"

    def test_docker_exec_timeout_pozitif(self):
        assert self.cfg.Config.DOCKER_EXEC_TIMEOUT > 0


# ─────────────────────────────────────────────────────────────────────────────
# Config sınıfı — ortam değişkeni override'ları
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigEnvOverride:
    """Ortam değişkenlerinin Config sınıfındaki değerleri ezdiğini doğrular."""

    def test_ai_provider_override(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "openai")
        cfg = _reload_config()
        assert cfg.Config.AI_PROVIDER == "openai"

    def test_debug_mode_override(self, monkeypatch):
        monkeypatch.setenv("DEBUG_MODE", "true")
        cfg = _reload_config()
        assert cfg.Config.DEBUG_MODE is True

    def test_web_port_override(self, monkeypatch):
        monkeypatch.setenv("WEB_PORT", "8080")
        cfg = _reload_config()
        assert cfg.Config.WEB_PORT == 8080

    def test_log_level_override(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        cfg = _reload_config()
        assert cfg.Config.LOG_LEVEL == "DEBUG"

    def test_max_memory_turns_override(self, monkeypatch):
        monkeypatch.setenv("MAX_MEMORY_TURNS", "50")
        cfg = _reload_config()
        assert cfg.Config.MAX_MEMORY_TURNS == 50

    def test_rag_top_k_override(self, monkeypatch):
        monkeypatch.setenv("RAG_TOP_K", "10")
        cfg = _reload_config()
        assert cfg.Config.RAG_TOP_K == 10

    def test_ollama_url_override(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://custom:11434/api")
        cfg = _reload_config()
        assert cfg.Config.OLLAMA_URL == "http://custom:11434/api"

    def test_database_url_override(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/sidar")
        cfg = _reload_config()
        assert "postgresql" in cfg.Config.DATABASE_URL

    def test_enable_semantic_cache_override(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SEMANTIC_CACHE", "true")
        cfg = _reload_config()
        assert cfg.Config.ENABLE_SEMANTIC_CACHE is True

    def test_response_language_override(self, monkeypatch):
        monkeypatch.setenv("RESPONSE_LANGUAGE", "en")
        cfg = _reload_config()
        assert cfg.Config.RESPONSE_LANGUAGE == "en"


# ─────────────────────────────────────────────────────────────────────────────
# SANDBOX_LIMITS global sözlüğü
# ─────────────────────────────────────────────────────────────────────────────

class TestSandboxLimits:
    """Modül seviyesindeki SANDBOX_LIMITS sözlüğü testleri."""

    def setup_method(self):
        self.cfg = _reload_config()

    def test_beklenen_anahtarlar(self):
        keys = set(self.cfg.SANDBOX_LIMITS.keys())
        assert {"memory", "cpus", "pids_limit", "network", "timeout"} <= keys

    def test_timeout_pozitif_tam_sayi(self):
        assert isinstance(self.cfg.SANDBOX_LIMITS["timeout"], int)
        assert self.cfg.SANDBOX_LIMITS["timeout"] > 0

    def test_pids_limit_pozitif(self):
        assert self.cfg.SANDBOX_LIMITS["pids_limit"] > 0

    def test_memory_string(self):
        assert isinstance(self.cfg.SANDBOX_LIMITS["memory"], str)

    def test_sandbox_memory_override(self, monkeypatch):
        monkeypatch.setenv("SANDBOX_MEMORY", "512m")
        cfg = _reload_config()
        assert cfg.SANDBOX_LIMITS["memory"] == "512m"

    def test_sandbox_timeout_override(self, monkeypatch):
        monkeypatch.setenv("SANDBOX_TIMEOUT", "30")
        cfg = _reload_config()
        assert cfg.SANDBOX_LIMITS["timeout"] == 30
