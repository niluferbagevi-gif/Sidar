from core import config_postgres


def test_read_env_returns_default_when_getter_returns_none():
    assert config_postgres._read_env(lambda _key, _default: None, "POSTGRES_USER", "sidar") == "sidar"


def test_normalize_postgres_port_rejects_malformed_and_out_of_range_values():
    assert config_postgres._normalize_postgres_port("not-a-port") == "5432"
    assert config_postgres._normalize_postgres_port("0") == "5432"
    assert config_postgres._normalize_postgres_port("65536") == "5432"


def test_database_url_helpers_return_explicit_urls():
    def getenv(key, default=None):
        values = {
            "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/app",
            "SIDAR_CONTAINER_DATABASE_URL": "postgresql+asyncpg://u:p@postgres:5432/app",
        }
        return values.get(key, default)

    assert config_postgres.get_database_url(getenv=getenv) == "postgresql+asyncpg://u:p@db:5432/app"
    assert (
        config_postgres.get_container_database_url(getenv=getenv)
        == "postgresql+asyncpg://u:p@postgres:5432/app"
    )
