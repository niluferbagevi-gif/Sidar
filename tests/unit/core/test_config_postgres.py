import pytest

from core import config_postgres


def test_load_database_settings_groups_database_domain_with_production_defaults():
    values = {
        "SIDAR_ENV": "production",
        "DATABASE_URL": "postgresql+asyncpg://user:secret@db:5432/sidar",
        "SIDAR_CONTAINER_DATABASE_URL": "postgresql+asyncpg://user:secret@postgres:5432/sidar",
        "DB_DEGRADED_SQLITE_URL": "sqlite+aiosqlite:///fallback.db",
        "DB_SCHEMA_VERSION_TABLE": "sidar_schema_versions",
    }

    settings = config_postgres.load_database_settings(
        getenv=_getenv(values),
        get_bool_env=lambda key, default: default,
        get_int_env=lambda key, default: default,
        get_float_env=lambda key, default: default,
        default_pool_size=12,
    )

    assert settings.database_url == values["DATABASE_URL"]
    assert settings.sidar_container_database_url == values["SIDAR_CONTAINER_DATABASE_URL"]
    assert settings.pool_size == 12
    assert settings.degraded_sqlite_url == "sqlite+aiosqlite:///fallback.db"
    assert settings.schema_version_table == "sidar_schema_versions"
    assert settings.auto_migrate is False


def test_load_database_settings_preserves_explicit_typed_overrides():
    bool_values = {
        "SIDAR_ALLOW_INSECURE_LOCAL_DB_DEFAULT": True,
        "DB_DEGRADED_MODE_ON_POSTGRES_FAILURE": False,
        "SIDAR_AUTO_MIGRATE": True,
    }
    int_values = {
        "DB_POOL_SIZE": 7,
        "DB_POOL_MIN_SIZE": 2,
        "DB_STATEMENT_CACHE_SIZE": 64,
        "DB_SCHEMA_TARGET_VERSION": 9,
    }

    settings = config_postgres.load_database_settings(
        getenv=_getenv({"SIDAR_ENV": "development"}),
        get_bool_env=lambda key, default: bool_values.get(key, default),
        get_int_env=lambda key, default: int_values.get(key, default),
        get_float_env=lambda key, default: (
            45.5 if key == "DB_MAX_CACHED_STATEMENT_LIFETIME" else default
        ),
        default_pool_size=10,
    )

    assert settings.allow_insecure_local_default is True
    assert settings.degraded_mode_on_postgres_failure is False
    assert settings.auto_migrate is True
    assert settings.pool_size == 7
    assert settings.pool_min_size == 2
    assert settings.statement_cache_size == 64
    assert settings.schema_target_version == 9
    assert settings.max_cached_statement_lifetime == 45.5


def _getenv(values):
    return lambda key, default=None: values.get(key, default)


def test_read_env_returns_default_when_getter_returns_none():
    assert (
        config_postgres._read_env(lambda _key, _default: None, "POSTGRES_USER", "sidar") == "sidar"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "5432"),
        ("", "5432"),
        ("   ", "5432"),
        ("not-a-port", "5432"),
        ("-1", "5432"),
        ("0", "5432"),
        ("65536", "5432"),
        ("15432", "15432"),
        (" 6543 ", "6543"),
    ],
)
def test_normalize_postgres_port_handles_valid_and_invalid_values(value, expected):
    assert config_postgres._normalize_postgres_port(value) == expected


def test_build_postgres_dsn_falls_back_for_invalid_port_and_quotes_components():
    values = {
        "POSTGRES_USER": "sidar user",
        "POSTGRES_PASSWORD": "p@ ss/word",
        "POSTGRES_HOST": " db.internal ",
        "POSTGRES_PORT": "bad-port",
        "POSTGRES_DB": "sidar db",
    }

    assert (
        config_postgres.build_postgres_dsn(getenv=_getenv(values))
        == "postgresql+asyncpg://sidar%20user:p%40%20ss%2Fword@db.internal:5432/sidar%20db"
    )


def test_database_url_helpers_return_explicit_urls():
    values = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/app",
        "SIDAR_CONTAINER_DATABASE_URL": "postgresql+asyncpg://u:p@postgres:5432/app",
    }

    assert (
        config_postgres.get_database_url(getenv=_getenv(values))
        == "postgresql+asyncpg://u:p@db:5432/app"
    )
    assert (
        config_postgres.get_container_database_url(getenv=_getenv(values))
        == "postgresql+asyncpg://u:p@postgres:5432/app"
    )


def test_container_database_url_prefers_explicit_sidar_container_url_and_trims_it():
    values = {
        "SIDAR_CONTAINER_DATABASE_URL": "  postgresql+asyncpg://u:p@container:5432/app  ",
        "POSTGRES_CONTAINER_HOST": "should-not-be-used",
    }

    assert (
        config_postgres.get_container_database_url(getenv=_getenv(values))
        == "postgresql+asyncpg://u:p@container:5432/app"
    )


def test_container_database_url_uses_container_host_when_explicit_url_is_missing():
    values = {
        "POSTGRES_USER": "sidar",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "app",
        "POSTGRES_PORT": "6543",
        "POSTGRES_CONTAINER_HOST": "postgres-service",
    }

    assert (
        config_postgres.get_container_database_url(getenv=_getenv(values))
        == "postgresql+asyncpg://sidar:secret@postgres-service:6543/app"
    )


def test_postgres_password_drift_messages_detects_url_password_mismatch():
    values = {
        "POSTGRES_PASSWORD": "strong-password-1234567890!Aa",
        "DATABASE_URL": "postgresql+asyncpg://sidar:old@127.0.0.1:5432/sidar",
        "SIDAR_CONTAINER_DATABASE_URL": "postgresql+asyncpg://sidar:strong-password-1234567890%21Aa@postgres:5432/sidar",
    }

    assert config_postgres.postgres_password_drift_messages(getenv=_getenv(values)) == [
        "DATABASE_URL parolası POSTGRES_PASSWORD ile senkron değil."
    ]


@pytest.mark.parametrize("password_value", [None, ""])
def test_postgres_password_drift_messages_skip_when_postgres_password_is_missing_or_empty(
    password_value,
):
    values = {
        "POSTGRES_PASSWORD": password_value,
        "DATABASE_URL": "postgresql+asyncpg://sidar:old@127.0.0.1:5432/sidar",
        "SIDAR_CONTAINER_DATABASE_URL": "postgresql+asyncpg://sidar:old@postgres:5432/sidar",
    }

    assert config_postgres.postgres_password_drift_messages(getenv=_getenv(values)) == []


def test_postgres_password_drift_messages_skip_empty_url_entries():
    values = {
        "POSTGRES_PASSWORD": "secret",
        "DATABASE_URL": "   ",
        "SIDAR_CONTAINER_DATABASE_URL": "postgresql+asyncpg://sidar:wrong@postgres:5432/sidar",
    }

    assert config_postgres.postgres_password_drift_messages(getenv=_getenv(values)) == [
        "SIDAR_CONTAINER_DATABASE_URL parolası POSTGRES_PASSWORD ile senkron değil."
    ]


def test_postgres_password_drift_messages_ignore_non_postgresql_urls():
    values = {
        "POSTGRES_PASSWORD": "secret",
        "DATABASE_URL": "sqlite:///sidar.db",
        "SIDAR_CONTAINER_DATABASE_URL": "mysql://sidar:wrong@mysql:3306/sidar",
    }

    assert config_postgres.postgres_password_drift_messages(getenv=_getenv(values)) == []


def test_postgres_password_drift_messages_reports_passwordless_postgresql_urls():
    values = {
        "POSTGRES_PASSWORD": "secret",
        "DATABASE_URL": "postgresql+asyncpg://sidar@127.0.0.1:5432/sidar",
        "SIDAR_CONTAINER_DATABASE_URL": "postgresql://sidar@postgres:5432/sidar",
    }

    assert config_postgres.postgres_password_drift_messages(getenv=_getenv(values)) == [
        "DATABASE_URL PostgreSQL URL parolası içermiyor; POSTGRES_PASSWORD ile senkron değil.",
        "SIDAR_CONTAINER_DATABASE_URL PostgreSQL URL parolası içermiyor; POSTGRES_PASSWORD ile "
        "senkron değil.",
    ]
