"""Secret hardening checks kept outside the Config facade."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from config_security import get_missing_security_runtime_keys, has_weak_postgres_runtime_secret
from core.config_secrets import is_nonempty_secret, is_weak_secret
from core.config_validators import is_valid_http_url, normalize_ai_provider

PRODUCTION_SECRET_KEYS: tuple[str, ...] = (
    "API_KEY",
    "JWT_SECRET_KEY",
    "MEMORY_ENCRYPTION_KEY",
    "AUTONOMY_WEBHOOK_SECRET",
    "SWARM_FEDERATION_SHARED_SECRET",
    "GITHUB_WEBHOOK_SECRET",
    "GRAFANA_ADMIN_PASSWORD",
    "METRICS_TOKEN",
)


def _read_dotenv_secret_values(path: Path) -> dict[str, str]:
    """Read only production-secret keys from a dotenv file without mutating the environment."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in PRODUCTION_SECRET_KEYS:
            values[normalized_key] = value.strip().strip('"').strip("'")
    return values


def collect_unsafe_production_secret_keys(config_cls: Any) -> list[str]:
    """Return missing, weak, known-shared, or non-production-shared production secrets."""
    effective = {
        key: str(getattr(config_cls, key, os.getenv(key, "")) or "").strip()
        for key in PRODUCTION_SECRET_KEYS
    }
    base_dir = Path(getattr(config_cls, "BASE_DIR", Path.cwd()))
    known_weak = _read_dotenv_secret_values(base_dir / "scripts" / "known_weak_secrets.txt")
    reference_values = [
        _read_dotenv_secret_values(base_dir / filename)
        for filename in (".env", ".env.development", ".env.test", ".env.advanced")
    ]
    return [
        key
        for key, value in effective.items()
        if is_weak_secret(value)
        or (value and known_weak.get(key) == value)
        or (value and any(reference.get(key) == value for reference in reference_values))
    ]


def collect_missing_critical_runtime_keys(
    config_cls: Any,
    *,
    provider_required_settings: Mapping[str, Iterable[str]],
    get_int_env: Callable[[str, int], int],
) -> list[str]:
    """Return unresolved security/provider keys after dotenv and process env resolution."""
    missing: list[str] = []
    is_production = os.getenv("SIDAR_ENV", "").strip().lower() == "production"
    missing.extend(
        get_missing_security_runtime_keys(
            api_key=config_cls.API_KEY,
            jwt_secret_key=config_cls.JWT_SECRET_KEY,
            jwt_secret_key_explicitly_configured=config_cls._JWT_SECRET_KEY_EXPLICITLY_CONFIGURED,
            is_production=is_production,
            is_test_env=config_cls._is_test_env(),
            web_concurrency=get_int_env("WEB_CONCURRENCY", 1),
            postgres_password=os.getenv("POSTGRES_PASSWORD", ""),
            database_url=config_cls.DATABASE_URL,
        )
    )

    provider = normalize_ai_provider(config_cls.AI_PROVIDER)
    for setting_name in provider_required_settings.get(provider, ()):
        raw_value = getattr(config_cls, setting_name, "")
        if setting_name.endswith("_GATEWAY_URL"):
            if not is_valid_http_url(raw_value):
                missing.append(setting_name)
        elif not is_nonempty_secret(raw_value):
            missing.append(setting_name)

    if is_production and not str(config_cls.MEMORY_ENCRYPTION_KEY or "").strip():
        missing.append("MEMORY_ENCRYPTION_KEY")

    if is_production:
        missing.extend(collect_unsafe_production_secret_keys(config_cls))

    return list(dict.fromkeys(missing))


def warn_on_silent_security_fallbacks(config_cls: Any, *, logger: logging.Logger) -> None:
    """Log non-production security fallbacks that would otherwise be silent."""
    if config_cls._is_test_env():
        return
    if not config_cls._JWT_SECRET_KEY_EXPLICITLY_CONFIGURED:
        logger.warning(
            "JWT_SECRET_KEY tanımlanmamış; bu process için rastgele ve kalıcı olmayan bir "
            "secret üretildi. Process yeniden başladığında mevcut tüm JWT token'lar sessizce "
            "geçersiz olacaktır. Kalıcı oturumlar için .env/DOTENV_FILE/SIDAR_KEYS_FILE içine "
            "sabit bir JWT_SECRET_KEY tanımlayın."
        )

    is_production = os.getenv("SIDAR_ENV", "").strip().lower() == "production"
    if not is_production and has_weak_postgres_runtime_secret(
        postgres_password=os.getenv("POSTGRES_PASSWORD", ""),
        database_url=config_cls.DATABASE_URL,
    ):
        logger.warning(
            'POSTGRES_PASSWORD zayıf/varsayılan bir değerde (ör. "sidar"); bu yalnızca '
            "production'da engellenir. Staging/test ortamlarında da güçlü bir parola "
            "tanımlamanız önerilir."
        )
