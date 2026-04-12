import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys
import types


@contextmanager
def _dummy_txn():
    yield


class _FakeConfig:
    config_file_name = None
    config_ini_section = "alembic"

    def get_main_option(self, key: str) -> str:
        assert key == "sqlalchemy.url"
        return "sqlite:///fallback.db"

    def get_section(self, _name: str):
        return {"sqlalchemy.url": "sqlite:///fallback.db"}


class _FakeContext:
    def __init__(self):
        self.config = _FakeConfig()
        self._x_args = {}

    def get_x_argument(self, as_dictionary: bool = False):
        assert as_dictionary is True
        return self._x_args

    def configure(self, **kwargs):
        self.configured = kwargs

    def begin_transaction(self):
        return _dummy_txn()

    def run_migrations(self):
        return None

    def is_offline_mode(self):
        return True


def _import_env_module(monkeypatch, fake_context):
    alembic_mod = types.ModuleType("alembic")
    alembic_mod.context = fake_context
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)

    sqlalchemy_mod = types.ModuleType("sqlalchemy")
    sqlalchemy_mod.pool = types.SimpleNamespace(NullPool=object)

    async_mod = types.ModuleType("sqlalchemy.ext.asyncio")

    class _FakeAsyncEngine:
        pass

    async_mod.AsyncEngine = _FakeAsyncEngine
    async_mod.create_async_engine = lambda *args, **kwargs: _FakeAsyncEngine()

    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_mod)
    monkeypatch.setitem(sys.modules, "sqlalchemy.ext", types.ModuleType("sqlalchemy.ext"))
    monkeypatch.setitem(sys.modules, "sqlalchemy.ext.asyncio", async_mod)

    env_path = Path("migrations/env.py")
    spec = importlib.util.spec_from_file_location("migrations.env", env_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_load_database_url_prefers_x_argument(monkeypatch):
    fake_context = _FakeContext()
    fake_context._x_args = {"database_url": "postgresql://x/y"}

    module = _import_env_module(monkeypatch, fake_context)

    assert module._load_database_url() == "postgresql://x/y"


def test_load_database_url_falls_back_to_env(monkeypatch):
    fake_context = _FakeContext()
    module = _import_env_module(monkeypatch, fake_context)

    monkeypatch.setenv("DATABASE_URL", "postgresql://env/value")

    assert module._load_database_url() == "postgresql://env/value"


def test_fake_config_fallback_values():
    config = _FakeConfig()
    assert config.get_main_option("sqlalchemy.url") == "sqlite:///fallback.db"
    assert config.get_section("alembic") == {"sqlalchemy.url": "sqlite:///fallback.db"}
