import importlib.util
from pathlib import Path
import sys
import types


class FakeOp:
    def __init__(self):
        self.calls = []

    def create_table(self, name, *args, **kwargs):
        self.calls.append(("create_table", name))

    def create_index(self, name, table_name, columns, *args, **kwargs):
        self.calls.append(("create_index", name, table_name, tuple(columns)))

    def drop_index(self, name, *args, **kwargs):
        self.calls.append(("drop_index", name))

    def drop_table(self, name, *args, **kwargs):
        self.calls.append(("drop_table", name))

    def execute(self, statement):
        self.calls.append(("execute", str(statement)))


class _BoundText:
    def __init__(self, value: str):
        self.value = value

    def bindparams(self, **kwargs):
        self.kwargs = kwargs
        return self

    def __str__(self) -> str:
        return self.value


def _install_fake_dependencies():
    fake_alembic = types.ModuleType("alembic")
    fake_alembic.op = FakeOp()
    sys.modules["alembic"] = fake_alembic

    fake_sa = types.ModuleType("sqlalchemy")

    def _ctor(name):
        return lambda *args, **kwargs: (name, args, kwargs)

    fake_sa.Column = _ctor("Column")
    fake_sa.String = _ctor("String")
    fake_sa.Text = _ctor("Text")
    fake_sa.DateTime = _ctor("DateTime")
    fake_sa.Integer = _ctor("Integer")
    fake_sa.BigInteger = _ctor("BigInteger")
    fake_sa.Date = _ctor("Date")
    fake_sa.Boolean = _ctor("Boolean")
    fake_sa.Numeric = _ctor("Numeric")
    fake_sa.ForeignKey = _ctor("ForeignKey")
    fake_sa.UniqueConstraint = _ctor("UniqueConstraint")
    fake_sa.text = lambda value: _BoundText(value)
    sys.modules["sqlalchemy"] = fake_sa


def load_migration(file_name: str):
    path = Path("migrations/versions") / file_name
    _install_fake_dependencies()

    if file_name == "0002_prompt_registry.py":
        fake_defs = types.ModuleType("agent.definitions")
        fake_defs.SIDAR_SYSTEM_PROMPT = "system prompt"
        sys.modules["agent.definitions"] = fake_defs

    spec = importlib.util.spec_from_file_location(f"test_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module
