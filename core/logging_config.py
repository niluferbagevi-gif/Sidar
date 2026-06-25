"""Logging configuration helpers for the Sidar runtime config module."""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

LOG_MESSAGES: dict[str, dict[str, str]] = {
    "log_file_unavailable": {
        "tr": "⚠️ Log dosyasına yazılamıyor (%s). Sadece konsol loglama ile devam edilecek.",
        "en": "⚠️ Cannot write to log file (%s). Continuing with console logging only.",
    },
    "config_reload_suppressed": {
        "tr": "Config tekrar yüklendi; aynı fingerprint için bilgi logu bastırıldı: %s",
        "en": "Config reloaded; info log suppressed for the same fingerprint: %s",
    },
    "env_loaded": {
        "tr": "✅ Ortam değişkenleri yüklendi: %s",
        "en": "✅ Environment variables loaded: %s",
    },
    "provider_updated": {
        "tr": "✅ AI Sağlayıcı güncellendi: %s",
        "en": "✅ AI provider updated: %s",
    },
    "invalid_provider": {
        "tr": "❌ Geçersiz sağlayıcı modu: %s  Geçerliler: %s",
        "en": "❌ Invalid provider mode: %s  Valid values: %s",
    },
    "ollama_ok": {
        "tr": "✅ Ollama bağlantısı başarılı.",
        "en": "✅ Ollama connection successful.",
    },
    "ollama_status": {
        "tr": "⚠️  Ollama yanıt kodu: %d",
        "en": "⚠️  Ollama response status: %d",
    },
    "ollama_unreachable": {
        "tr": "⚠️  Ollama'ya ulaşılamadı (%s)\n    'ollama serve' çalıştırıldığından emin olun.",
        "en": "⚠️  Ollama is unreachable (%s)\n    Make sure 'ollama serve' is running.",
    },
    "otel_active": {
        "tr": "✅ OpenTelemetry aktif: %s",
        "en": "✅ OpenTelemetry active: %s",
    },
    "otel_failed": {
        "tr": "OpenTelemetry başlatılamadı: %s",
        "en": "OpenTelemetry could not be started: %s",
    },
    "config_loaded": {
        "tr": "✅ %s v%s yapılandırması yüklendi.",
        "en": "✅ %s v%s configuration loaded.",
    },
}

NOISY_DEPENDENCY_LOGGERS = (
    "httpx",
    "huggingface_hub",
    "sentence_transformers",
    "alembic.runtime.migration",
)


@dataclass(frozen=True)
class LoggingConfigState:
    """Resolved logging settings exported back to ``config.py``."""

    log_dir: Path
    log_level_str: str
    log_file_path: Path
    log_max_bytes: int
    log_backup_count: int
    verbose_http_logs: bool
    noisy_dependency_loggers: tuple[str, ...]


def get_sidar_locale() -> str:
    """Resolve the runtime log locale from SIDAR_LOCALE."""
    raw_locale = os.getenv("SIDAR_LOCALE", "tr").strip().lower()
    normalized = raw_locale.split(".", 1)[0].replace("_", "-").split("-", 1)[0]
    return "en" if normalized == "en" else "tr"


def localized_log_message(key: str) -> str:
    """Return a localized log format string for the active Sidar locale."""
    messages = LOG_MESSAGES[key]
    return messages.get(get_sidar_locale(), messages["tr"])


def configure_noisy_dependency_loggers(
    logger_names: tuple[str, ...] = NOISY_DEPENDENCY_LOGGERS, *, verbose_http: bool
) -> None:
    """Set noisy dependency logger levels and unify output through root handlers."""
    target_level = logging.NOTSET if verbose_http else logging.WARNING
    for logger_name in logger_names:
        dep_logger = logging.getLogger(logger_name)
        dep_logger.setLevel(target_level)
        dep_logger.propagate = True
        if dep_logger.handlers:
            dep_logger.handlers.clear()


def _log_format(log_level_str: str) -> str:
    if log_level_str == "DEBUG":
        return "%(asctime)s %(levelname)-7s %(name)s [%(threadName)s]:%(lineno)d › %(message)s"
    return "%(asctime)s %(levelname)-7s %(name)s:%(lineno)d › %(message)s"


def configure_sidar_logging(
    *,
    base_dir: Path,
    get_int_env: Callable[[str, int], int],
    get_bool_env: Callable[[str, bool], bool],
    repair_log_file_permissions: Callable[[Path], None],
) -> LoggingConfigState:
    """Configure root console/file logging and return resolved config values."""
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("SIDAR_CONFIG_QUIET", "false")

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file_path = base_dir / os.getenv("LOG_FILE", "logs/sidar_system.log")
    log_max_bytes = get_int_env("LOG_MAX_BYTES", 10_485_760)
    log_backup_count = get_int_env("LOG_BACKUP_COUNT", 5)
    verbose_http_logs = get_bool_env("SIDAR_VERBOSE_HTTP", False)

    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    repair_log_file_permissions(log_file_path)

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        with contextlib.suppress(Exception):
            handler.flush()
            handler.close()
        root_logger.removeHandler(handler)

    resolved_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(
        level=resolved_level,
        format=_log_format(log_level_str),
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    with contextlib.suppress(Exception):
        root_logger.handlers[0].setLevel(resolved_level)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=log_max_bytes,
            backupCount=log_backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_log_format(log_level_str)))
        root_logger.addHandler(file_handler)
    except (PermissionError, OSError) as exc:
        root_logger.warning(localized_log_message("log_file_unavailable"), exc)

    configure_noisy_dependency_loggers(verbose_http=verbose_http_logs)

    return LoggingConfigState(
        log_dir=log_dir,
        log_level_str=log_level_str,
        log_file_path=log_file_path,
        log_max_bytes=log_max_bytes,
        log_backup_count=log_backup_count,
        verbose_http_logs=verbose_http_logs,
        noisy_dependency_loggers=NOISY_DEPENDENCY_LOGGERS,
    )
