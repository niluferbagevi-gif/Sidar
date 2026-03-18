"""
Tests for scripts/check_env_parity.sh ve .env.example ↔ config.py paritesi.

Bu test dosyası:
1. Shell script'inin var olduğunu doğrular
2. Çalıştırılabilir olduğunu doğrular
3. config.py'deki DLP/HITL/JUDGE anahtarlarının .env.example'da mevcut olduğunu doğrular
4. .env.example'daki yeni bölümlerin eklendiğini doğrular
"""
import os
import re
import stat
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.py"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
PARITY_SCRIPT = PROJECT_ROOT / "scripts" / "check_env_parity.sh"


# ─── Script varlığı ──────────────────────────────────────────────────────────

def test_parity_script_exists():
    assert PARITY_SCRIPT.exists(), f"check_env_parity.sh bulunamadı: {PARITY_SCRIPT}"


def test_parity_script_executable():
    mode = PARITY_SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "check_env_parity.sh çalıştırılabilir değil"


# ─── .env.example içerik doğrulama ───────────────────────────────────────────

def test_env_example_has_dlp_section():
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "DLP_ENABLED" in content, "DLP_ENABLED .env.example'da yok"
    assert "DLP_LOG_DETECTIONS" in content, "DLP_LOG_DETECTIONS .env.example'da yok"


def test_env_example_has_hitl_section():
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "HITL_ENABLED" in content, "HITL_ENABLED .env.example'da yok"
    assert "HITL_TIMEOUT_SECONDS" in content, "HITL_TIMEOUT_SECONDS .env.example'da yok"


def test_env_example_has_judge_section():
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "JUDGE_ENABLED" in content, "JUDGE_ENABLED .env.example'da yok"
    assert "JUDGE_MODEL" in content, "JUDGE_MODEL .env.example'da yok"
    assert "JUDGE_PROVIDER" in content, "JUDGE_PROVIDER .env.example'da yok"
    assert "JUDGE_SAMPLE_RATE" in content, "JUDGE_SAMPLE_RATE .env.example'da yok"


# ─── config.py içerik doğrulama ──────────────────────────────────────────────

def test_config_has_dlp_keys():
    content = CONFIG_FILE.read_text(encoding="utf-8")
    assert "DLP_ENABLED" in content
    assert "DLP_LOG_DETECTIONS" in content


def test_config_has_hitl_keys():
    content = CONFIG_FILE.read_text(encoding="utf-8")
    assert "HITL_ENABLED" in content
    assert "HITL_TIMEOUT_SECONDS" in content


def test_config_has_judge_keys():
    content = CONFIG_FILE.read_text(encoding="utf-8")
    assert "JUDGE_ENABLED" in content
    assert "JUDGE_MODEL" in content
    assert "JUDGE_PROVIDER" in content
    assert "JUDGE_SAMPLE_RATE" in content


# ─── config.py os.getenv çağrıları ile .env.example parite kontrolü ──────────

def test_critical_env_keys_present_in_example():
    """
    config.py'deki kritik os.getenv anahtarlarının tamamı .env.example'da olmalı.
    Bu test, ileride eklenen yeni anahtarların belgelenmediğini hızla tespit eder.
    """
    config_text = CONFIG_FILE.read_text(encoding="utf-8")
    example_text = ENV_EXAMPLE.read_text(encoding="utf-8")

    # config.py'deki tüm os.getenv("KEY") çağrılarını çıkar
    config_keys = set(re.findall(r'os\.getenv\(["\']([A-Z_][A-Z0-9_]+)["\']', config_text))

    # .env.example'daki tanımlanmış anahtarları çıkar
    example_keys = set(re.findall(r'^([A-Z_][A-Z0-9_]+)=', example_text, re.MULTILINE))

    # Yeni eklenen anahtarların hepsinin .env.example'da olduğunu doğrula
    new_keys = {"DLP_ENABLED", "DLP_LOG_DETECTIONS", "HITL_ENABLED",
                "HITL_TIMEOUT_SECONDS", "JUDGE_ENABLED", "JUDGE_MODEL",
                "JUDGE_PROVIDER", "JUDGE_SAMPLE_RATE"}

    missing = new_keys - example_keys
    assert not missing, (
        f"Şu anahtarlar config.py'de var ama .env.example'da yok: {missing}"
    )


# ─── CI workflow doğrulama ───────────────────────────────────────────────────

def test_ci_workflow_includes_parity_check():
    ci_file = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists(), "ci.yml bulunamadı"
    content = ci_file.read_text(encoding="utf-8")
    assert "check_env_parity" in content, (
        "ci.yml içinde check_env_parity.sh çağrısı bulunamadı"
    )
