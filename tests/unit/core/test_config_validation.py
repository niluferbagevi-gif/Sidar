"""Unit tests for core.config_validation (Config.validate_critical_settings backend)."""

from __future__ import annotations

import logging
import sys
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

from core import config_postgres, config_validation

_VALID_FERNET_KEY = Fernet.generate_key().decode()


class _FakeConfig:
    """Minimal Config stand-in that records the facade hooks validation calls."""

    AI_PROVIDER = "openai"
    OPENAI_API_KEY = "sk-valid"
    LITELLM_GATEWAY_URL = ""
    REQUIRE_GPU = False
    USE_GPU = False
    ACCESS_LEVEL = "sandbox"
    MEMORY_ENCRYPTION_KEY = _VALID_FERNET_KEY
    MEMORY_ENCRYPTION_KEY_PREVIOUS = ""
    OLLAMA_URL = "http://localhost:11434"
    missing_keys: list[str] = []
    calls: list[str] = []
    provider_result = True

    @classmethod
    def _ensure_hardware_info_loaded(cls) -> None:
        cls.calls.append("hardware")

    @classmethod
    def _apply_gpu_memory_safety_check(cls) -> None:
        cls.calls.append("gpu_budget")

    @classmethod
    def initialize_directories(cls) -> bool:
        cls.calls.append("dirs")
        return True

    @classmethod
    def get_missing_critical_runtime_keys(cls) -> list[str]:
        return list(cls.missing_keys)

    @classmethod
    def _log_dotenv_load_status(cls, *, missing_keys: list[str] | None = None) -> None:
        cls.calls.append(f"dotenv_status:{missing_keys}")

    @classmethod
    def _validate_ai_provider_settings(cls) -> bool:
        cls.calls.append("provider")
        return cls.provider_result


@pytest.fixture
def fake_config() -> type[_FakeConfig]:
    class _Cfg(_FakeConfig):
        missing_keys: list[str] = []
        calls: list[str] = []

    return _Cfg


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("SIDAR_ALLOW_FULL_ACCESS", raising=False)


@pytest.fixture(autouse=True)
def _no_postgres_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_postgres, "postgres_password_drift_messages", lambda: [])


def _validate(
    config_cls: Any,
    *,
    log_once_calls: list[tuple[Any, ...]] | None = None,
) -> bool:
    once = log_once_calls if log_once_calls is not None else []
    return config_validation.validate_critical_settings(
        config_cls,
        logger=logging.getLogger("test.config_validation"),
        log_once_env=lambda *args: once.append(args),
        localized_log_message=lambda key: f"<{key}> %s",
    )


def test_validate_ai_provider_settings_normalizes_and_accepts_known_provider() -> None:
    class Cfg:
        AI_PROVIDER = "  OpenAI "
        OPENAI_API_KEY = "sk-valid"

    ok = config_validation.validate_ai_provider_settings(
        Cfg,
        logger=logging.getLogger("test"),
        supported_providers=("openai", "ollama"),
        provider_required_settings={"openai": ("OPENAI_API_KEY",)},
    )

    assert ok is True
    assert Cfg.AI_PROVIDER == "openai"


def test_validate_ai_provider_settings_rejects_unknown_provider(caplog) -> None:
    class Cfg:
        AI_PROVIDER = "mystery"

    with caplog.at_level(logging.ERROR):
        ok = config_validation.validate_ai_provider_settings(
            Cfg,
            logger=logging.getLogger("test"),
            supported_providers=("openai", "ollama"),
            provider_required_settings={},
        )

    assert ok is False
    assert "Geçersiz AI_PROVIDER=mystery" in caplog.text
    assert "ollama, openai" in caplog.text


def test_validate_ai_provider_settings_flags_missing_key_and_bad_gateway_url(caplog) -> None:
    class Cfg:
        AI_PROVIDER = "litellm"
        LITELLM_API_KEY = ""
        LITELLM_GATEWAY_URL = "not-a-url"

    with caplog.at_level(logging.ERROR):
        ok = config_validation.validate_ai_provider_settings(
            Cfg,
            logger=logging.getLogger("test"),
            supported_providers=("litellm",),
            provider_required_settings={"litellm": ("LITELLM_GATEWAY_URL", "LITELLM_API_KEY")},
        )

    assert ok is False
    assert "LITELLM_GATEWAY_URL geçerli bir http(s) URL değil" in caplog.text
    assert "LITELLM_API_KEY ayarlanmamış veya hatalı" in caplog.text


def test_validate_critical_settings_happy_path_calls_facade_hooks_in_order(fake_config) -> None:
    fake_config.missing_keys = ["OPTIONAL_KEY"]

    assert _validate(fake_config) is True
    assert fake_config.calls == [
        "hardware",
        "gpu_budget",
        "dirs",
        "dotenv_status:['OPTIONAL_KEY']",
        "provider",
    ]


def test_production_exits_on_missing_production_secret(fake_config, monkeypatch, caplog) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")
    fake_config.missing_keys = ["JWT_SECRET_KEY", "OTHER"]

    with caplog.at_level(logging.CRITICAL), pytest.raises(SystemExit) as exc_info:
        _validate(fake_config)

    assert exc_info.value.code == 1
    assert "Production secret doğrulaması başarısız: JWT_SECRET_KEY." in caplog.text
    assert "provider" not in fake_config.calls


def test_production_without_unsafe_secrets_continues(fake_config, monkeypatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")
    fake_config.missing_keys = ["NOT_A_PRODUCTION_SECRET"]

    assert _validate(fake_config) is True
    assert "provider" in fake_config.calls


def test_require_gpu_without_gpu_is_invalid(fake_config, caplog) -> None:
    fake_config.REQUIRE_GPU = True
    fake_config.USE_GPU = False

    with caplog.at_level(logging.ERROR):
        assert _validate(fake_config) is False
    assert "REQUIRE_GPU=true" in caplog.text


@pytest.mark.parametrize(("allow", "expected"), [("", False), ("yes", True)])
def test_full_access_requires_explicit_opt_in(fake_config, monkeypatch, allow, expected) -> None:
    fake_config.ACCESS_LEVEL = " FULL "
    if allow:
        monkeypatch.setenv("SIDAR_ALLOW_FULL_ACCESS", allow)

    assert _validate(fake_config) is expected


def test_failed_provider_check_makes_result_invalid(fake_config) -> None:
    fake_config.provider_result = False

    assert _validate(fake_config) is False


def test_postgres_password_drift_messages_are_logged_and_invalid(
    fake_config, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(
        config_postgres, "postgres_password_drift_messages", lambda: ["drift-one", "drift-two"]
    )

    with caplog.at_level(logging.ERROR):
        ok = _validate(fake_config)

    assert ok is False
    assert "drift-one" in caplog.text
    assert "drift-two" in caplog.text
    assert "scripts/sync_database_passwords.py" in caplog.text


def test_invalid_current_or_previous_fernet_key_is_invalid(fake_config, caplog) -> None:
    fake_config.MEMORY_ENCRYPTION_KEY = _VALID_FERNET_KEY
    fake_config.MEMORY_ENCRYPTION_KEY_PREVIOUS = f" , {_VALID_FERNET_KEY}, not-a-key"

    with caplog.at_level(logging.ERROR):
        assert _validate(fake_config) is False
    assert "MEMORY_ENCRYPTION_KEY geçersiz Fernet anahtarı" in caplog.text


def test_valid_rotated_fernet_keys_pass(fake_config) -> None:
    fake_config.MEMORY_ENCRYPTION_KEY_PREVIOUS = Fernet.generate_key().decode()

    assert _validate(fake_config) is True


def test_encryption_key_without_cryptography_package_is_invalid(
    fake_config, monkeypatch, caplog
) -> None:
    monkeypatch.setitem(sys.modules, "cryptography.fernet", None)

    with caplog.at_level(logging.ERROR):
        assert _validate(fake_config) is False
    assert "'cryptography' paketi kurulu değil" in caplog.text


def test_missing_encryption_key_warns_outside_production(fake_config, caplog) -> None:
    fake_config.MEMORY_ENCRYPTION_KEY = "   "

    with caplog.at_level(logging.CRITICAL):
        assert _validate(fake_config) is True
    assert "MEMORY_ENCRYPTION_KEY is not set" in caplog.text


def test_missing_encryption_key_exits_in_production(fake_config, monkeypatch, caplog) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")
    fake_config.MEMORY_ENCRYPTION_KEY = None

    with caplog.at_level(logging.CRITICAL), pytest.raises(SystemExit):
        _validate(fake_config)
    assert "SIDAR_ENV=production iken MEMORY_ENCRYPTION_KEY zorunludur" in caplog.text


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _install_fake_httpx_client(
    monkeypatch: pytest.MonkeyPatch, *, status_code: int | None, requested: list[str]
) -> None:
    class _Client:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 2

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def get(self, url: str) -> _FakeResponse:
            requested.append(url)
            if status_code is None:
                raise httpx.ConnectError("refused")
            return _FakeResponse(status_code)

    monkeypatch.setattr(httpx, "Client", _Client)


@pytest.mark.parametrize(
    ("ollama_url", "expected_url"),
    [
        ("http://ollama:11434/", "http://ollama:11434/api/tags"),
        ("http://ollama:11434/api", "http://ollama:11434/api/tags"),
    ],
)
def test_ollama_probe_success_logs_once(fake_config, monkeypatch, ollama_url, expected_url) -> None:
    fake_config.AI_PROVIDER = "ollama"
    fake_config.OLLAMA_URL = ollama_url
    requested: list[str] = []
    once: list[tuple[Any, ...]] = []
    _install_fake_httpx_client(monkeypatch, status_code=200, requested=requested)

    assert _validate(fake_config, log_once_calls=once) is True
    assert requested == [expected_url]
    assert once[0][0] == "SIDAR_OLLAMA_OK_LOGGED"
    assert once[0][2] == "<ollama_ok> %s"


def test_ollama_probe_non_200_logs_status(fake_config, monkeypatch, caplog) -> None:
    fake_config.AI_PROVIDER = "ollama"
    _install_fake_httpx_client(monkeypatch, status_code=503, requested=[])

    with caplog.at_level(logging.WARNING):
        assert _validate(fake_config) is True
    assert "<ollama_status> 503" in caplog.text


def test_ollama_probe_unreachable_does_not_fail_validation(
    fake_config, monkeypatch, caplog
) -> None:
    fake_config.AI_PROVIDER = "ollama"
    _install_fake_httpx_client(monkeypatch, status_code=None, requested=[])

    with caplog.at_level(logging.WARNING):
        assert _validate(fake_config) is True
    assert "<ollama_unreachable> http://localhost:11434" in caplog.text
