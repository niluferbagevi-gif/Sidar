"""Critical startup validation for the Config facade.

`config.Config.validate_critical_settings()` and `_validate_ai_provider_settings()`
delegate here. The Config class is passed in, and every step that tests or
subclasses may override (hardware loading, directory setup, the provider check)
is still called through it, so the facade's classmethod surface stays the
single override point.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from core import config_postgres, config_secret_hardening
from core.config_secrets import is_nonempty_secret
from core.config_validators import is_valid_http_url, normalize_ai_provider


def validate_ai_provider_settings(
    config_cls: Any,
    *,
    logger: logging.Logger,
    supported_providers: Iterable[str],
    provider_required_settings: Mapping[str, Iterable[str]],
) -> bool:
    """Normalize ``AI_PROVIDER`` and check the credentials that provider needs."""
    provider = normalize_ai_provider(config_cls.AI_PROVIDER)
    config_cls.AI_PROVIDER = provider

    supported = set(supported_providers)
    if provider not in supported:
        logger.error(
            "❌ Geçersiz AI_PROVIDER=%s. Geçerli sağlayıcılar: %s",
            provider,
            ", ".join(sorted(supported)),
        )
        return False

    is_valid = True
    for setting_name in provider_required_settings.get(provider, ()):  # ollama has no API key
        raw_value = getattr(config_cls, setting_name, "")
        if setting_name.endswith("_GATEWAY_URL"):
            setting_valid = is_valid_http_url(raw_value)
            message = (
                f"❌ {provider} modu seçili ama {setting_name} geçerli bir http(s) URL değil!\n"
                "   .env dosyasını kontrol edin."
            )
        else:
            setting_valid = is_nonempty_secret(raw_value)
            message = (
                f"❌ {provider} modu seçili ama {setting_name} ayarlanmamış veya hatalı!\n"
                "   .env dosyasını kontrol edin."
            )

        if not setting_valid:
            logger.error(message)
            is_valid = False

    return is_valid


def _validate_memory_encryption_key(config_cls: Any, *, logger: logging.Logger) -> bool:
    """Check ``MEMORY_ENCRYPTION_KEY`` (and rotated keys); exit in production when unset."""
    memory_encryption_key = (config_cls.MEMORY_ENCRYPTION_KEY or "").strip()
    previous_memory_encryption_keys = [
        key.strip()
        for key in str(config_cls.MEMORY_ENCRYPTION_KEY_PREVIOUS or "").split(",")
        if key.strip()
    ]

    if memory_encryption_key:
        try:
            from cryptography.fernet import Fernet  # noqa: F401

            # Anahtarı ön doğrulama — geçersiz formatta erken hata ver
            try:
                Fernet(memory_encryption_key.encode())
                for previous_key in previous_memory_encryption_keys:
                    Fernet(previous_key.encode())
            except Exception as key_exc:
                logger.error(
                    "❌ MEMORY_ENCRYPTION_KEY geçersiz Fernet anahtarı: %s\n"
                    "   Geçerli anahtar üretmek için:\n"
                    '   python -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"',
                    key_exc,
                )
                return False
        except ImportError:
            logger.error(
                "❌ MEMORY_ENCRYPTION_KEY ayarlanmış ama 'cryptography' paketi kurulu değil.\n"
                "   Bu kritik bir güvenlik ayarıdır. Şifreleme olmadan devam etmek\n"
                "   güvenlik riskine yol açabilir. Kurmak için: uv pip install cryptography"
            )
            return False
        return True

    logger.critical(
        "MEMORY_ENCRYPTION_KEY is not set. Please generate a valid Fernet key for memory "
        "encryption. "
        "Konuşma geçmişi şifrelenmeden saklanıyor. Üretim ortamında .env dosyasına güçlü "
        "bir Fernet anahtarı eklemelisiniz.\n"
        '   Yeni anahtar üretmek için: python -c "from cryptography.fernet import '
        'Fernet; print(Fernet.generate_key().decode())"'
    )
    if os.getenv("SIDAR_ENV", "").strip().lower() == "production":
        logger.critical(
            "SIDAR_ENV=production iken MEMORY_ENCRYPTION_KEY zorunludur. Güvenlik "
            "nedeniyle uygulama durduruluyor."
        )
        raise SystemExit(1)
    return True


def _probe_ollama(
    config_cls: Any,
    *,
    logger: logging.Logger,
    log_once_env: Callable[..., Any],
    localized_log_message: Callable[[str], str],
) -> None:
    """Log whether the configured Ollama server answers ``/api/tags`` (never fails validation)."""
    try:
        import httpx

        base = config_cls.OLLAMA_URL.rstrip("/")
        if base.endswith("/api"):
            tags_url = base + "/tags"
        else:
            tags_url = base + "/api/tags"
        with httpx.Client(timeout=2) as client:
            r = client.get(tags_url)
        if r.status_code == 200:
            log_once_env("SIDAR_OLLAMA_OK_LOGGED", logger.info, localized_log_message("ollama_ok"))
        else:
            logger.warning(localized_log_message("ollama_status"), r.status_code)
    except Exception:
        logger.warning(
            localized_log_message("ollama_unreachable"),
            config_cls.OLLAMA_URL,
        )


def validate_critical_settings(
    config_cls: Any,
    *,
    logger: logging.Logger,
    log_once_env: Callable[..., Any],
    localized_log_message: Callable[[str], str],
) -> bool:
    """Validate critical settings and log warnings; exit on unsafe production secrets.

    The production key list and the PostgreSQL drift check are read from their
    modules at call time, so tests that patch ``config.config_postgres`` keep working.
    Only key names and drift diagnostics are logged, never secret values.
    """
    is_valid = True
    config_cls._ensure_hardware_info_loaded()
    config_cls._apply_gpu_memory_safety_check()
    config_cls.initialize_directories()
    missing_runtime_keys = config_cls.get_missing_critical_runtime_keys()
    config_cls._log_dotenv_load_status(missing_keys=missing_runtime_keys)

    if os.getenv("SIDAR_ENV", "").strip().lower() == "production":
        unsafe_production_secrets = [
            key
            for key in config_secret_hardening.PRODUCTION_SECRET_KEYS
            if key in missing_runtime_keys
        ]
        if unsafe_production_secrets:
            logger.critical(
                "Production secret doğrulaması başarısız: %s. Eksik, zayıf veya "
                "non-production ortamlarla paylaşılan secret değerlerini rotate edin; "
                "değerler güvenlik nedeniyle loglanmadı.",
                ", ".join(unsafe_production_secrets),
            )
            raise SystemExit(1)

    if config_cls.REQUIRE_GPU and not config_cls.USE_GPU:
        logger.error(
            "❌ GPU zorunlu mod aktif (REQUIRE_GPU=true) ancak CUDA/PyTorch uygun değil veya "
            "USE_GPU=false.\n"
            "   Çözüm: CUDA destekli PyTorch kurun ve .env içinde USE_GPU=true yapın."
        )
        is_valid = False

    allow_full_access = os.getenv("SIDAR_ALLOW_FULL_ACCESS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if config_cls.ACCESS_LEVEL.strip().lower() == "full" and not allow_full_access:
        logger.error(
            "❌ ACCESS_LEVEL=full açık onay olmadan yasaktır. "
            "Riskleri kabul ediyorsanız SIDAR_ALLOW_FULL_ACCESS=true ayarlayın."
        )
        is_valid = False

    is_valid = config_cls._validate_ai_provider_settings() and is_valid

    for drift_message in config_postgres.postgres_password_drift_messages():
        logger.error(
            "❌ %s Önce scripts/sync_database_passwords.py veya POSTGRES_* tek kaynak akışını "
            "kullanın.",
            drift_message,
        )
        is_valid = False

    is_valid = _validate_memory_encryption_key(config_cls, logger=logger) and is_valid

    if config_cls.AI_PROVIDER == "ollama":
        _probe_ollama(
            config_cls,
            logger=logger,
            log_once_env=log_once_env,
            localized_log_message=localized_log_message,
        )

    return is_valid
