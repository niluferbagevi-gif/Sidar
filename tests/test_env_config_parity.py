"""
.env.example ↔ config.py eşleşme testi (Faz 1 Stabilizasyon).

config.py içinde `os.getenv("VAR_NAME", ...)` olarak tanımlanan tüm
değişkenler .env.example'da da belgelenmiş olmalıdır.

Bu test CI'da otomatik olarak çalışarak yeni config değişkenlerinin
.env.example'a eklenmeden commit edilmesini engeller.

İstisna listesi: dahili/konfigürasyon olmayan ve .env.example'da
kasıtlı olarak yer almayan değişkenler.
"""

import re
from pathlib import Path


# Bu değişkenler kasıtlı olarak .env.example'da bulunmuyor:
# - DATABASE_URL      : PostgreSQL bağlantısı genellikle ayrı yönetilir (docker-compose vs.)
# - DB_SCHEMA_VERSION_TABLE : Alembic iç değişkeni, kullanıcıya gereksiz
# - DOCKER_MEM_LIMIT  : Docker run -m flag'ı; SANDBOX_MEMORY ile örtüşüyor
# - DOCKER_MICROVM_MODE : Deneysel; production kullanımda değil
_KNOWN_EXCEPTIONS = frozenset({
    "DATABASE_URL",
    "DB_SCHEMA_VERSION_TABLE",
    "DOCKER_MEM_LIMIT",
    "DOCKER_MICROVM_MODE",
})


def _extract_config_keys() -> set[str]:
    """config.py'deki os.getenv("LITERAL_KEY", ...) çağrılarından anahtar isimlerini çeker."""
    config_src = Path("config.py").read_text(encoding="utf-8")
    # Yalnızca değişken ismiyle çağrılanları yakala: os.getenv("KEY", ...) veya os.getenv("KEY")
    pattern = re.compile(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"\s*[,\)]')
    return set(pattern.findall(config_src))


def _extract_example_keys() -> set[str]:
    """".env.example dosyasından BÜYÜK_HARF=değer satırlarının anahtarlarını çeker."""
    env_src = Path(".env.example").read_text(encoding="utf-8")
    pattern = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
    return set(pattern.findall(env_src))


# ─── Testler ──────────────────────────────────────────────────────────────


def test_all_config_vars_documented_in_env_example():
    """
    config.py'de os.getenv() ile okunan her değişken .env.example'da bulunmalı.
    Kasıtlı istisnalar _KNOWN_EXCEPTIONS listesinde tutulur.
    """
    config_keys = _extract_config_keys()
    example_keys = _extract_example_keys()

    missing = (config_keys - example_keys) - _KNOWN_EXCEPTIONS

    assert not missing, (
        f"\n\nAşağıdaki config.py değişkenleri .env.example'da TANIMLANMAMIŞ:\n"
        + "\n".join(f"  - {k}" for k in sorted(missing))
        + "\n\nDüzeltme: .env.example'a ilgili bölümü ekleyin ya da "
        + "_KNOWN_EXCEPTIONS listesine dahil edin."
    )


def test_no_stale_exception_in_known_exceptions():
    """
    _KNOWN_EXCEPTIONS listesindeki her değişken gerçekten config.py'de
    os.getenv() ile kullanılıyor olmalı (eski/stale exception'ları engeller).
    """
    config_keys = _extract_config_keys()
    stale = _KNOWN_EXCEPTIONS - config_keys

    assert not stale, (
        f"\n\nAşağıdaki değişkenler _KNOWN_EXCEPTIONS'ta ama artık config.py'de KULLANILMIYOR:\n"
        + "\n".join(f"  - {k}" for k in sorted(stale))
        + "\n\nDüzeltme: _KNOWN_EXCEPTIONS listesinden kaldırın."
    )


def test_env_example_has_no_duplicate_keys():
    """.env.example'da aynı anahtar iki kez tanımlanmamalı."""
    env_src = Path(".env.example").read_text(encoding="utf-8")
    pattern = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
    all_keys = pattern.findall(env_src)
    duplicates = [k for k in set(all_keys) if all_keys.count(k) > 1]

    assert not duplicates, (
        f"\n\n.env.example'da çift tanımlı anahtarlar:\n"
        + "\n".join(f"  - {k}" for k in sorted(duplicates))
    )


def test_config_py_reads_keys_as_strings():
    """
    config.py'de os.getenv(key) şeklinde değişken argümanlı çağrılar olabilir.
    Bu test söz konusu kalıbı sayıp belgelemek için vardır (sınır belirleme).
    """
    config_src = Path("config.py").read_text(encoding="utf-8")
    # Değişken argüman: os.getenv(variable, ...) — literal değil
    variable_pattern = re.compile(r'os\.getenv\(\s*([^"\'(][^,)]*)\s*[,\)]')
    variable_calls = variable_pattern.findall(config_src)
    # Sayısal sınır: genel amaçlı helper fonksiyonlarda bunlar beklenir
    # Bu test yalnızca sayı izler, hata üretmez
    assert len(variable_calls) <= 10, (
        f"config.py'de beklenenden fazla değişken argümanlı os.getenv() çağrısı: "
        f"{len(variable_calls)} (max 10). Yeni helper fonksiyonları eklenmiş olabilir."
    )


def test_env_example_has_key_jwt_secret_key():
    """JWT_SECRET_KEY üretim için kritik — .env.example'da belgelenmiş olmalı."""
    example_keys = _extract_example_keys()
    assert "JWT_SECRET_KEY" in example_keys


def test_env_example_has_otel_keys():
    """OpenTelemetry anahtarları v4.0'da eklendi — .env.example'da bulunmalı."""
    example_keys = _extract_example_keys()
    for key in ("ENABLE_TRACING", "OTEL_EXPORTER_ENDPOINT", "OTEL_SERVICE_NAME"):
        assert key in example_keys, f"OTel anahtarı .env.example'da eksik: {key}"
