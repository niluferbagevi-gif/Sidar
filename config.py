"""
Sidar Project — Merkezi Yapılandırma Modülü
Sürüm: `sidar_version.PRODUCT_VERSION` üzerinden merkezi olarak çözülür.
Açıklama: Sistem ayarları, donanım tespiti, dizin yönetimi ve loglama altyapısı.
"""

import contextlib
import logging
import os
import sys
import warnings
from collections.abc import Callable
from copy import deepcopy
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

from core.config_dirs import initialize_directories as initialize_required_directories
from core.config_dirs import repair_log_file_permissions, resolve_base_dir
from core.config_gpu_detect import (
    HardwareInfo,
    normalize_gpu_memory_fractions,
    resolve_adaptive_gpu_pool_size,
)
from core.config_logging_setup import configure_noisy_dependency_loggers
from core.config_runtime_env import apply_runtime_env_overrides, safe_choice_for_reload
from core.config_secrets import is_nonempty_secret
from sidar_version import PRODUCT_VERSION

# HuggingFace/Transformers gürültülü çıktıları .env yüklemesi başlamadan bastırılır.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

# ═══════════════════════════════════════════════════════════════
# UYARI FİLTRELERİ
# ═══════════════════════════════════════════════════════════════
warnings.filterwarnings("ignore", category=FutureWarning, module="torch")
warnings.filterwarnings("ignore", category=UserWarning, module="torch")
warnings.filterwarnings("ignore", category=UserWarning, message=".*pkg_resources is deprecated.*")

# ═══════════════════════════════════════════════════════════════
# TEMEL DİZİN VE .ENV YÜKLEMESİ  (diğer her şeyden ÖNCE)
# ═══════════════════════════════════════════════════════════════
BASE_DIR = getattr(sys.modules.get(__name__), "BASE_DIR", None) or resolve_base_dir(__file__)

_DOTENV_LOAD_EVENTS: list[dict[str, Any]] = []
_DOTENV_KEY_SOURCES: dict[str, dict[str, Any]] = {}
_DOTENV_MANAGED_KEYS: set[str] = set()
_DOTENV_ORIGINAL_ENV_VALUES: dict[str, str] = {}
_DOTENV_MISSING_FILE_NOTICES: list[str] = []
_LAST_DOTENV_LOAD_CHAIN_SIGNATURE: tuple[tuple[str, str], ...] | None = None
_FIRST_CONFIG_LOAD_LOGGED = False
logger = logging.getLogger("Sidar.Config")


def _log_first_load_info(message: str, *args: Any) -> None:
    """Log as INFO only on first config load cycle, DEBUG on later reloads."""
    if _FIRST_CONFIG_LOAD_LOGGED:
        logger.debug(message, *args)
    else:
        logger.info(message, *args)


def _parse_dotenv_source_values(path: Path) -> dict[str, str]:
    """Parse simple dotenv assignments for source attribution without logging values."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _record_dotenv_key_sources(
    *,
    label: str,
    path: Path,
    override: bool,
    parsed_values: dict[str, str],
    before_values: dict[str, str | None],
) -> None:
    """Track which dotenv file supplied each effective key without storing values."""
    for key in parsed_values:
        if key not in os.environ:
            continue
        if override or before_values.get(key) is None:
            if key not in _DOTENV_MANAGED_KEYS:
                original_value = before_values.get(key)
                if original_value is not None:
                    _DOTENV_ORIGINAL_ENV_VALUES[key] = original_value
            _DOTENV_MANAGED_KEYS.add(key)
            _DOTENV_KEY_SOURCES[key] = {
                "label": label,
                "path": str(path),
                "override": override,
            }


def _reset_dotenv_managed_environment() -> None:
    """Restore pre-dotenv env values so reloads can observe changed dotenv files."""
    for key in tuple(_DOTENV_MANAGED_KEYS):
        original_value = _DOTENV_ORIGINAL_ENV_VALUES.get(key)
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value
    _DOTENV_MANAGED_KEYS.clear()


def _record_dotenv_event(
    *,
    label: str,
    raw_path: str,
    resolved_path: Path | None,
    loaded: bool,
    override: bool,
    reason: str = "",
) -> None:
    """Record dotenv load attempts so runtime checks can explain env precedence."""
    _DOTENV_LOAD_EVENTS.append(
        {
            "label": label,
            "raw_path": raw_path,
            "path": str(resolved_path) if resolved_path is not None else "",
            "loaded": loaded,
            "override": override,
            "reason": reason,
        }
    )
    if not loaded and reason == "missing" and resolved_path is not None:
        _DOTENV_MISSING_FILE_NOTICES.append(f"{label}={resolved_path}")


def get_dotenv_load_report() -> list[dict[str, Any]]:
    """Return the ordered dotenv load attempts used by this runtime."""
    return deepcopy(_DOTENV_LOAD_EVENTS)


def get_dotenv_key_source_report() -> dict[str, dict[str, Any]]:
    """Return dotenv key-to-source metadata without exposing secret values."""
    return deepcopy(_DOTENV_KEY_SOURCES)


# Açık referans: test izolasyon/reload araçlarında dotenv tanılama API'lerini sabit tutar.
_dotenv_api_exports = (get_dotenv_load_report, get_dotenv_key_source_report)


def _resolve_dotenv_path(raw_path: str) -> Path:
    """Resolve repo-relative, absolute, or user-home dotenv file paths."""
    dotenv_path = Path(raw_path).expanduser()
    if not dotenv_path.is_absolute():
        dotenv_path = BASE_DIR / dotenv_path
    return dotenv_path


def _load_dotenv_if_exists(
    raw_path: str,
    *,
    override: bool,
    label: str,
    record_missing: bool = True,
) -> Path | None:
    """Load a dotenv file when it exists and return the resolved path."""
    cleaned_path = raw_path.strip()
    if not cleaned_path:
        _record_dotenv_event(
            label=label,
            raw_path=raw_path,
            resolved_path=None,
            loaded=False,
            override=override,
            reason="empty_path",
        )
        return None
    dotenv_path = _resolve_dotenv_path(cleaned_path)
    if dotenv_path.exists():
        parsed_values = _parse_dotenv_source_values(dotenv_path)
        before_values = {key: os.environ.get(key) for key in parsed_values}
        # Import at call time so tests/runtime reloads observe the current dotenv loader
        # instead of a stale function captured by a previous module reload.
        from dotenv import load_dotenv as current_load_dotenv

        current_load_dotenv(dotenv_path=dotenv_path, override=override)
        _record_dotenv_event(
            label=label,
            raw_path=raw_path,
            resolved_path=dotenv_path,
            loaded=True,
            override=override,
        )
        _record_dotenv_key_sources(
            label=label,
            path=dotenv_path,
            override=override,
            parsed_values=parsed_values,
            before_values=before_values,
        )
        return dotenv_path
    if record_missing:
        _record_dotenv_event(
            label=label,
            raw_path=raw_path,
            resolved_path=dotenv_path,
            loaded=False,
            override=override,
            reason="missing",
        )
    return None


def _dotenv_values_for_reload(path: Path) -> dict[str, str]:
    """Read dotenv assignments for reload-time effective env calculation."""
    from dotenv import dotenv_values

    values: dict[str, str] = {}
    for key, value in dotenv_values(path).items():
        if key and value is not None:
            values[key] = str(value)
    return values


def _load_dotenv_into_effective_env(
    effective_env: dict[str, str],
    raw_path: str,
    *,
    override: bool,
    label: str,
) -> Path | None:
    """Record and merge one dotenv file into an in-memory env without mutating os.environ."""
    cleaned_path = raw_path.strip()
    if not cleaned_path:
        _record_dotenv_event(
            label=label,
            raw_path=raw_path,
            resolved_path=None,
            loaded=False,
            override=override,
            reason="empty_path",
        )
        return None

    dotenv_path = _resolve_dotenv_path(cleaned_path)
    if not dotenv_path.exists():
        _record_dotenv_event(
            label=label,
            raw_path=raw_path,
            resolved_path=dotenv_path,
            loaded=False,
            override=override,
            reason="missing",
        )
        return None

    parsed_values = _dotenv_values_for_reload(dotenv_path)
    before_values = {key: effective_env.get(key) for key in parsed_values}
    for key, value in parsed_values.items():
        if override or key not in effective_env:
            effective_env[key] = value

    _record_dotenv_event(
        label=label,
        raw_path=raw_path,
        resolved_path=dotenv_path,
        loaded=True,
        override=override,
    )
    for key in parsed_values:
        if key not in effective_env:
            continue
        if override or before_values.get(key) is None:
            if key not in _DOTENV_MANAGED_KEYS:
                original_value = before_values.get(key)
                if original_value is not None:
                    _DOTENV_ORIGINAL_ENV_VALUES[key] = original_value
            _DOTENV_MANAGED_KEYS.add(key)
            _DOTENV_KEY_SOURCES[key] = {
                "label": label,
                "path": str(dotenv_path),
                "override": override,
            }
    return dotenv_path


def _dotenv_reload_baseline_environment() -> dict[str, str]:
    """Return the pre-dotenv baseline for atomic reload without intermediate os.environ pops."""
    effective_env = dict(os.environ)
    for key in tuple(_DOTENV_MANAGED_KEYS):
        effective_env.pop(key, None)
    return effective_env


def _skip_default_dotenv_layers(env: dict[str, str] | None = None) -> bool:
    """Return whether repository-local dotenv layers should be skipped."""

    values = os.environ if env is None else env
    return values.get("SIDAR_SKIP_DEFAULT_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}


# 1. Ortam değişkenini kontrol et (örn: SIDAR_ENV=production)
sidar_env = os.getenv("SIDAR_ENV", "").strip().lower()
_SKIP_DEFAULT_DOTENV = _skip_default_dotenv_layers()

# 2-4. Varsayılan yerel dotenv katmanları opt-out edilmediyse yüklenir.
#      DOTENV_FILE ve SIDAR_KEYS_FILE aşağıda her durumda korunur.
base_env_path = BASE_DIR / ".env"
advanced_env_path = BASE_DIR / ".env.advanced"
if not _SKIP_DEFAULT_DOTENV:
    _load_dotenv_if_exists(str(base_env_path), override=False, label="base")
    _load_dotenv_if_exists(str(advanced_env_path), override=False, label="advanced")
    # .env veya .env.advanced SIDAR_ENV değerini değiştirdiyse ortam dosyası seçimini güncelle.
    sidar_env = os.getenv("SIDAR_ENV", "").strip().lower()

    # Ortama özgü dosyayı (örn: .env.production) temel/advanced ayarların üstüne yaz.
    # Import aşamasında stdout'a erken uyarı basmayın; tüm dotenv durumu
    # Config._log_dotenv_load_status() içinde tek logger kanalından raporlanır.
    if sidar_env:
        specific_env_path = BASE_DIR / f".env.{sidar_env}"
        _load_dotenv_if_exists(
            str(specific_env_path), override=True, label=f"environment:{sidar_env}"
        )

# 5. DOTENV_FILE ile açıkça belirtilen dosyayı yüksek öncelikle yükle.
#    Repo-göreli yolların yanında mutlak yollar ve ~ kısaltması desteklenir.
#    (örn: test ortamında DOTENV_FILE=.env.test veya DOTENV_FILE=~/.sidar_keys.env)
_explicit_dotenv = os.getenv("DOTENV_FILE", "").strip()
_load_dotenv_if_exists(_explicit_dotenv, override=True, label="explicit:DOTENV_FILE")

# 6. Kullanıcıya özel gizli anahtar dosyasını en son yükle. Bu dosya repoya
#    konmamalıdır; varsayılan ~/.sidar_keys.env sadece mevcutsa yüklenir.
_sidar_keys_file = os.getenv("SIDAR_KEYS_FILE", "~/.sidar_keys.env").strip()
_load_dotenv_if_exists(_sidar_keys_file, override=True, label="secret:SIDAR_KEYS_FILE")

ENV_PATH = base_env_path


class LLMClientSettings(BaseSettings):
    """LLM istemcisi için ortam değişkenlerini tip güvenli şekilde yükler."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH) if ENV_PATH.exists() and not _SKIP_DEFAULT_DOTENV else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    AI_PROVIDER: str = "ollama"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BASE_DELAY: float = 0.4
    LLM_RETRY_MAX_DELAY: float = 4.0
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-latest"
    ANTHROPIC_TIMEOUT: int = 60
    LITELLM_GATEWAY_URL: str = ""
    LITELLM_API_KEY: str = ""
    LITELLM_MODEL: str = ""
    LITELLM_TIMEOUT: int = 60
    OLLAMA_URL: str = "http://localhost:11434/api"
    OLLAMA_TIMEOUT: int = 600
    OLLAMA_KEEP_ALIVE: str = "30m"
    OLLAMA_NUM_BATCH: int = 2048
    OLLAMA_CODING_NUM_CTX: int = 8192
    OLLAMA_CONTEXT_MAX_CHARS: int = 12000
    OLLAMA_STREAM_MAX_BUFFER_CHARS: int = 1_000_000
    CODING_MODEL: str = "qwen2.5-coder:7b"
    REDIS_MAX_CONNECTIONS: int = 50
    SEMANTIC_CACHE_TTL: int = 3600
    SEMANTIC_CACHE_MAX_ITEMS: int = 500
    SEMANTIC_CACHE_REDIS_CB_FAIL_THRESHOLD: int = 3
    SEMANTIC_CACHE_REDIS_CB_COOLDOWN_SECONDS: int = 30


LLM_SETTINGS = LLMClientSettings()

SUPPORTED_AI_PROVIDERS: frozenset[str] = frozenset(
    {"ollama", "gemini", "openai", "anthropic", "litellm"}
)
_PROVIDER_REQUIRED_SETTINGS: dict[str, tuple[str, ...]] = {
    "gemini": ("GEMINI_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "litellm": ("LITELLM_GATEWAY_URL",),
}


def normalize_ai_provider(provider: str | None) -> str:
    """Normalize configured AI provider names for consistent validation and routing."""
    return (provider or "ollama").strip().lower() or "ollama"


def is_valid_http_url(value: str | None) -> bool:
    """Validate required HTTP(S) endpoint settings without leaking the raw value."""
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    parsed = urlparse(stripped)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


# ═══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════


def get_bool_env(key: str, default: bool = False) -> bool:
    """Return a strict boolean environment value.

    Sidar feature flags intentionally accept only ``true`` or ``false``
    (case-insensitive). Numeric and shell-style aliases such as ``1``, ``0``,
    ``yes`` or ``no`` are rejected so deployments cannot silently drift between
    incompatible boolean conventions.
    """
    raw_val = os.getenv(key)
    if raw_val is None or not raw_val.strip():
        return default
    val = raw_val.strip().lower()
    if val == "true":
        return True
    if val == "false":
        return False
    raise ValueError(f"{key} must be either 'true' or 'false' (case-insensitive); got {raw_val!r}.")


def get_external_bool_env(key: str, default: bool = False) -> bool:
    """Return a boolean environment value for third-party library conventions.

    External tools such as HuggingFace commonly document both ``1``/``0`` and
    ``true``/``false`` style booleans. Keep Sidar feature flags strict via
    :func:`get_bool_env`, but tolerate these aliases at integration boundaries
    so externally owned variables cannot crash Sidar during import.
    """
    raw_val = os.getenv(key)
    if raw_val is None or not raw_val.strip():
        return default
    val = raw_val.strip().lower()
    if val in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if val in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    raise ValueError(
        f"{key} must be a boolean accepted by the external provider "
        f"('true'/'false', '1'/'0', 'yes'/'no', or 'on'/'off'); got {raw_val!r}."
    )


def build_postgres_dsn(*, host: str | None = None) -> str:
    """Build Sidar's async PostgreSQL DSN from normalized POSTGRES_* variables."""
    user = os.getenv("POSTGRES_USER", "sidar").strip() or "sidar"
    password = os.getenv("POSTGRES_PASSWORD", "sidar")
    resolved_host = (
        host if host is not None else os.getenv("POSTGRES_HOST") or "127.0.0.1"
    ).strip() or "127.0.0.1"
    port = os.getenv("POSTGRES_PORT", "5432").strip() or "5432"
    database = os.getenv("POSTGRES_DB", "sidar").strip() or "sidar"

    quoted_user = quote(user, safe="")
    quoted_password = quote(password, safe="")
    quoted_database = quote(database, safe="")
    return f"postgresql+asyncpg://{quoted_user}:{quoted_password}@{resolved_host}:{port}/{quoted_database}"


def get_database_url() -> str:
    """Resolve DATABASE_URL, deriving it from POSTGRES_* variables when absent."""
    explicit_url = os.getenv("DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url
    return build_postgres_dsn()


def get_container_database_url() -> str:
    """Resolve the container DSN from SIDAR_CONTAINER_DATABASE_URL or POSTGRES_* values."""
    explicit_url = os.getenv("SIDAR_CONTAINER_DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url
    container_host = os.getenv("POSTGRES_CONTAINER_HOST", "postgres")
    return build_postgres_dsn(host=container_host)


def get_web_scrape_max_chars(default: int = 12000) -> int:
    """Resolve preferred WEB_SCRAPE_MAX_CHARS with deprecated WEB_FETCH fallback."""
    if os.getenv("WEB_SCRAPE_MAX_CHARS") is not None:
        return get_int_env("WEB_SCRAPE_MAX_CHARS", default)
    if os.getenv("WEB_FETCH_MAX_CHARS") is not None:
        warnings.warn(
            "WEB_FETCH_MAX_CHARS is deprecated; use WEB_SCRAPE_MAX_CHARS instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return get_int_env("WEB_FETCH_MAX_CHARS", default)
    return default


def get_int_env(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_float_env(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_list_env(key: str, default: list[str] | None = None, separator: str = ",") -> list[str]:
    if default is None:
        default = []
    value = os.getenv(key, "")
    if not value:
        return default
    return [item.strip() for item in value.split(separator) if item.strip()]


def get_prefixed_env(prefix_key: str, legacy_key: str, default: str = "") -> str:
    """Read a Sidar-prefixed env var while preserving a legacy fallback."""
    prefixed_value = os.getenv(prefix_key)
    if prefixed_value is not None:
        return prefixed_value
    return os.getenv(legacy_key, default)


def get_optional_prefixed_env(prefix_key: str, legacy_key: str) -> str | None:
    """Read an optional Sidar-prefixed env var with legacy fallback."""
    prefixed_value = os.getenv(prefix_key)
    if prefixed_value is not None:
        return prefixed_value
    return os.getenv(legacy_key)


def get_int_prefixed_env(prefix_key: str, legacy_key: str, default: int = 0) -> int:
    raw_value = get_prefixed_env(prefix_key, legacy_key, str(default))
    try:
        return int(raw_value)
    except (ValueError, TypeError):
        return default


def get_float_prefixed_env(prefix_key: str, legacy_key: str, default: float = 0.0) -> float:
    raw_value = get_prefixed_env(prefix_key, legacy_key, str(default))
    try:
        return float(raw_value)
    except (ValueError, TypeError):
        return default


def get_bool_prefixed_env(prefix_key: str, legacy_key: str, default: bool = False) -> bool:
    raw_value = get_optional_prefixed_env(prefix_key, legacy_key)
    if raw_value is None or not raw_value.strip():
        return default
    val = raw_value.strip().lower()
    if val == "true":
        return True
    if val == "false":
        return False
    raise ValueError(
        f"{prefix_key} / {legacy_key} must be either 'true' or 'false' "
        f"(case-insensitive); got {raw_value!r}."
    )


def _default_auto_migrate_enabled() -> bool:
    """Enable runtime Alembic auto-migrate outside production by default."""
    return os.getenv("SIDAR_ENV", "").strip().lower() != "production"


def get_db_pool_size_default() -> int:
    """
    DB havuz boyutu için çekirdek sayısı + PostgreSQL max_connections temelli varsayılan üretir.

    Formül:
    - taban hedef = CPU * DB_POOL_SIZE_PER_CORE (varsayılan 2)
    - üst sınır = POSTGRES_MAX_CONNECTIONS - DB_POOL_CONNECTION_RESERVE (varsayılan 10)
    - global tavan = DB_POOL_SIZE_HARD_CAP (varsayılan 50)
    """
    cpu_count = max(1, int(os.cpu_count() or 1))
    per_core = max(1, get_int_env("DB_POOL_SIZE_PER_CORE", 2))
    postgres_max_connections = max(1, get_int_env("POSTGRES_MAX_CONNECTIONS", 100))
    reserve = max(0, get_int_env("DB_POOL_CONNECTION_RESERVE", 10))
    hard_cap = max(1, get_int_env("DB_POOL_SIZE_HARD_CAP", 50))

    max_by_postgres = max(1, postgres_max_connections - reserve)
    return max(2, min(cpu_count * per_core, max_by_postgres, hard_cap))


# ═══════════════════════════════════════════════════════════════
# LOGLAMA SİSTEMİ  (dinamik, RotatingFileHandler)
# ═══════════════════════════════════════════════════════════════
_LOG_DIR = BASE_DIR / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("SIDAR_CONFIG_QUIET", "false")

_LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_FILE_PATH = BASE_DIR / os.getenv("LOG_FILE", "logs/sidar_system.log")
_LOG_MAX_BYTES = get_int_env("LOG_MAX_BYTES", 10_485_760)  # 10 MB
_LOG_BACKUP_CNT = get_int_env("LOG_BACKUP_COUNT", 5)
_VERBOSE_HTTP_LOGS = get_bool_env("SIDAR_VERBOSE_HTTP", False)
_NOISY_DEPENDENCY_LOGGERS = (
    "httpx",
    "huggingface_hub",
    "sentence_transformers",
    "alembic.runtime.migration",
)

_LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _repair_log_file_permissions(path: Path) -> None:
    """Backward-compatible wrapper for log permission repair helper."""
    repair_log_file_permissions(path)


_repair_log_file_permissions(_LOG_FILE_PATH)


def _configure_noisy_dependency_loggers(*, verbose_http: bool = _VERBOSE_HTTP_LOGS) -> None:
    """Keep chatty HTTP/HF dependency logs quiet unless explicitly requested."""
    configure_noisy_dependency_loggers(_NOISY_DEPENDENCY_LOGGERS, verbose_http=verbose_http)


_root_logger = logging.getLogger()
for _handler in list(_root_logger.handlers):
    with contextlib.suppress(Exception):
        _handler.flush()
        _handler.close()
    _root_logger.removeHandler(_handler)

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL_STR, logging.INFO),
    format=(
        "%(asctime)s %(levelname)-7s %(name)s [%(threadName)s]:%(lineno)d › %(message)s"
        if _LOG_LEVEL_STR == "DEBUG"
        else "%(asctime)s %(levelname)-7s %(name)s:%(lineno)d › %(message)s"
    ),
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

with contextlib.suppress(Exception):
    _root_logger.handlers[0].setLevel(getattr(logging, _LOG_LEVEL_STR, logging.INFO))

try:
    _file_handler = RotatingFileHandler(
        _LOG_FILE_PATH,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_CNT,
        encoding="utf-8",
    )
    _file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s [%(threadName)s]:%(lineno)d › %(message)s"
            if _LOG_LEVEL_STR == "DEBUG"
            else "%(asctime)s %(levelname)-7s %(name)s:%(lineno)d › %(message)s"
        )
    )
    _root_logger.addHandler(_file_handler)
except (PermissionError, OSError) as exc:
    _root_logger.warning(
        "⚠️ Log dosyasına yazılamıyor (%s). Sadece konsol loglama ile devam edilecek.",
        exc,
    )

_configure_noisy_dependency_loggers()

_DEPENDENCY_AUTO = object()


def _log_once_env(
    flag: str, fn: Callable[..., Any], *args: Any, fingerprint: str | None = None
) -> Any:
    current = os.environ.get(flag, "")
    token = fingerprint or "1"
    if current == token:
        logger.debug(
            "Config tekrar yüklendi; aynı fingerprint için bilgi logu bastırıldı: %s", flag
        )
        return
    os.environ[flag] = token
    fn(*args)


if ENV_PATH.exists() and not _SKIP_DEFAULT_DOTENV:
    _log_once_env(
        "SIDAR_ENV_LOGGED",
        logger.info,
        "✅ Ortam değişkenleri yüklendi: %s",
        ENV_PATH,
        fingerprint=str(ENV_PATH.resolve()),
    )

# ═══════════════════════════════════════════════════════════════
# SANDBOX KAYNAK KOTALARI (Docker/cgroups)
# ═══════════════════════════════════════════════════════════════
SANDBOX_LIMITS = {
    "memory": os.getenv("SANDBOX_MEMORY", "256m"),
    "cpus": os.getenv("SANDBOX_CPUS", "0.5"),
    "pids_limit": get_int_env("SANDBOX_PIDS_LIMIT", 64),
    "network": os.getenv("SANDBOX_NETWORK", "none"),
    "timeout": get_int_env("SANDBOX_TIMEOUT", 10),
}

# ═══════════════════════════════════════════════════════════════
# DONANIM TESPİTİ
# ═══════════════════════════════════════════════════════════════

# Project-supported PyTorch CUDA wheel guidance. Re-check periodically against
# the official PyTorch selector/release notes; keep this list aligned with
# install_sidar.sh's dynamic selector and prefer uv-managed installs in
# user-facing guidance. Last reviewed: 2026-06-11.
PYTORCH_STABLE_CUDA_WHEEL_TAGS: tuple[str, ...] = ("cu128", "cu126", "cu124")
PYTORCH_RECOMMENDED_CUDA_WHEEL_TAG: str = PYTORCH_STABLE_CUDA_WHEEL_TAGS[0]
PYTORCH_RECOMMENDED_CUDA_INDEX_URL: str = (
    f"https://download.pytorch.org/whl/{PYTORCH_RECOMMENDED_CUDA_WHEEL_TAG}"
)
PYTORCH_RECOMMENDED_CUDA_INSTALL_COMMAND: str = (
    "uv pip install torch torchvision " f"--index-url {PYTORCH_RECOMMENDED_CUDA_INDEX_URL}"
)


def _is_wsl2() -> bool:
    """WSL2 ortamını tespit eder (/proc/sys/kernel/osrelease içinde 'microsoft' arar)."""
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except Exception:
        return False


def check_hardware() -> HardwareInfo:
    """GPU/CPU donanımını tespit eder; PyTorch yoksa sessizce devam eder."""
    info = HardwareInfo(has_cuda=False, gpu_name="N/A")

    try:
        import multiprocessing

        info.cpu_count = multiprocessing.cpu_count()
    except Exception:
        info.cpu_count = 1

    wsl2 = _is_wsl2()
    if wsl2:
        _log_first_load_info(
            "ℹ️  WSL2 ortamı tespit edildi — CUDA, Windows sürücüsü üzerinden erişilecek."
        )

    if not get_bool_env("USE_GPU", True):
        logger.info("ℹ️  GPU kullanımı .env ile devre dışı bırakıldı.")
        info.gpu_name = "Devre Dışı (Kullanıcı)"
        return info

    try:
        import torch

        if torch.cuda.is_available():
            info.has_cuda = True
            info.gpu_count = torch.cuda.device_count()
            info.gpu_name = torch.cuda.get_device_name(0)
            info.cuda_version = torch.version.cuda or "N/A"
            try:
                props = torch.cuda.get_device_properties(0)
                info.gpu_vram_mb = int(getattr(props, "total_memory", 0) or 0) // (1024 * 1024)
            except Exception:
                info.gpu_vram_mb = 0
            _log_first_load_info(
                "🚀 GPU Hızlandırma Aktif: %s  (%d GPU tespit edildi, Torch CUDA build %s)",
                info.gpu_name,
                info.gpu_count,
                info.cuda_version,
            )
            # VRAM fraksiyonu: geriye dönük GPU_MEMORY_FRACTION + opsiyonel LLM/RAG ayrımı
            legacy_frac = get_float_env("GPU_MEMORY_FRACTION", 0.8)
            llm_frac = get_float_env("LLM_GPU_MEMORY_FRACTION", legacy_frac)
            rag_frac = get_float_env(
                "RAG_GPU_MEMORY_FRACTION", max(0.1, min(0.5, legacy_frac * 0.35))
            )
            if (
                os.getenv("LLM_GPU_MEMORY_FRACTION") is not None
                or os.getenv("RAG_GPU_MEMORY_FRACTION") is not None
            ):
                vram_budget = normalize_gpu_memory_fractions(llm_frac, rag_frac)
                frac = float(
                    vram_budget["gpu"] if vram_budget["normalized"] else vram_budget["total"]
                )
                if vram_budget["normalized"]:
                    logger.warning(
                        "LLM/RAG VRAM fraksiyonları toplamı %.2f; donanım probu %.2f toplamına normalize edilmiş bütçeyi uyguluyor "
                        "(LLM=%.2f, RAG=%.2f).",
                        vram_budget["original_total"],
                        vram_budget["gpu"],
                        vram_budget["llm"],
                        vram_budget["rag"],
                    )
            else:
                frac = legacy_frac
            if not (0.1 <= frac < 1.0):
                logger.warning(
                    "GPU bellek fraksiyonu=%.2f geçersiz aralık (0.1–0.99 bekleniyor, 1.0 dahil değil) "
                    "— varsayılan 0.8 kullanılıyor.",
                    frac,
                )
                frac = 0.8
            multi_gpu = get_bool_env("MULTI_GPU", False)
            target_device = max(0, get_int_env("GPU_DEVICE", 0))
            try:
                if multi_gpu and info.gpu_count > 1:
                    for device_idx in range(info.gpu_count):
                        torch.cuda.set_per_process_memory_fraction(frac, device=device_idx)
                    _log_first_load_info(
                        "🔧 VRAM fraksiyonu tüm GPU'lara uygulandı: %.0f%% (%d cihaz)",
                        frac * 100,
                        info.gpu_count,
                    )
                else:
                    if info.gpu_count > 0:
                        target_device = min(target_device, info.gpu_count - 1)
                    torch.cuda.set_per_process_memory_fraction(frac, device=target_device)
                    _log_first_load_info(
                        "🔧 VRAM fraksiyonu ayarlandı: %.0f%% (cuda:%d)",
                        frac * 100,
                        target_device,
                    )
            except Exception as exc:
                logger.debug("VRAM fraksiyon ayarı atlandı: %s", exc)
        else:
            if wsl2:
                logger.warning(
                    "⚠️  WSL2 — CUDA bulunamadı. Kontrol: "
                    "Windows NVIDIA sürücüsü güncel mi? "
                    "PyTorch resmi selector ile uyumlu CUDA wheel kurulumu yapıldı mı? "
                    "Desteklenen stabil wheel etiketleri: %s. Örnek: %s",
                    ", ".join(PYTORCH_STABLE_CUDA_WHEEL_TAGS),
                    PYTORCH_RECOMMENDED_CUDA_INSTALL_COMMAND,
                )
            else:
                logger.info("ℹ️  CUDA bulunamadı — CPU modunda çalışılacak.")
            info.gpu_name = "CUDA Bulunamadı"
    except ImportError:
        logger.warning("⚠️  PyTorch kurulu değil; GPU kontrolü atlanıyor.")
        info.gpu_name = "PyTorch Yok"
    except Exception as exc:
        logger.warning("⚠️  Donanım kontrolü hatası: %s", exc)
        info.gpu_name = "Tespit Edilemedi"

    # sürücü sürümü — nvidia-ml-py varsa al
    try:
        import pynvml

        pynvml.nvmlInit()
        info.driver_version = pynvml.nvmlSystemGetDriverVersion()
        pynvml.nvmlShutdown()
    except Exception as exc:
        logger.debug(
            "NVML driver version okunamadı (opsiyonel bağımlılık/ortam kısıtı olabilir): %s",
            exc,
        )

    return info


# ═══════════════════════════════════════════════════════════════
# ANA YAPILANDIRMA SINIFI
# ═══════════════════════════════════════════════════════════════


class Config:
    """
    Sidar Merkezi Yapılandırma Sınıfı.

    Sürüm değeri `sidar_version.PRODUCT_VERSION` üzerinden paket metadata'sı / pyproject
    kaynaklı tek merkezden alınır.
    """

    # ─── Genel ───────────────────────────────────────────────
    PROJECT_NAME: str = "Sidar"
    VERSION: str = PRODUCT_VERSION
    DEBUG_MODE: bool = get_bool_env("DEBUG_MODE", False)
    ENABLE_MULTI_AGENT: bool = (
        True  # Legacy bayrak kaldırıldı; sistem daima Supervisor akışında çalışır.
    )
    ENABLE_AUTONOMOUS_SELF_HEAL: bool = get_bool_env("ENABLE_AUTONOMOUS_SELF_HEAL", False)
    SELF_HEAL_MAX_PATCHES: int = get_int_env("SELF_HEAL_MAX_PATCHES", 3)
    SELF_HEAL_PLAN_MAX_RETRIES: int = get_int_env("SELF_HEAL_PLAN_MAX_RETRIES", 3)
    SELF_HEAL_PLAN_TIMEOUT_SECONDS: int = get_int_env("SELF_HEAL_PLAN_TIMEOUT_SECONDS", 180)
    SELF_HEAL_SKIP_FULL_SCOPE_MIN_FILES: int = get_int_env("SELF_HEAL_SKIP_FULL_SCOPE_MIN_FILES", 6)
    SELF_HEAL_LOCAL_SCOPE_LIMIT: int = get_int_prefixed_env(
        "SIDAR_SELF_HEAL_LOCAL_SCOPE_LIMIT", "SELF_HEAL_LOCAL_SCOPE_LIMIT", 200
    )
    SELF_HEAL_HITL_SCOPE_THRESHOLD: int = get_int_prefixed_env(
        "SIDAR_SELF_HEAL_HITL_SCOPE_THRESHOLD", "SELF_HEAL_HITL_SCOPE_THRESHOLD", 3
    )
    SELF_HEAL_AUTONOMOUS_BATCH_SIZE: int = get_int_prefixed_env(
        "SIDAR_SELF_HEAL_AUTONOMOUS_BATCH_SIZE", "SELF_HEAL_AUTONOMOUS_BATCH_SIZE", 5
    )
    SELF_HEAL_DEFAULT_DECISION: str = (
        (
            get_optional_prefixed_env(
                "SIDAR_SELF_HEAL_DEFAULT_DECISION", "SELF_HEAL_DEFAULT_DECISION"
            )
            or "prompt"
        )
        .strip()
        .lower()
    )
    RUFF_AUTOFIX_UNSAFE_RULES: str | None = get_optional_prefixed_env(
        "SIDAR_RUFF_AUTOFIX_UNSAFE_RULES", "RUFF_AUTOFIX_UNSAFE_RULES"
    )

    # ─── Dizinler ────────────────────────────────────────────
    BASE_DIR: Path = BASE_DIR
    TEMP_DIR: Path = BASE_DIR / "temp"
    LOGS_DIR: Path = BASE_DIR / "logs"
    DATA_DIR: Path = BASE_DIR / "data"
    MEMORY_FILE: Path = DATA_DIR / "memory.json"

    REQUIRED_DIRS: list[Path] = [BASE_DIR / "temp", BASE_DIR / "logs", BASE_DIR / "data"]

    # ─── AI Sağlayıcı ────────────────────────────────────────
    AI_PROVIDER: str = (
        LLM_SETTINGS.AI_PROVIDER
    )  # "ollama" | "gemini" | "openai" | "anthropic" | "litellm"
    GEMINI_API_KEY: str = LLM_SETTINGS.GEMINI_API_KEY
    GEMINI_MODEL: str = LLM_SETTINGS.GEMINI_MODEL
    OPENAI_API_KEY: str = LLM_SETTINGS.OPENAI_API_KEY
    OPENAI_MODEL: str = LLM_SETTINGS.OPENAI_MODEL
    OPENAI_TIMEOUT: int = LLM_SETTINGS.OPENAI_TIMEOUT
    LLM_MAX_RETRIES: int = LLM_SETTINGS.LLM_MAX_RETRIES
    LLM_RETRY_BASE_DELAY: float = LLM_SETTINGS.LLM_RETRY_BASE_DELAY
    LLM_RETRY_MAX_DELAY: float = LLM_SETTINGS.LLM_RETRY_MAX_DELAY
    ANTHROPIC_API_KEY: str = LLM_SETTINGS.ANTHROPIC_API_KEY
    ANTHROPIC_MODEL: str = LLM_SETTINGS.ANTHROPIC_MODEL
    ANTHROPIC_TIMEOUT: int = LLM_SETTINGS.ANTHROPIC_TIMEOUT

    # ─── LiteLLM Gateway ─────────────────────────────────────
    LITELLM_GATEWAY_URL: str = LLM_SETTINGS.LITELLM_GATEWAY_URL
    LITELLM_API_KEY: str = LLM_SETTINGS.LITELLM_API_KEY
    LITELLM_MODEL: str = LLM_SETTINGS.LITELLM_MODEL
    LITELLM_FALLBACK_MODELS: list[str] = get_list_env("LITELLM_FALLBACK_MODELS", [])
    LITELLM_TIMEOUT: int = LLM_SETTINGS.LITELLM_TIMEOUT

    # ─── Ollama ──────────────────────────────────────────────
    OLLAMA_URL: str = LLM_SETTINGS.OLLAMA_URL
    OLLAMA_TIMEOUT: int = LLM_SETTINGS.OLLAMA_TIMEOUT
    OLLAMA_KEEP_ALIVE: str = LLM_SETTINGS.OLLAMA_KEEP_ALIVE
    OLLAMA_NUM_BATCH: int = get_int_env("OLLAMA_NUM_BATCH", LLM_SETTINGS.OLLAMA_NUM_BATCH)
    OLLAMA_CODING_NUM_CTX: int = get_int_env(
        "OLLAMA_CODING_NUM_CTX", LLM_SETTINGS.OLLAMA_CODING_NUM_CTX
    )
    OLLAMA_FORCE_KILL_ON_SHUTDOWN: bool = get_bool_env("OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)
    CODING_MODEL: str = LLM_SETTINGS.CODING_MODEL
    TEXT_MODEL: str = os.getenv("TEXT_MODEL", "gemma2:9b")

    # ─── Erişim Seviyesi (OpenClaw) ──────────────────────────
    SIDAR_SKIP_DEFAULT_DOTENV: bool = _skip_default_dotenv_layers()
    SIDAR_KEYS_FILE: str = os.getenv("SIDAR_KEYS_FILE", "~/.sidar_keys.env")
    ACCESS_LEVEL: str = os.getenv("ACCESS_LEVEL", "sandbox")
    API_KEY: str = os.getenv("API_KEY", "")

    # ─── JWT Auth (stateless) ─────────────────────────────────
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", os.getenv("API_KEY", ""))
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_TTL_DAYS: int = get_int_env("JWT_TTL_DAYS", 7)

    # ─── GitHub ──────────────────────────────────────────────
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "")
    GITHUB_WEBHOOK_SECRET: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    GITHUB_WEBHOOK_REQUIRE_SIGNATURE: bool = get_bool_env("GITHUB_WEBHOOK_REQUIRE_SIGNATURE", True)

    # ─── HuggingFace ─────────────────────────────────────────
    HF_TOKEN: str = os.getenv("HF_TOKEN", "")
    HF_HUB_OFFLINE: bool = get_external_bool_env("HF_HUB_OFFLINE", False)
    HF_USE_LOCAL_CACHE_ONLY: bool = get_bool_env("HF_USE_LOCAL_CACHE_ONLY", False)

    # ─── Donanım & GPU ───────────────────────────────────────
    USE_GPU: bool = get_bool_env("USE_GPU", True)
    # CPU-only hosts should boot without failing critical validation. Installers may
    # set REQUIRE_GPU=true when CUDA hardware is detected and desired.
    REQUIRE_GPU: bool = get_bool_env("REQUIRE_GPU", False)
    GPU_INFO: str = "Devre Dışı / CPU Modu"
    GPU_COUNT: int = 0
    CPU_COUNT: int = os.cpu_count() or 1
    CUDA_VERSION: str = "N/A"
    DRIVER_VERSION: str = "N/A"
    GPU_VRAM_MB: int = 0
    OLLAMA_GPU_REQUEST_POOL_SIZE: int = get_int_env("OLLAMA_GPU_REQUEST_POOL_SIZE", 0)

    _hardware_loaded: bool = False

    # Birden fazla GPU varsa hangi device kullanılsın (0-indexed)
    GPU_DEVICE: int = get_int_env("GPU_DEVICE", 0)

    # Çoklu GPU dağıtık mod
    MULTI_GPU: bool = get_bool_env("MULTI_GPU", False)

    # Embedding ve model yüklemeleri için VRAM fraksiyonu (0.1–0.99 bekleniyor, 1.0 dahil değil)
    GPU_MEMORY_FRACTION: float = get_float_env("GPU_MEMORY_FRACTION", 0.8)
    # Yerel LLM ve RAG için ayrı bellek bütçeleri (opsiyonel)
    LLM_GPU_MEMORY_FRACTION: float = get_float_env("LLM_GPU_MEMORY_FRACTION", GPU_MEMORY_FRACTION)
    RAG_GPU_MEMORY_FRACTION: float = get_float_env(
        "RAG_GPU_MEMORY_FRACTION", max(0.1, min(0.5, GPU_MEMORY_FRACTION * 0.35))
    )

    # FP16 / mixed precision  →  embedding modellerinde bellek tasarrufu
    GPU_MIXED_PRECISION: bool = get_bool_env("GPU_MIXED_PRECISION", False)

    # ─── Uygulama ────────────────────────────────────────────
    MAX_MEMORY_TURNS: int = get_int_env("MAX_MEMORY_TURNS", 20)
    MEMORY_SUMMARY_KEEP_LAST: int = get_int_env("MEMORY_SUMMARY_KEEP_LAST", 4)
    CLI_FAST_MODE: bool = get_bool_env("CLI_FAST_MODE", False)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    RESPONSE_LANGUAGE: str = os.getenv("RESPONSE_LANGUAGE", "tr")

    # ─── Loglama ─────────────────────────────────────────────
    LOG_FILE: Path = _LOG_FILE_PATH
    LOG_MAX_BYTES: int = _LOG_MAX_BYTES
    LOG_BACKUP_COUNT: int = _LOG_BACKUP_CNT

    # ─── ReAct Döngüsü ───────────────────────────────────────
    MAX_REACT_STEPS: int = get_int_env("MAX_REACT_STEPS", 10)
    REACT_TIMEOUT: int = get_int_env("REACT_TIMEOUT", 60)
    SWARM_TASK_TIMEOUT_SECONDS: int = get_int_env("SWARM_TASK_TIMEOUT_SECONDS", REACT_TIMEOUT)
    SUBTASK_MAX_STEPS: int = get_int_env("SUBTASK_MAX_STEPS", 5)
    AUTO_HANDLE_TIMEOUT: int = get_int_env("AUTO_HANDLE_TIMEOUT", 12)

    # ─── API Rate Limiting ───────────────────────────────────
    SIDAR_RATE_LIMIT_WINDOW: int = get_int_prefixed_env(
        "SIDAR_RATE_LIMIT_WINDOW", "RATE_LIMIT_WINDOW", 60
    )
    SIDAR_RATE_LIMIT_CHAT: int = get_int_prefixed_env(
        "SIDAR_RATE_LIMIT_CHAT", "RATE_LIMIT_CHAT", 20
    )
    SIDAR_RATE_LIMIT_MUTATIONS: int = get_int_prefixed_env(
        "SIDAR_RATE_LIMIT_MUTATIONS", "RATE_LIMIT_MUTATIONS", 60
    )
    SIDAR_RATE_LIMIT_GET_IO: int = get_int_prefixed_env(
        "SIDAR_RATE_LIMIT_GET_IO", "RATE_LIMIT_GET_IO", 30
    )
    RATE_LIMIT_WINDOW: int = SIDAR_RATE_LIMIT_WINDOW
    RATE_LIMIT_CHAT: int = SIDAR_RATE_LIMIT_CHAT
    RATE_LIMIT_MUTATIONS: int = SIDAR_RATE_LIMIT_MUTATIONS
    RATE_LIMIT_GET_IO: int = SIDAR_RATE_LIMIT_GET_IO
    SIDAR_REDIS_URL: str = get_prefixed_env(
        "SIDAR_REDIS_URL", "REDIS_URL", "redis://localhost:6379/0"
    )
    REDIS_URL: str = SIDAR_REDIS_URL
    SIDAR_REDIS_MAX_CONNECTIONS: int = get_int_prefixed_env(
        "SIDAR_REDIS_MAX_CONNECTIONS", "REDIS_MAX_CONNECTIONS", LLM_SETTINGS.REDIS_MAX_CONNECTIONS
    )
    REDIS_MAX_CONNECTIONS: int = SIDAR_REDIS_MAX_CONNECTIONS
    SIDAR_REDIS_CONNECT_TIMEOUT: float = get_float_prefixed_env(
        "SIDAR_REDIS_CONNECT_TIMEOUT", "REDIS_CONNECT_TIMEOUT", 0.5
    )
    REDIS_CONNECT_TIMEOUT: float = SIDAR_REDIS_CONNECT_TIMEOUT
    SIDAR_REDIS_SOCKET_TIMEOUT: float = get_float_prefixed_env(
        "SIDAR_REDIS_SOCKET_TIMEOUT", "REDIS_SOCKET_TIMEOUT", 0.5
    )
    REDIS_SOCKET_TIMEOUT: float = SIDAR_REDIS_SOCKET_TIMEOUT
    ENABLE_DISTRIBUTED_AGENT_LOCKS: bool = get_bool_env("ENABLE_DISTRIBUTED_AGENT_LOCKS", True)
    DISTRIBUTED_AGENT_LOCK_REQUIRED: bool = get_bool_env("DISTRIBUTED_AGENT_LOCK_REQUIRED", False)
    DISTRIBUTED_AGENT_LOCK_TTL_SECONDS: int = get_int_env(
        "DISTRIBUTED_AGENT_LOCK_TTL_SECONDS", 1800
    )
    DISTRIBUTED_AGENT_LOCK_TIMEOUT_MS: int = get_int_env("DISTRIBUTED_AGENT_LOCK_TIMEOUT_MS", 250)
    ENABLE_DEPENDENCY_HEALTHCHECKS: bool = get_bool_env("ENABLE_DEPENDENCY_HEALTHCHECKS", False)
    HEALTHCHECK_CONNECT_TIMEOUT_MS: int = get_int_env("HEALTHCHECK_CONNECT_TIMEOUT_MS", 250)
    # Güvenilir ters proxy IP listesi (virgülle ayrılmış); boşsa proxy başlıkları kabul edilmez
    TRUSTED_PROXIES: frozenset[str] = frozenset(get_list_env("TRUSTED_PROXIES", ["127.0.0.1"]))
    TRUSTED_PROXIES_LIST: list[str] = sorted(TRUSTED_PROXIES)
    # RAG yükleme boyut limiti (varsayılan 50 MB)
    MAX_RAG_UPLOAD_BYTES: int = get_int_env("MAX_RAG_UPLOAD_BYTES", 50 * 1024 * 1024)
    # Metrics endpoint'leri için statik Bearer token (boşsa yalnızca admin kullanıcılar erişebilir)
    METRICS_TOKEN: str = os.getenv("METRICS_TOKEN", "")

    # ─── Veritabanı (v3.0 çoklu kullanıcı hazırlığı) ────────
    DATABASE_URL: str = get_database_url()
    CONTAINER_DATABASE_URL: str | None = None
    SIDAR_CONTAINER_DATABASE_URL: str = get_container_database_url()
    DB_POOL_SIZE: int = get_int_env("DB_POOL_SIZE", get_db_pool_size_default())
    DB_DEGRADED_MODE_ON_POSTGRES_FAILURE: bool = get_bool_env(
        "DB_DEGRADED_MODE_ON_POSTGRES_FAILURE", True
    )
    DB_DEGRADED_SQLITE_URL: str = os.getenv("DB_DEGRADED_SQLITE_URL", "")
    DB_SCHEMA_VERSION_TABLE: str = os.getenv("DB_SCHEMA_VERSION_TABLE", "schema_versions")
    DB_SCHEMA_TARGET_VERSION: int = get_int_env("DB_SCHEMA_TARGET_VERSION", 1)
    SIDAR_AUTO_MIGRATE: bool = get_bool_env("SIDAR_AUTO_MIGRATE", _default_auto_migrate_enabled())

    # ─── Gözlemlenebilirlik (OpenTelemetry) ───────────────────
    ENABLE_TRACING: bool = get_bool_env("ENABLE_TRACING", False)
    OTEL_EXPORTER_ENDPOINT: str = os.getenv("OTEL_EXPORTER_ENDPOINT", "http://jaeger:4317")
    OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "sidar")
    OTEL_INSTRUMENT_FASTAPI: bool = get_bool_env("OTEL_INSTRUMENT_FASTAPI", True)
    OTEL_INSTRUMENT_HTTPX: bool = get_bool_env("OTEL_INSTRUMENT_HTTPX", True)

    # ─── Semantic Cache (v4.0) ───────────────────────────────
    ENABLE_SEMANTIC_CACHE: bool = get_bool_env("ENABLE_SEMANTIC_CACHE", False)
    SEMANTIC_CACHE_THRESHOLD: float = get_float_env("SEMANTIC_CACHE_THRESHOLD", 0.95)
    SEMANTIC_CACHE_TTL: int = LLM_SETTINGS.SEMANTIC_CACHE_TTL
    SEMANTIC_CACHE_MAX_ITEMS: int = LLM_SETTINGS.SEMANTIC_CACHE_MAX_ITEMS
    SIDAR_EVENT_BUS_BACKEND: str = os.getenv("SIDAR_EVENT_BUS_BACKEND", "redis")
    SIDAR_EVENT_BUS_CHANNEL: str = os.getenv("SIDAR_EVENT_BUS_CHANNEL", "sidar:agent_events")
    SIDAR_EVENT_BUS_GROUP: str = os.getenv("SIDAR_EVENT_BUS_GROUP", "sidar:agent_events:cg")
    SIDAR_EVENT_BUS_DLQ_CHANNEL: str = os.getenv(
        "SIDAR_EVENT_BUS_DLQ_CHANNEL", f"{SIDAR_EVENT_BUS_CHANNEL}:dlq"
    )
    SIDAR_EVENT_BUS_DLQ_MAXLEN: int = get_int_env("SIDAR_EVENT_BUS_DLQ_MAXLEN", 1000)
    SIDAR_EVENT_BUS_DLQ_PERSIST_PATH: str = os.getenv("SIDAR_EVENT_BUS_DLQ_PERSIST_PATH", "")
    SIDAR_EVENT_BUS_DLQ_PERSIST_BATCH_SIZE: int = get_int_env(
        "SIDAR_EVENT_BUS_DLQ_PERSIST_BATCH_SIZE", 100
    )
    SIDAR_EVENT_BUS_DLQ_PERSIST_FLUSH_INTERVAL: float = get_float_env(
        "SIDAR_EVENT_BUS_DLQ_PERSIST_FLUSH_INTERVAL", 1.0
    )
    SIDAR_RABBITMQ_URL: str = get_prefixed_env(
        "SIDAR_RABBITMQ_URL", "RABBITMQ_URL", "amqp://guest:guest@localhost/"
    )
    RABBITMQ_URL: str = SIDAR_RABBITMQ_URL
    SIDAR_EVENT_BUS_KAFKA_TOPIC: str = os.getenv(
        "SIDAR_EVENT_BUS_KAFKA_TOPIC", "sidar.agent_events"
    )
    SIDAR_EVENT_BUS_KAFKA_GROUP: str = os.getenv("SIDAR_EVENT_BUS_KAFKA_GROUP", "")
    SIDAR_KAFKA_BOOTSTRAP_SERVERS: str = get_prefixed_env(
        "SIDAR_KAFKA_BOOTSTRAP_SERVERS", "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
    )
    KAFKA_BOOTSTRAP_SERVERS: str = SIDAR_KAFKA_BOOTSTRAP_SERVERS
    SIDAR_EVENT_BUS_CB_FAILURE_THRESHOLD: int = get_int_env(
        "SIDAR_EVENT_BUS_CB_FAILURE_THRESHOLD", 5
    )
    SIDAR_EVENT_BUS_CB_OPEN_SECONDS: float = get_float_env("SIDAR_EVENT_BUS_CB_OPEN_SECONDS", 15.0)

    # ─── Web Arama ───────────────────────────────────────────
    SEARCH_ENGINE: str = os.getenv("SEARCH_ENGINE", "auto")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    GOOGLE_SEARCH_API_KEY: str = os.getenv("GOOGLE_SEARCH_API_KEY", "")
    GOOGLE_SEARCH_CX: str = os.getenv("GOOGLE_SEARCH_CX", "")
    WEB_SEARCH_MAX_RESULTS: int = get_int_env("WEB_SEARCH_MAX_RESULTS", 5)
    WEB_FETCH_TIMEOUT: int = get_int_env("WEB_FETCH_TIMEOUT", 15)
    # Eski ad geriye dönük uyumluluk için tutulur; tercih edilen anahtar WEB_SCRAPE_MAX_CHARS.
    WEB_FETCH_MAX_CHARS: int = get_int_env("WEB_FETCH_MAX_CHARS", 12000)
    # Yeni ad (tercih edilen): scrape/okuma karakter limiti
    WEB_SCRAPE_MAX_CHARS: int = get_web_scrape_max_chars(WEB_FETCH_MAX_CHARS)

    # ─── Paket Bilgi ─────────────────────────────────────────
    PACKAGE_INFO_TIMEOUT: int = get_int_env("PACKAGE_INFO_TIMEOUT", 12)
    PACKAGE_INFO_CACHE_TTL: int = get_int_env("PACKAGE_INFO_CACHE_TTL", 1800)

    # ─── RAG — Belge Deposu ──────────────────────────────────
    RAG_DIR: Path = BASE_DIR / os.getenv("RAG_DIR", "data/rag")
    RAG_TOP_K: int = get_int_env("RAG_TOP_K", 3)
    RAG_CHUNK_SIZE: int = get_int_env("RAG_CHUNK_SIZE", 1000)
    RAG_CHUNK_OVERLAP: int = get_int_env("RAG_CHUNK_OVERLAP", 200)
    # Büyük dosya eşiği: bu karakter sayısını geçen dosyalar okunduğunda
    # RAG deposuna ekleme önerilir (varsayılan ≈ 400 satır / ~20 KB).
    RAG_FILE_THRESHOLD: int = get_int_env("RAG_FILE_THRESHOLD", 20000)
    RAG_VECTOR_BACKEND: str = os.getenv("RAG_VECTOR_BACKEND", "chroma")  # chroma | pgvector | bm25
    PGVECTOR_TABLE: str = os.getenv("PGVECTOR_TABLE", "rag_embeddings")
    PGVECTOR_EMBEDDING_DIM: int = get_int_env("PGVECTOR_EMBEDDING_DIM", 384)
    PGVECTOR_EMBEDDING_MODEL: str = os.getenv("PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # ─── Docker REPL Sandbox ─────────────────────────────────
    SANDBOX_LIMITS: dict[str, Any] = dict(SANDBOX_LIMITS)
    DOCKER_PYTHON_IMAGE: str = get_prefixed_env(
        "SIDAR_DOCKER_PYTHON_IMAGE", "DOCKER_PYTHON_IMAGE", "python:3.11-slim"
    )
    DOCKER_IMAGE: str = get_prefixed_env("SIDAR_DOCKER_IMAGE", "DOCKER_IMAGE", "")
    _DOCKER_TEST_IMAGE_RAW: str | None = get_optional_prefixed_env(
        "SIDAR_DOCKER_TEST_IMAGE", "DOCKER_TEST_IMAGE"
    )
    DOCKER_TEST_IMAGE_EXPLICIT: bool = bool((_DOCKER_TEST_IMAGE_RAW or "").strip())
    DOCKER_TEST_IMAGE: str = (_DOCKER_TEST_IMAGE_RAW or DOCKER_PYTHON_IMAGE).strip()
    DOCKER_RUNTIME: str = get_prefixed_env("SIDAR_DOCKER_RUNTIME", "DOCKER_RUNTIME", "")
    DOCKER_ALLOWED_RUNTIMES: list[str] = get_list_env(
        "DOCKER_ALLOWED_RUNTIMES", ["", "runc", "runsc", "kata-runtime"]
    )
    DOCKER_MICROVM_MODE: str = get_prefixed_env(
        "SIDAR_DOCKER_MICROVM_MODE", "DOCKER_MICROVM_MODE", "off"
    )
    DOCKER_MEM_LIMIT: str = get_prefixed_env("SIDAR_DOCKER_MEM_LIMIT", "DOCKER_MEM_LIMIT", "256m")
    DOCKER_NETWORK_DISABLED: bool = get_bool_prefixed_env(
        "SIDAR_DOCKER_NETWORK_DISABLED", "DOCKER_NETWORK_DISABLED", True
    )
    DOCKER_NANO_CPUS: int = get_int_prefixed_env(
        "SIDAR_DOCKER_NANO_CPUS", "DOCKER_NANO_CPUS", 1_000_000_000
    )
    # Maksimum Docker sandbox çalışma süresi (saniye) — sonsuz döngü koruması
    DOCKER_EXEC_TIMEOUT: int = get_int_env("DOCKER_EXEC_TIMEOUT", 10)
    # Docker zorunlu mod: True ise Docker erişilemezse yerel subprocess fallback engellenir
    DOCKER_REQUIRED: bool = get_bool_prefixed_env("SIDAR_DOCKER_REQUIRED", "DOCKER_REQUIRED", False)
    PYTHON_VIRTUAL_ENV: str = os.getenv("VIRTUAL_ENV", "")
    PYTHON_CONDA_PREFIX: str = os.getenv("CONDA_PREFIX", "")

    # ─── Bellek Şifrelemesi ───────────────────────────────────────
    # Boş bırakılırsa şifreleme devre dışı (varsayılan).
    # Fernet anahtarı üretmek için:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    MEMORY_ENCRYPTION_KEY: str = os.getenv("MEMORY_ENCRYPTION_KEY", "")

    # ─── Web Arayüzü ─────────────────────────────────────────
    WEB_HOST: str = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT: int = get_int_env("WEB_PORT", 7860)
    WEB_GPU_PORT: int = get_int_env("WEB_GPU_PORT", 7861)

    # ─── Observability Bağlantı Noktaları ───────────────────
    # GRAFANA_URL ayarlanmazsa varsayılan olarak yerel kurulum portu kullanılır.
    GRAFANA_URL: str = os.getenv("GRAFANA_URL", "http://localhost:3000")

    # ─── Multi-Agent geçiş ayarları ─────────────────────────
    REVIEWER_TEST_COMMAND: str = os.getenv("REVIEWER_TEST_COMMAND", "uv run pytest")

    # ─── DLP — Veri Kaybı Önleme ─────────────────────────────
    DLP_ENABLED: bool = get_bool_env("DLP_ENABLED", True)
    DLP_LOG_DETECTIONS: bool = get_bool_env("DLP_LOG_DETECTIONS", False)

    # ─── HITL — Human-in-the-Loop Onay Geçidi ────────────────
    HITL_ENABLED: bool = get_bool_env("HITL_ENABLED", False)
    HITL_TIMEOUT_SECONDS: int = get_int_env("HITL_TIMEOUT_SECONDS", 120)

    # ─── LLM-as-a-Judge Kalite Değerlendirmesi ────────────────
    JUDGE_ENABLED: bool = get_bool_prefixed_env("SIDAR_JUDGE_ENABLED", "JUDGE_ENABLED", False)
    JUDGE_MODEL: str = get_prefixed_env("SIDAR_JUDGE_MODEL", "JUDGE_MODEL", "")
    JUDGE_PROVIDER: str = get_prefixed_env("SIDAR_JUDGE_PROVIDER", "JUDGE_PROVIDER", "ollama")
    JUDGE_SAMPLE_RATE: float = max(
        0.0,
        min(1.0, get_float_prefixed_env("SIDAR_JUDGE_SAMPLE_RATE", "JUDGE_SAMPLE_RATE", 0.2)),
    )
    JUDGE_AUTO_FEEDBACK_ENABLED: bool = get_bool_prefixed_env(
        "SIDAR_JUDGE_AUTO_FEEDBACK_ENABLED", "JUDGE_AUTO_FEEDBACK_ENABLED", True
    )
    JUDGE_AUTO_FEEDBACK_THRESHOLD: float = max(
        0.0,
        min(
            10.0,
            get_float_prefixed_env(
                "SIDAR_JUDGE_AUTO_FEEDBACK_THRESHOLD", "JUDGE_AUTO_FEEDBACK_THRESHOLD", 8.0
            ),
        ),
    )
    JUDGE_RESPONSE_MODEL: str = get_prefixed_env(
        "SIDAR_JUDGE_RESPONSE_MODEL", "JUDGE_RESPONSE_MODEL", ""
    )

    # ─── Cost-Aware Model Routing (v5.0) ──────────────────────
    ENABLE_COST_ROUTING: bool = get_bool_env("ENABLE_COST_ROUTING", False)
    # 0.0–1.0: Bu eşiğin altındaki sorgular lokal modele yönlendirilir
    COST_ROUTING_COMPLEXITY_THRESHOLD: float = get_float_env(
        "COST_ROUTING_COMPLEXITY_THRESHOLD", 0.55
    )
    # Lokal sağlayıcı (basit sorgular için)
    COST_ROUTING_LOCAL_PROVIDER: str = os.getenv("COST_ROUTING_LOCAL_PROVIDER", "ollama")
    COST_ROUTING_LOCAL_MODEL: str = os.getenv("COST_ROUTING_LOCAL_MODEL", "")
    # Bulut sağlayıcı (karmaşık sorgular için; boşsa varsayılan sağlayıcı kullanılır)
    COST_ROUTING_CLOUD_PROVIDER: str = os.getenv("COST_ROUTING_CLOUD_PROVIDER", "")
    COST_ROUTING_CLOUD_MODEL: str = os.getenv("COST_ROUTING_CLOUD_MODEL", "")
    # Bu günlük bütçe (USD) aşılırsa tüm sorgular lokal modele yönlendirilir
    COST_ROUTING_DAILY_BUDGET_USD: float = get_float_env("COST_ROUTING_DAILY_BUDGET_USD", 1.0)
    # Tek bir isteğin yaklaşık token eşiği; aşılırsa lokal modele fallback uygulanır.
    COST_ROUTING_TOKEN_THRESHOLD: int = get_int_env("COST_ROUTING_TOKEN_THRESHOLD", 0)

    # ─── Entity/Persona Memory (v5.0) ─────────────────────────
    ENABLE_ENTITY_MEMORY: bool = get_bool_env("ENABLE_ENTITY_MEMORY", True)
    # Güncellenmemiş kayıtların saklanma süresi (gün); 0 = sonsuz
    ENTITY_MEMORY_TTL_DAYS: int = get_int_env("ENTITY_MEMORY_TTL_DAYS", 90)
    # Kullanıcı başına maksimum persona anahtarı sayısı (LRU eviction)
    ENTITY_MEMORY_MAX_PER_USER: int = get_int_env("ENTITY_MEMORY_MAX_PER_USER", 100)

    # ─── Active Learning + LoRA/QLoRA (v6.0) ────────────────────
    ENABLE_ACTIVE_LEARNING: bool = get_bool_env("ENABLE_ACTIVE_LEARNING", True)
    # Minimum geri bildirim puanı (bu değer ve üzeri export edilir)
    AL_MIN_RATING_FOR_TRAIN: int = get_int_env("AL_MIN_RATING_FOR_TRAIN", 1)
    # LoRA eğitimini etkinleştir (peft/transformers gerektirir)
    ENABLE_LORA_TRAINING: bool = get_bool_env("ENABLE_LORA_TRAINING", False)
    # Fine-tuning için temel model (HuggingFace hub ID)
    LORA_BASE_MODEL: str = os.getenv("LORA_BASE_MODEL", "")
    LORA_RANK: int = get_int_env("LORA_RANK", 8)
    LORA_ALPHA: int = get_int_env("LORA_ALPHA", 16)
    LORA_DROPOUT: float = get_float_env("LORA_DROPOUT", 0.05)
    LORA_EPOCHS: int = get_int_env("LORA_EPOCHS", 3)
    LORA_BATCH_SIZE: int = get_int_env("LORA_BATCH_SIZE", 4)
    LORA_USE_4BIT: bool = get_bool_env("LORA_USE_4BIT", True)
    LORA_OUTPUT_DIR: str = os.getenv("LORA_OUTPUT_DIR", "data/lora_adapters")
    # Ar-Ge: Judge/feedback sinyallerinden sürekli öğrenme bundle'ı üret
    ENABLE_CONTINUOUS_LEARNING: bool = get_bool_env("ENABLE_CONTINUOUS_LEARNING", False)
    CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES: int = get_int_env(
        "CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES", 20
    )
    CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES: int = get_int_env(
        "CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES", 10
    )
    CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS: int = get_int_env(
        "CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS", 5000
    )
    CONTINUOUS_LEARNING_COOLDOWN_SECONDS: int = get_int_env(
        "CONTINUOUS_LEARNING_COOLDOWN_SECONDS", 3600
    )
    CONTINUOUS_LEARNING_OUTPUT_DIR: str = os.getenv(
        "CONTINUOUS_LEARNING_OUTPUT_DIR", "data/continuous_learning"
    )
    CONTINUOUS_LEARNING_SFT_FORMAT: str = os.getenv("CONTINUOUS_LEARNING_SFT_FORMAT", "alpaca")

    # ─── Multimodal Vision (v6.0) ───────────────────────────────
    ENABLE_VISION: bool = get_bool_env("ENABLE_VISION", True)
    # Maksimum görsel boyutu (byte) — varsayılan 10 MB
    VISION_MAX_IMAGE_BYTES: int = get_int_env("VISION_MAX_IMAGE_BYTES", 10485760)
    ENABLE_MULTIMODAL: bool = get_bool_env("ENABLE_MULTIMODAL", True)
    MULTIMODAL_MAX_FILE_BYTES: int = get_int_env("MULTIMODAL_MAX_FILE_BYTES", 52428800)
    VOICE_STT_PROVIDER: str = os.getenv("VOICE_STT_PROVIDER", "whisper")
    VOICE_TTS_PROVIDER: str = os.getenv("VOICE_TTS_PROVIDER", "auto")
    VOICE_TTS_VOICE: str = os.getenv("VOICE_TTS_VOICE", "")
    VOICE_TTS_SEGMENT_CHARS: int = get_int_env("VOICE_TTS_SEGMENT_CHARS", 48)
    VOICE_TTS_BUFFER_CHARS: int = get_int_env("VOICE_TTS_BUFFER_CHARS", 96)
    VOICE_VAD_ENABLED: bool = get_bool_env("VOICE_VAD_ENABLED", True)
    VOICE_VAD_MIN_SPEECH_BYTES: int = get_int_env("VOICE_VAD_MIN_SPEECH_BYTES", 1024)
    VOICE_DUPLEX_ENABLED: bool = get_bool_env("VOICE_DUPLEX_ENABLED", True)
    VOICE_VAD_INTERRUPT_MIN_BYTES: int = get_int_env("VOICE_VAD_INTERRUPT_MIN_BYTES", 384)
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    VOICE_WS_MAX_BYTES: int = get_int_env("VOICE_WS_MAX_BYTES", 10485760)
    BROWSER_PROVIDER: str = os.getenv("BROWSER_PROVIDER", "auto")
    BROWSER_HEADLESS: bool = get_bool_env("BROWSER_HEADLESS", True)
    BROWSER_TIMEOUT_MS: int = get_int_env("BROWSER_TIMEOUT_MS", 15000)
    BROWSER_ALLOWED_DOMAINS: list[str] = get_list_env("BROWSER_ALLOWED_DOMAINS", [])
    ENABLE_LSP: bool = get_bool_env("ENABLE_LSP", True)
    LSP_TIMEOUT_SECONDS: int = get_int_env("LSP_TIMEOUT_SECONDS", 15)
    LSP_MAX_REFERENCES: int = get_int_env("LSP_MAX_REFERENCES", 200)
    PYTHON_LSP_SERVER: str = os.getenv("PYTHON_LSP_SERVER", "pyright-langserver")
    TYPESCRIPT_LSP_SERVER: str = os.getenv("TYPESCRIPT_LSP_SERVER", "typescript-language-server")
    ENABLE_AUTONOMOUS_CRON: bool = get_bool_env("ENABLE_AUTONOMOUS_CRON", False)
    AUTONOMOUS_CRON_INTERVAL_SECONDS: int = get_int_env("AUTONOMOUS_CRON_INTERVAL_SECONDS", 900)
    AUTONOMOUS_CRON_PROMPT: str = os.getenv(
        "AUTONOMOUS_CRON_PROMPT",
        "Sistemdeki bekleyen otonom iş fırsatlarını değerlendir ve gerekli aksiyon planını çıkar.",
    )
    ENABLE_NIGHTLY_MEMORY_PRUNING: bool = get_bool_env("ENABLE_NIGHTLY_MEMORY_PRUNING", False)
    NIGHTLY_MEMORY_INTERVAL_SECONDS: int = get_int_env("NIGHTLY_MEMORY_INTERVAL_SECONDS", 86400)
    NIGHTLY_MEMORY_IDLE_SECONDS: int = get_int_env("NIGHTLY_MEMORY_IDLE_SECONDS", 1800)
    NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS: int = get_int_env("NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS", 2)
    NIGHTLY_MEMORY_SESSION_MIN_MESSAGES: int = get_int_env(
        "NIGHTLY_MEMORY_SESSION_MIN_MESSAGES", 12
    )
    NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS: int = get_int_env("NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS", 2)
    ENABLE_EVENT_WEBHOOKS: bool = get_bool_env("ENABLE_EVENT_WEBHOOKS", True)
    AUTONOMY_SERVICE_USER_ID: str = os.getenv(
        "AUTONOMY_SERVICE_USER_ID", os.getenv("SYSTEM_USER_ID", "system:autonomy")
    )
    AUTONOMY_WEBHOOK_SECRET: str = os.getenv(
        "AUTONOMY_WEBHOOK_SECRET", os.getenv("SIDAR_AUTONOMY_WEBHOOK_SECRET", "")
    )
    AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE: bool = get_bool_env(
        "AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE",
        get_bool_env("SIDAR_AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE", True),
    )
    ENABLE_SWARM_FEDERATION: bool = get_bool_env("ENABLE_SWARM_FEDERATION", True)
    SWARM_FEDERATION_SHARED_SECRET: str = os.getenv("SWARM_FEDERATION_SHARED_SECRET", "")
    ENABLE_GRAPH_RAG: bool = get_bool_env("ENABLE_GRAPH_RAG", True)
    GRAPH_RAG_MAX_FILES: int = get_int_env("GRAPH_RAG_MAX_FILES", 5000)
    ENABLE_RAG_ENTITY_EXTRACTION: bool = get_bool_env("ENABLE_RAG_ENTITY_EXTRACTION", True)
    RAG_ENTITY_MAX_PER_DOC: int = get_int_env("RAG_ENTITY_MAX_PER_DOC", 24)

    # ─── Sosyal / Meta Graph Entegrasyonları (v6.0) ─────────────
    META_GRAPH_API_TOKEN: str = os.getenv("META_GRAPH_API_TOKEN", "")
    META_GRAPH_API_VERSION: str = os.getenv("META_GRAPH_API_VERSION", "v20.0")
    INSTAGRAM_BUSINESS_ACCOUNT_ID: str = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    FACEBOOK_PAGE_ID: str = os.getenv("FACEBOOK_PAGE_ID", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

    # ─── Slack Entegrasyonu (v6.0) ──────────────────────────────
    SLACK_TOKEN: str = os.getenv("SLACK_TOKEN", "")
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
    SLACK_DEFAULT_CHANNEL: str = os.getenv("SLACK_DEFAULT_CHANNEL", "")

    # ─── Jira Entegrasyonu (v6.0) ───────────────────────────────
    JIRA_URL: str = os.getenv("JIRA_URL", "")
    JIRA_TOKEN: str = os.getenv("JIRA_TOKEN", "")
    JIRA_EMAIL: str = os.getenv("JIRA_EMAIL", "")
    JIRA_DEFAULT_PROJECT: str = os.getenv("JIRA_DEFAULT_PROJECT", "")
    # Geriye dönük/alternatif adlandırma uyumluluğu
    JIRA_BASE_URL: str = os.getenv("JIRA_BASE_URL", JIRA_URL)
    JIRA_API_TOKEN: str = os.getenv("JIRA_API_TOKEN", JIRA_TOKEN)

    # ─── Microsoft Teams Entegrasyonu (v6.0) ────────────────────
    TEAMS_WEBHOOK_URL: str = os.getenv("TEAMS_WEBHOOK_URL", "")

    # ─────────────────────────────────────────────────────────
    #  METOTLAR
    # ─────────────────────────────────────────────────────────

    @classmethod
    def get_missing_critical_runtime_keys(cls) -> list[str]:
        """Return critical keys that remain unresolved after the dotenv load chain."""
        missing: list[str] = []
        if not str(cls.JWT_SECRET_KEY or "").strip() and not cls._is_test_env():
            missing.append("JWT_SECRET_KEY")

        provider = normalize_ai_provider(cls.AI_PROVIDER)
        for setting_name in _PROVIDER_REQUIRED_SETTINGS.get(provider, ()):
            raw_value = getattr(cls, setting_name, "")
            if setting_name.endswith("_GATEWAY_URL"):
                if not is_valid_http_url(raw_value):
                    missing.append(setting_name)
            elif not is_nonempty_secret(raw_value):
                missing.append(setting_name)

        if (
            os.getenv("SIDAR_ENV", "").strip().lower() == "production"
            and not str(cls.MEMORY_ENCRYPTION_KEY or "").strip()
        ):
            missing.append("MEMORY_ENCRYPTION_KEY")

        return missing

    @classmethod
    def _log_dotenv_load_status(cls, *, missing_keys: list[str] | None = None) -> None:
        """Log the effective dotenv load chain and actionable missing-key guidance."""
        global _FIRST_CONFIG_LOAD_LOGGED, _LAST_DOTENV_LOAD_CHAIN_SIGNATURE
        loaded = [event for event in _DOTENV_LOAD_EVENTS if event.get("loaded")]
        missing_files = [
            event
            for event in _DOTENV_LOAD_EVENTS
            if not event.get("loaded") and event.get("reason") == "missing"
        ]
        if loaded:
            chain_text = " -> ".join(f"{event['label']}={event['path']}" for event in loaded)
            chain_signature = tuple(
                (str(event.get("label", "")), str(event.get("path", ""))) for event in loaded
            )
            chain_changed = chain_signature != _LAST_DOTENV_LOAD_CHAIN_SIGNATURE
            _LAST_DOTENV_LOAD_CHAIN_SIGNATURE = chain_signature
            if chain_changed:
                _log_first_load_info("Runtime env yükleme zinciri: %s", chain_text)
            else:
                logger.debug(
                    "Runtime env yükleme zinciri: %s",
                    chain_text,
                )
        else:
            logger.warning(
                "Hiçbir dotenv dosyası yüklenmedi; varsayılanlar ve proses ortam değişkenleri kullanılacak."
            )

        missing_notice_items = [
            f"{event['label']}={event['path']}" for event in missing_files if event.get("path")
        ]
        if _DOTENV_MISSING_FILE_NOTICES:
            for notice in _DOTENV_MISSING_FILE_NOTICES:
                if notice not in missing_notice_items:
                    missing_notice_items.append(notice)
            _DOTENV_MISSING_FILE_NOTICES.clear()
        if missing_notice_items:
            logger.info(
                "Opsiyonel dotenv dosyaları bulunamadı: %s",
                ", ".join(missing_notice_items),
            )

        if _DOTENV_KEY_SOURCES:
            logger.debug(
                "Runtime env anahtar kaynakları: %s",
                ", ".join(
                    f"{key}->{source['label']}={source['path']}"
                    for key, source in sorted(_DOTENV_KEY_SOURCES.items())
                ),
            )

        if missing_keys:
            logger.warning(
                "Kritik ortam anahtarları çözülemedi: %s. Yükleme zinciri: .env, .env.advanced, .env.${SIDAR_ENV}, DOTENV_FILE, SIDAR_KEYS_FILE. Proses ortam değişkenleri korunur; SIDAR_KEYS_FILE en son yüklenir. "
                "Eksik değerleri .env, DOTENV_FILE veya SIDAR_KEYS_FILE (varsayılan ~/.sidar_keys.env) içine ekleyin.",
                ", ".join(missing_keys),
            )
        _FIRST_CONFIG_LOAD_LOGGED = True

    def __init__(self) -> None:
        # Donanım bilgisini import anında değil, ilk Config kullanımında yükle.
        self.__class__._ensure_hardware_info_loaded()
        self.__class__._apply_gpu_memory_safety_check()
        missing_keys = self.__class__.get_missing_critical_runtime_keys()
        if "JWT_SECRET_KEY" in missing_keys:
            self.__class__._log_dotenv_load_status(missing_keys=missing_keys)
            raise ValueError(
                "JWT_SECRET_KEY boş bırakılamaz. .env/DOTENV_FILE/SIDAR_KEYS_FILE yükleme sırasını kontrol edin."
            )

    @classmethod
    def _ensure_hardware_info_loaded(cls) -> None:
        """Donanım bilgisini lazy-load ederek import yan etkisini azalt."""
        if cls._hardware_loaded:
            return

        if not cls.USE_GPU:
            cls.GPU_INFO = "Devre Dışı / CPU Modu"
            cls.GPU_COUNT = 0
            cls.CUDA_VERSION = "N/A"
            cls.DRIVER_VERSION = "N/A"
            cls.GPU_VRAM_MB = 0
            cls.CPU_COUNT = os.cpu_count() or 1
            cls._hardware_loaded = True
            return

        hw = check_hardware()
        cls.USE_GPU = bool(hw.has_cuda)
        cls.GPU_INFO = hw.gpu_name
        cls.GPU_COUNT = hw.gpu_count
        cls.CPU_COUNT = hw.cpu_count or (os.cpu_count() or 1)
        cls.CUDA_VERSION = hw.cuda_version
        cls.DRIVER_VERSION = hw.driver_version
        cls.GPU_VRAM_MB = int(getattr(hw, "gpu_vram_mb", 0) or 0)
        cls.OLLAMA_GPU_REQUEST_POOL_SIZE = resolve_adaptive_gpu_pool_size(
            hw,
            get_int_env=get_int_env,
            logger=logger,
        )
        cls._autoselect_ollama_coding_ctx_window()
        cls._hardware_loaded = True

    @classmethod
    def _autoselect_ollama_coding_ctx_window(cls) -> None:
        """Auto-tune Ollama coding context for GPU VRAM unless explicitly overridden."""
        if os.getenv("OLLAMA_CODING_NUM_CTX") is not None:
            return
        if not cls.USE_GPU:
            return
        vram_mb = 0
        try:
            import torch

            if torch.cuda.is_available() and torch.cuda.device_count() > 0:
                props = torch.cuda.get_device_properties(0)
                vram_mb = int(getattr(props, "total_memory", 0) / (1024 * 1024))
        except Exception:
            vram_mb = 0

        if vram_mb > 0:
            cls.GPU_VRAM_MB = max(0, int(vram_mb))
        if cls.GPU_VRAM_MB >= 16384:
            cls.OLLAMA_CODING_NUM_CTX = 16384
        elif cls.GPU_VRAM_MB >= 8192:
            cls.OLLAMA_CODING_NUM_CTX = 8192

    @classmethod
    def trusted_proxies_as_list(cls) -> list[str]:
        """Middleware entegrasyonları için güvenilir proxy değerlerini list[str] verir."""
        return list(cls.TRUSTED_PROXIES_LIST)

    @classmethod
    def _is_test_env(cls) -> bool:
        sidar_env = os.getenv("SIDAR_ENV", "").strip().lower()
        if sidar_env in {"test", "testing"}:
            return True
        return bool(os.getenv("PYTEST_CURRENT_TEST"))

    @classmethod
    def _apply_gpu_memory_safety_check(cls) -> None:
        """LLM+RAG VRAM fraksiyonu 1.0'ı aşarsa toplamı güvenli 0.8'e normalize eder."""
        llm = float(cls.LLM_GPU_MEMORY_FRACTION or 0.0)
        rag = float(cls.RAG_GPU_MEMORY_FRACTION or 0.0)
        total = llm + rag

        budget = normalize_gpu_memory_fractions(llm, rag)
        if total <= 0:
            cls.LLM_GPU_MEMORY_FRACTION = float(budget["llm"])
            cls.RAG_GPU_MEMORY_FRACTION = float(budget["rag"])
            cls.GPU_MEMORY_FRACTION = float(budget["gpu"])
            return

        if not budget["normalized"]:
            return

        cls.LLM_GPU_MEMORY_FRACTION = float(budget["llm"])
        cls.RAG_GPU_MEMORY_FRACTION = float(budget["rag"])
        cls.GPU_MEMORY_FRACTION = float(budget["gpu"])
        logger.warning(
            "LLM/RAG GPU bellek fraksiyonları toplamı %.2f bulundu; OOM riskini azaltmak için %.2f toplamına normalize edildi "
            "(LLM=%.2f, RAG=%.2f).",
            budget["original_total"],
            budget["gpu"],
            cls.LLM_GPU_MEMORY_FRACTION,
            cls.RAG_GPU_MEMORY_FRACTION,
        )

    @classmethod
    def initialize_directories(cls) -> bool:
        """Gerekli tüm dizinleri oluşturur."""
        return initialize_required_directories(cls.REQUIRED_DIRS, logger)

    @classmethod
    def set_provider_mode(cls, mode: str) -> None:
        """AI sağlayıcı modunu çalışma zamanında değiştirir."""
        mode_map = {
            "online": "gemini",
            "gemini": "gemini",
            "local": "ollama",
            "ollama": "ollama",
            "anthropic": "anthropic",
            "litellm": "litellm",
        }
        m_lower = normalize_ai_provider(mode)
        if m_lower in mode_map:
            cls.AI_PROVIDER = mode_map[m_lower]
            logger.info("✅ AI Sağlayıcı güncellendi: %s", cls.AI_PROVIDER.upper())
        else:
            logger.error(
                "❌ Geçersiz sağlayıcı modu: %s  Geçerliler: %s",
                mode,
                list(mode_map.keys()),
            )

    @classmethod
    def _validate_ai_provider_settings(cls) -> bool:
        """Validate centralized provider and credential settings from config.py."""
        provider = normalize_ai_provider(cls.AI_PROVIDER)
        cls.AI_PROVIDER = provider

        if provider not in SUPPORTED_AI_PROVIDERS:
            logger.error(
                "❌ Geçersiz AI_PROVIDER=%s. Geçerli sağlayıcılar: %s",
                provider,
                ", ".join(sorted(SUPPORTED_AI_PROVIDERS)),
            )
            return False

        is_valid = True
        for setting_name in _PROVIDER_REQUIRED_SETTINGS.get(provider, ()):  # ollama has no API key
            raw_value = getattr(cls, setting_name, "")
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

    @classmethod
    def validate_critical_settings(cls) -> bool:
        """Kritik yapılandırmaları doğrular; uyarıları loglar."""
        is_valid = True
        cls._ensure_hardware_info_loaded()
        cls._apply_gpu_memory_safety_check()
        cls.initialize_directories()
        cls._log_dotenv_load_status(missing_keys=cls.get_missing_critical_runtime_keys())

        if cls.REQUIRE_GPU and not cls.USE_GPU:
            logger.error(
                "❌ GPU zorunlu mod aktif (REQUIRE_GPU=true) ancak CUDA/PyTorch uygun değil veya USE_GPU=false.\n"
                "   Çözüm: CUDA destekli PyTorch kurun ve .env içinde USE_GPU=true yapın."
            )
            is_valid = False

        allow_full_access = os.getenv("SIDAR_ALLOW_FULL_ACCESS", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if cls.ACCESS_LEVEL.strip().lower() == "full" and not allow_full_access:
            logger.error(
                "❌ ACCESS_LEVEL=full açık onay olmadan yasaktır. "
                "Riskleri kabul ediyorsanız SIDAR_ALLOW_FULL_ACCESS=true ayarlayın."
            )
            is_valid = False

        is_valid = cls._validate_ai_provider_settings() and is_valid

        memory_encryption_key = (cls.MEMORY_ENCRYPTION_KEY or "").strip()

        if memory_encryption_key:
            try:
                from cryptography.fernet import Fernet  # noqa: F401

                # Anahtarı ön doğrulama — geçersiz formatta erken hata ver
                try:
                    Fernet(memory_encryption_key.encode())
                except Exception as key_exc:
                    logger.error(
                        "❌ MEMORY_ENCRYPTION_KEY geçersiz Fernet anahtarı: %s\n"
                        "   Geçerli anahtar üretmek için:\n"
                        '   python -c "from cryptography.fernet import Fernet; '
                        'print(Fernet.generate_key().decode())"',
                        key_exc,
                    )
                    is_valid = False
            except ImportError:
                logger.error(
                    "❌ MEMORY_ENCRYPTION_KEY ayarlanmış ama 'cryptography' paketi kurulu değil.\n"
                    "   Bu kritik bir güvenlik ayarıdır. Şifreleme olmadan devam etmek\n"
                    "   güvenlik riskine yol açabilir. Kurmak için: uv pip install cryptography"
                )
                is_valid = False
        else:
            logger.critical(
                "MEMORY_ENCRYPTION_KEY is not set. Please generate a valid Fernet key for memory encryption. "
                "Konuşma geçmişi şifrelenmeden saklanıyor. Üretim ortamında .env dosyasına güçlü bir Fernet "
                "anahtarı eklemelisiniz.\n"
                '   Yeni anahtar üretmek için: python -c "from cryptography.fernet import '
                'Fernet; print(Fernet.generate_key().decode())"'
            )
            if os.getenv("SIDAR_ENV", "").strip().lower() == "production":
                logger.critical(
                    "SIDAR_ENV=production iken MEMORY_ENCRYPTION_KEY zorunludur. Güvenlik nedeniyle uygulama durduruluyor."
                )
                raise SystemExit(1)

        if cls.AI_PROVIDER == "ollama":
            try:
                import httpx

                base = cls.OLLAMA_URL.rstrip("/")
                if base.endswith("/api"):
                    tags_url = base + "/tags"
                else:
                    tags_url = base + "/api/tags"
                with httpx.Client(timeout=2) as client:
                    r = client.get(tags_url)
                if r.status_code == 200:
                    _log_once_env(
                        "SIDAR_OLLAMA_OK_LOGGED", logger.info, "✅ Ollama bağlantısı başarılı."
                    )
                else:
                    logger.warning("⚠️  Ollama yanıt kodu: %d", r.status_code)
            except Exception:
                logger.warning(
                    "⚠️  Ollama'ya ulaşılamadı (%s)\n"
                    "    'ollama serve' çalıştırıldığından emin olun.",
                    cls.OLLAMA_URL,
                )

        return is_valid

    @classmethod
    def get_system_info(cls) -> dict[str, Any]:
        """Özet sistem bilgisini sözlük olarak döndürür."""
        cls._ensure_hardware_info_loaded()
        return {
            "project": cls.PROJECT_NAME,
            "version": cls.VERSION,
            "provider": cls.AI_PROVIDER,
            "access_level": cls.ACCESS_LEVEL,
            "gpu_enabled": cls.USE_GPU,
            "gpu_info": cls.GPU_INFO,
            "gpu_count": cls.GPU_COUNT,
            "gpu_device": cls.GPU_DEVICE,
            "cuda_version": cls.CUDA_VERSION,
            "driver_version": cls.DRIVER_VERSION,
            "multi_gpu": cls.MULTI_GPU,
            "gpu_mixed_precision": cls.GPU_MIXED_PRECISION,
            "gpu_memory_fraction": cls.GPU_MEMORY_FRACTION,
            "llm_gpu_memory_fraction": cls.LLM_GPU_MEMORY_FRACTION,
            "rag_gpu_memory_fraction": cls.RAG_GPU_MEMORY_FRACTION,
            "cpu_count": cls.CPU_COUNT,
            "debug_mode": cls.DEBUG_MODE,
            "web_port": cls.WEB_PORT,
            "web_gpu_port": cls.WEB_GPU_PORT,
            "hf_hub_offline": cls.HF_HUB_OFFLINE,
            "hf_use_local_cache_only": cls.HF_USE_LOCAL_CACHE_ONLY,
            "rate_limit_window": cls.RATE_LIMIT_WINDOW,
            "rate_limit_chat": cls.RATE_LIMIT_CHAT,
            "rate_limit_mutations": cls.RATE_LIMIT_MUTATIONS,
            "rate_limit_get_io": cls.RATE_LIMIT_GET_IO,
            # REDIS_URL burada yer almaz — host/port/kimlik bilgisi ifşasını önlemek için
            "enable_tracing": cls.ENABLE_TRACING,
            "otel_exporter_endpoint": cls.OTEL_EXPORTER_ENDPOINT,
            "enable_semantic_cache": cls.ENABLE_SEMANTIC_CACHE,
            "semantic_cache_threshold": cls.SEMANTIC_CACHE_THRESHOLD,
            "semantic_cache_ttl": cls.SEMANTIC_CACHE_TTL,
            "semantic_cache_max_items": cls.SEMANTIC_CACHE_MAX_ITEMS,
        }

    @classmethod
    def init_telemetry(
        cls,
        *,
        service_name: str | None = None,
        fastapi_app: Any | None = None,
        logger_obj: logging.Logger | None = None,
        trace_module: Any = _DEPENDENCY_AUTO,
        otlp_exporter_cls: Any = _DEPENDENCY_AUTO,
        tracer_provider_cls: Any = _DEPENDENCY_AUTO,
        resource_cls: Any = _DEPENDENCY_AUTO,
        batch_span_processor_cls: Any = _DEPENDENCY_AUTO,
        fastapi_instrumentor_cls: Any = _DEPENDENCY_AUTO,
        httpx_instrumentor_cls: Any = _DEPENDENCY_AUTO,
    ) -> bool:
        """OpenTelemetry tracing + opsiyonel FastAPI/HTTPX enstrümantasyonunu başlat."""
        log = logger_obj or logger
        if not cls.ENABLE_TRACING:
            return False

        if (
            trace_module is None
            or otlp_exporter_cls is None
            or tracer_provider_cls is None
            or resource_cls is None
            or batch_span_processor_cls is None
        ):
            log.warning("ENABLE_TRACING açık fakat OpenTelemetry bağımlılıkları yüklenemedi.")
            return False

        try:
            if trace_module is _DEPENDENCY_AUTO:
                from opentelemetry import trace as imported_trace_module

                trace_module = imported_trace_module
            if otlp_exporter_cls is _DEPENDENCY_AUTO:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter as imported_otlp_exporter_cls,
                )

                otlp_exporter_cls = imported_otlp_exporter_cls
            if tracer_provider_cls is _DEPENDENCY_AUTO:
                from opentelemetry.sdk.trace import TracerProvider as imported_tracer_provider_cls

                tracer_provider_cls = imported_tracer_provider_cls
            if resource_cls is _DEPENDENCY_AUTO:
                from opentelemetry.sdk.resources import Resource as imported_resource_cls

                resource_cls = imported_resource_cls
            if batch_span_processor_cls is _DEPENDENCY_AUTO:
                from opentelemetry.sdk.trace.export import (
                    BatchSpanProcessor as imported_batch_span_processor_cls,
                )

                batch_span_processor_cls = imported_batch_span_processor_cls
        except Exception:
            log.warning("ENABLE_TRACING açık fakat OpenTelemetry bağımlılıkları yüklenemedi.")
            return False

        try:
            svc_name = service_name or cls.OTEL_SERVICE_NAME or "sidar"
            resource = resource_cls.create({"service.name": svc_name})
            provider = tracer_provider_cls(resource=resource)
            exporter = otlp_exporter_cls(endpoint=cls.OTEL_EXPORTER_ENDPOINT, insecure=True)
            provider.add_span_processor(batch_span_processor_cls(exporter))
            trace_module.set_tracer_provider(provider)

            if fastapi_app is not None and cls.OTEL_INSTRUMENT_FASTAPI:
                if fastapi_instrumentor_cls is _DEPENDENCY_AUTO:
                    from opentelemetry.instrumentation.fastapi import (
                        FastAPIInstrumentor as imported_fastapi_instrumentor_cls,
                    )

                    fastapi_instrumentor_cls = imported_fastapi_instrumentor_cls
                fastapi_instrumentor_cls.instrument_app(fastapi_app)

            if cls.OTEL_INSTRUMENT_HTTPX:
                if httpx_instrumentor_cls is _DEPENDENCY_AUTO:
                    try:
                        from opentelemetry.instrumentation.httpx import (
                            HTTPXClientInstrumentor as imported_httpx_instrumentor_cls,
                        )

                        httpx_instrumentor_cls = imported_httpx_instrumentor_cls
                    except Exception:
                        httpx_instrumentor_cls = None
                if httpx_instrumentor_cls is not None:
                    with contextlib.suppress(Exception):
                        httpx_instrumentor_cls().instrument()

            log.info("✅ OpenTelemetry aktif: %s", cls.OTEL_EXPORTER_ENDPOINT)
            return True
        except Exception as exc:
            log.warning("OpenTelemetry başlatılamadı: %s", exc)
            return False

    @classmethod
    def print_config_summary(cls) -> None:
        """Konsola yapılandırma özetini yazdırır."""
        print("\n" + "═" * 62)
        print(f"  {cls.PROJECT_NAME} v{cls.VERSION} — Yapılandırma Özeti")
        print("═" * 62)
        print(f"  AI Sağlayıcı     : {cls.AI_PROVIDER.upper()}")
        if cls.USE_GPU:
            print(f"  GPU              : ✓ {cls.GPU_INFO}  (CUDA {cls.CUDA_VERSION})")
            print(f"  GPU Sayısı       : {cls.GPU_COUNT}")
            print(f"  Hedef Cihaz      : cuda:{cls.GPU_DEVICE}")
            print(f"  Mixed Precision  : {'Açık' if cls.GPU_MIXED_PRECISION else 'Kapalı'}")
            print(f"  LLM VRAM Payı    : {cls.LLM_GPU_MEMORY_FRACTION:.2f}")
            print(f"  RAG VRAM Payı    : {cls.RAG_GPU_MEMORY_FRACTION:.2f}")
            if cls.DRIVER_VERSION != "N/A":
                print(f"  Sürücü Sürümü    : {cls.DRIVER_VERSION}")
        else:
            print(f"  GPU              : ✗ CPU Modu  ({cls.GPU_INFO})")
        print(f"  CPU Çekirdek     : {cls.CPU_COUNT}")
        print(f"  Erişim Seviyesi  : {cls.ACCESS_LEVEL.upper()}")
        print(f"  Debug Modu       : {'Açık' if cls.DEBUG_MODE else 'Kapalı'}")
        if cls.AI_PROVIDER == "ollama":
            print(f"  CODING Modeli    : {cls.CODING_MODEL}")
            print(f"  TEXT Modeli      : {cls.TEXT_MODEL}")
        elif cls.AI_PROVIDER == "gemini":
            print(f"  Gemini Modeli    : {cls.GEMINI_MODEL}")
        elif cls.AI_PROVIDER == "openai":
            print(f"  OpenAI Modeli    : {cls.OPENAI_MODEL}")
        elif cls.AI_PROVIDER == "litellm":
            print(f"  LiteLLM Gateway  : {cls.LITELLM_GATEWAY_URL or '-'}")
            print(f"  LiteLLM Modeli   : {cls.LITELLM_MODEL or cls.OPENAI_MODEL}")
        else:
            print(f"  Anthropic Modeli : {cls.ANTHROPIC_MODEL}")
        print(f"  RAG Dizini       : {cls.RAG_DIR.relative_to(BASE_DIR)}")
        enc_status = "Etkin (Fernet)" if cls.MEMORY_ENCRYPTION_KEY else "Devre Dışı"
        print(f"  Bellek Şifreleme : {enc_status}")
        print("═" * 62 + "\n")


def _reload_dotenv_chain(*, profile: str | None = None) -> None:
    """Reload the dotenv precedence chain without re-importing the module."""
    global _LAST_DOTENV_LOAD_CHAIN_SIGNATURE
    previous_managed_keys = set(_DOTENV_MANAGED_KEYS)
    effective_env = _dotenv_reload_baseline_environment()
    _DOTENV_MANAGED_KEYS.clear()
    _DOTENV_LOAD_EVENTS.clear()
    _DOTENV_KEY_SOURCES.clear()

    base_path = BASE_DIR / ".env"
    advanced_path = BASE_DIR / ".env.advanced"
    if not _skip_default_dotenv_layers(effective_env):
        _load_dotenv_into_effective_env(effective_env, str(base_path), override=False, label="base")
        _load_dotenv_into_effective_env(
            effective_env, str(advanced_path), override=False, label="advanced"
        )

        selected_env = (profile or effective_env.get("SIDAR_ENV", "")).strip().lower()
        if selected_env:
            effective_env["SIDAR_ENV"] = selected_env
            _load_dotenv_into_effective_env(
                effective_env,
                str(BASE_DIR / f".env.{selected_env}"),
                override=True,
                label=f"environment:{selected_env}",
            )

    explicit_dotenv = effective_env.get("DOTENV_FILE", "").strip()
    _load_dotenv_into_effective_env(
        effective_env, explicit_dotenv, override=True, label="explicit:DOTENV_FILE"
    )
    sidar_keys_file = effective_env.get("SIDAR_KEYS_FILE", "~/.sidar_keys.env").strip()
    _load_dotenv_into_effective_env(
        effective_env, sidar_keys_file, override=True, label="secret:SIDAR_KEYS_FILE"
    )

    removed_managed_keys = previous_managed_keys - set(effective_env)
    for key in removed_managed_keys:
        os.environ.pop(key, None)
    os.environ.update(effective_env)


ConfigReloadCallback = Callable[["Config"], None]


def _restore_reload_registry_from_previous_module() -> (
    tuple[list["ConfigReloadCallback"], "Config | None"]
):
    """`importlib.reload(config)` çağrısı sonrası callback registry'sini koru.

    Modül yeniden çalıştırıldığında modül globalleri sıfırlanır; bu durum
    ``register_config_reload_callback`` ile bağlanmış abonelerin (örn.
    ``web_server._on_config_reload``) sessizce düşmesine yol açar. Python ilk
    importtan itibaren modülü ``sys.modules`` içine yerleştirdiği için reload
    sırasında önceki ``_config_reload_callbacks`` listesini ve son notify edilen
    Config kimliğini buradan okuyup yeni binding'lere taşıyarak registry'nin
    reload boundary'sinde dirençli kalmasını sağlarız.
    """
    existing_module = sys.modules[__name__]
    previous_callbacks = getattr(existing_module, "_config_reload_callbacks", None)
    callbacks: list[ConfigReloadCallback] = (
        list(previous_callbacks) if isinstance(previous_callbacks, list) else []
    )
    previous_instance = getattr(existing_module, "_last_notified_instance", None)
    return callbacks, previous_instance


_config_reload_callbacks, _last_notified_instance = _restore_reload_registry_from_previous_module()


def register_config_reload_callback(callback: ConfigReloadCallback) -> None:
    """Register a process-local hook that synchronizes cached Config references after reload."""
    if callback not in _config_reload_callbacks:
        _config_reload_callbacks.append(callback)


def _notify_config_reload_callbacks(config_instance: "Config") -> None:
    """Notify reload subscribers exactly once per active Config identity.

    Idempotent on instance identity so callers (`get_config`, `reload_environment`)
    can invoke it eagerly without double-firing subscribers when nothing changed.
    """
    global _last_notified_instance
    if _last_notified_instance is config_instance:
        return
    _last_notified_instance = config_instance
    for callback in list(_config_reload_callbacks):
        try:
            callback(config_instance)
        except Exception as exc:  # pragma: no cover - defensive isolation for app hooks
            logger.warning("Config reload callback failed: %s", exc)


def reload_environment(*, profile: str | None = None) -> "Config":
    """Reload dotenv files after an environment file is created and refresh Config defaults."""
    global _config_instance
    _reload_dotenv_chain(profile=profile)

    apply_runtime_env_overrides(
        Config,
        base_dir=BASE_DIR,
        get_int_env=get_int_env,
        get_database_url=get_database_url,
        get_container_database_url=get_container_database_url,
        normalize_ai_provider=normalize_ai_provider,
    )
    Config._hardware_loaded = False
    _config_instance = None
    Config._log_dotenv_load_status(missing_keys=Config.get_missing_critical_runtime_keys())
    reloaded = get_config()
    return reloaded


def _safe_choice_for_reload(value: object, default: str, allowed: set[str]) -> str:
    return safe_choice_for_reload(value, default, allowed)


# ═══════════════════════════════════════════════════════════════
# SINGLETON — Bulgu D: Config() tekrar çağrısı kaynak israfı
# ═══════════════════════════════════════════════════════════════
_config_instance: "Config | None" = None


def get_config() -> "Config":
    """Proses genelinde tek Config örneği döndürür (thread-safe, lazy).

    Her çağrıda mevcut singleton üzerinden idempotent notify çalıştırır; böylece
    monkeypatch yoluyla `_config_instance` dışarıdan değiştirilmiş olsa bile
    `web_server.cfg` gibi cached referanslar bir sonraki `get_config()` çağrısında
    otomatik olarak canlı singleton'a hizalanır.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    _notify_config_reload_callbacks(_config_instance)
    return _config_instance


# ═══════════════════════════════════════════════════════════════
# BAŞLANGIÇ
# ═══════════════════════════════════════════════════════════════
_config_banner_log = logger.debug if get_bool_env("SIDAR_CONFIG_QUIET", False) else logger.info
_log_once_env(
    "SIDAR_CONFIG_BANNER_LOGGED",
    _config_banner_log,
    "✅ %s v%s yapılandırması yüklendi.",
    Config.PROJECT_NAME,
    Config.VERSION,
    fingerprint=f"{Config.PROJECT_NAME}:{Config.VERSION}:{ENV_PATH.resolve()}",
)

if __name__ == "__main__":
    Config.initialize_directories()
    if Config.DEBUG_MODE:
        Config.print_config_summary()
