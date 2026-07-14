"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

import contextlib
import importlib
import os
import sys
from collections.abc import AsyncGenerator, Callable, Generator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Bazı modüller import anında Config() oluşturuyor.
# Pytest collection aşamasında test-env işaretleri henüz garanti olmadığından
# kritik ayarların boş gelmesini önlemek için en erken noktada varsayılanları set ediyoruz.
os.environ.setdefault("SIDAR_ENV", "test")
if os.getenv("SIDAR_TEST_LOAD_REAL_KEYS", "0").strip().lower() not in {"1", "true", "yes"}:
    os.environ["SIDAR_KEYS_FILE"] = ""
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-ci-testing-only!")
os.environ.setdefault("CODE_EXECUTION_BACKEND", "disabled")
os.environ.setdefault("DOCKER_AUTODETECT", "0")
os.environ.setdefault("PROMPT_GUARD_ENABLED", "0")

import pytest

from tests._fixtures import dotenv as _dotenv_fixtures
from tests._fixtures.dotenv import (
    assert_test_dotenv_postgres_parity as _fixture_assert_test_dotenv_postgres_parity,
)
from tests._fixtures.dotenv import (
    load_pytest_dotenv_chain as _fixture_load_pytest_dotenv_chain,
)


def _is_truthy_env(value: str | None) -> bool:
    """Return whether an environment flag is explicitly enabled."""
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _isolate_github_env_for_tests() -> None:
    """Keep real GitHub credentials/repositories out of default pytest runs."""
    if _is_truthy_env(os.getenv("SIDAR_TEST_LOAD_REAL_GITHUB")):
        return
    os.environ["GITHUB_TOKEN"] = ""
    os.environ["GITHUB_REPO"] = ""


def _disable_prompt_guard_for_tests() -> None:
    """Avoid eager NeMo Guardrails imports during default unit-test collection."""
    if _is_truthy_env(os.getenv("SIDAR_TEST_ENABLE_PROMPT_GUARD")):
        return
    os.environ["PROMPT_GUARD_ENABLED"] = "0"


def _sync_dotenv_fixture_project_root() -> None:
    _dotenv_fixtures.PROJECT_ROOT = PROJECT_ROOT


def _load_pytest_dotenv_chain() -> None:
    _sync_dotenv_fixture_project_root()
    _fixture_load_pytest_dotenv_chain()


def _assert_test_dotenv_postgres_parity() -> None:
    _sync_dotenv_fixture_project_root()
    # Guard details intentionally stay visible here for quality-gate tests:
    # .env.test içindeki POSTGRES_PASSWORD drift can surface as InvalidPasswordError.
    # Düzeltme: `uv run python scripts/sync_database_passwords.py --all-envs`.
    _fixture_assert_test_dotenv_postgres_parity()


_load_pytest_dotenv_chain()
_isolate_github_env_for_tests()
_disable_prompt_guard_for_tests()
_assert_test_dotenv_postgres_parity()

_REQUIRED_TEST_MODULES = {
    "pytest_asyncio": "pytest-asyncio",
    "freezegun": "freezegun",
    "sqlalchemy": "sqlalchemy",
    "testcontainers": "testcontainers",
}
_missing_test_deps = [
    pkg_name
    for module_name, pkg_name in _REQUIRED_TEST_MODULES.items()
    if importlib.util.find_spec(module_name) is None
]
if _missing_test_deps:
    missing = ", ".join(sorted(set(_missing_test_deps)))
    raise pytest.UsageError(
        f"Eksik test bağımlılıkları: {missing}. Önce `uv sync --all-extras` çalıştırın."
    )

import pytest_asyncio
from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory

from tests._fixtures.agent import agent_factory as agent_factory
from tests._fixtures.agent import fake_event_stream as fake_event_stream
from tests._fixtures.agent import fake_llm_error as fake_llm_error
from tests._fixtures.agent import fake_llm_response as fake_llm_response
from tests._fixtures.agent import fake_social_api as fake_social_api
from tests._fixtures.agent import fake_video_stream as fake_video_stream
from tests._fixtures.agent import fake_video_stream_error as fake_video_stream_error
from tests._fixtures.agent import sidar_agent_factory as sidar_agent_factory
from tests._fixtures.postgres import fake_db_session as fake_db_session
from tests._fixtures.postgres import pg_container as pg_container
from tests._fixtures.postgres import pg_db_session as pg_db_session
from tests._fixtures.postgres import pg_schema_initialized as pg_schema_initialized
from tests._fixtures.postgres import sqlite_db as sqlite_db
from tests._fixtures.redis import fake_redis as fake_redis
from tests.fixtures.factories import build_hitl_request
from tests.helpers import make_test_config

DEFAULT_FREEZEGUN_IGNORE_MODULES = (
    "transformers",
    "tiktoken",
    "pydantic",
    # LLM/ML ekosisteminde lazy-import zinciri yoğun paketler.
    # freezegun yüklü modüllerin attribute'larını gezerken transformers /
    # sentencepiece yanında huggingface_hub -> torch -> triton zincirini de
    # tetikleyebilir; torch tarafındaki TORCH_LIBRARY kayıtları ikinci kez
    # çalıştırıldığında test süreci deterministik olmayan biçimde düşebilir.
    "tokenizers",
    "langchain",
    "langchain_core",
    "langchain_community",
    "huggingface_hub",
    "torch",
    "triton",
)


def _build_freezegun_ignore_modules() -> list[str]:
    extra_raw = os.getenv("TEST_FREEZEGUN_IGNORE_MODULES", "")
    extras = [item.strip() for item in extra_raw.split(",") if item.strip()]
    # Aynı modülün tekrar eklenmesini önleyip deterministik sıra korur.
    return list(dict.fromkeys([*DEFAULT_FREEZEGUN_IGNORE_MODULES, *extras]))


_CONTRACTS_MODULE_SENTINEL = object()


@pytest.fixture(autouse=True)
def _isolate_contracts_module() -> Generator[None, None, None]:
    """Test pollutionunu runtime koduna taşımadan contracts modülünü izole et."""
    original = sys.modules.get("agent.core.contracts", _CONTRACTS_MODULE_SENTINEL)
    yield
    current = sys.modules.get("agent.core.contracts", _CONTRACTS_MODULE_SENTINEL)
    if current is not original:
        if original is _CONTRACTS_MODULE_SENTINEL:
            sys.modules.pop("agent.core.contracts", None)
        else:
            sys.modules["agent.core.contracts"] = cast(ModuleType, original)

    swarm_module = sys.modules.get("agent.swarm")
    if swarm_module is not None:
        contracts_module = (
            importlib.import_module("agent.core.contracts")
            if original is _CONTRACTS_MODULE_SENTINEL
            else cast(ModuleType, original)
        )
        sys.modules["agent.core.contracts"] = contracts_module
        swarm_module._CONTRACTS_MODULE_CACHE = None
        ensure_aliases = getattr(swarm_module, "_ensure_contract_aliases", None)
        if callable(ensure_aliases):
            ensure_aliases()


@pytest.fixture(autouse=True)
def _isolate_supervisor_module() -> Generator[None, None, None]:
    """Restore supervisor imports so production code does not need reload guards."""

    module_name = "agent.core.supervisor"
    package_name = "agent.core"
    package = sys.modules.get(package_name)
    original_module = sys.modules.get(module_name, _CONTRACTS_MODULE_SENTINEL)
    original_package_attr = (
        getattr(package, "supervisor", _CONTRACTS_MODULE_SENTINEL)
        if package is not None
        else _CONTRACTS_MODULE_SENTINEL
    )

    yield

    if original_module is _CONTRACTS_MODULE_SENTINEL:
        sys.modules.pop(module_name, None)
    else:
        sys.modules[module_name] = cast(ModuleType, original_module)

    current_package = sys.modules.get(package_name)
    if current_package is None:
        return
    if original_package_attr is _CONTRACTS_MODULE_SENTINEL:
        with contextlib.suppress(AttributeError):
            delattr(current_package, "supervisor")
    else:
        current_package.supervisor = original_package_attr


@pytest.fixture(autouse=True)
def _set_default_llm_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini/Google istemci yolları için testte güvenli sahte anahtarlar tanımlar."""
    monkeypatch.setenv("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", "test_key"))
    monkeypatch.setenv("GOOGLE_API_KEY", os.getenv("GOOGLE_API_KEY", "test_key"))


def _test_needs_web_server_runtime(request: pytest.FixtureRequest) -> bool:
    """Return whether a test path intentionally exercises the root web_server module."""
    nodeid = str(request.node.nodeid)
    return nodeid.startswith(
        (
            "tests/unit/root/",
            "tests/unit/web/",
            "tests/integration/api/",
            "tests/integration/web/",
            "tests/e2e/web/",
            "tests/smoke/test_boot.py",
        )
    )


@pytest.fixture(autouse=True)
def _isolate_root_web_server_database_url(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """Keep legacy web_server unit tests off developer PostgreSQL instances.

    The root web_server compatibility tests exercise route glue, not PostgreSQL
    connectivity. They import the production module but should resolve DB-backed
    helpers through an isolated SQLite database so local ``.env`` PostgreSQL
    credentials cannot leak into unit-test execution. PostgreSQL smoke and
    integration tests continue to opt into their own dedicated fixtures.
    """
    if not str(request.node.nodeid).startswith("tests/unit/root/"):
        return

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'sidar_root_unit.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    with contextlib.suppress(Exception):
        web_server_module = importlib.import_module("web_server")
        monkeypatch.setattr(web_server_module.cfg, "DATABASE_URL", database_url, raising=False)


@pytest.fixture(autouse=True)
def _isolate_webhook_secrets(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Prevent local webhook secrets from leaking into signature-optional tests."""
    if not _test_needs_web_server_runtime(request):
        return

    for key in (
        "GITHUB_WEBHOOK_SECRET",
        "AUTONOMY_WEBHOOK_SECRET",
        "SIDAR_GITHUB_WEBHOOK_SECRET",
        "SIDAR_AUTONOMY_WEBHOOK_SECRET",
        "SWARM_FEDERATION_SHARED_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)

    web_server_module = importlib.import_module("web_server")
    monkeypatch.setattr(web_server_module.cfg, "GITHUB_WEBHOOK_SECRET", "", raising=False)
    monkeypatch.setattr(web_server_module.cfg, "AUTONOMY_WEBHOOK_SECRET", "", raising=False)
    monkeypatch.setattr(web_server_module.cfg, "SWARM_FEDERATION_SHARED_SECRET", "", raising=False)


def _reset_web_route_dependency_factories() -> None:
    """Restore module-scoped web route dependency factories to production builders."""
    with contextlib.suppress(Exception):
        web_server_module = importlib.import_module("web_server")
        web_server_module.federation_routes.configure_federation_dependencies(
            web_server_module._build_federation_dependencies
        )
        web_server_module.autonomy_routes.configure_autonomy_dependencies(
            web_server_module._build_autonomy_dependencies
        )


@pytest.fixture(autouse=True)
def _reset_route_dependency_factories(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    """Keep module-scoped web route dependency factories isolated between tests.

    ``web.routes.federation`` and ``web.routes.autonomy`` keep their dependency
    factories in module-level globals so route-level tests can install small
    stubs without constructing the full root ``web_server`` module.  Without a
    suite-wide reset, a later root-level alias test that runs in the same pytest
    worker can inherit those stubs and bypass monkeypatched ``web_server``
    dependencies, which makes xdist ordering affect HMAC/signature behavior.
    """
    if not _test_needs_web_server_runtime(request):
        yield
        return

    _reset_web_route_dependency_factories()
    yield
    _reset_web_route_dependency_factories()


_MISSING_SYS_MODULE = object()
_SENSITIVE_SYS_MODULES = (
    "agent.base_agent",
    "chromadb.utils.embedding_functions",
    "core.db",
    "core.doctor",
    "core.llm_client",
)
_SENSITIVE_SYS_MODULE_ATTRIBUTES = {
    "agent.base_agent": ("BaseAgent",),
}
_CRITICAL_SYS_MODULE_CONTRACTS = {
    "core.db": ("Database", "UserRecord", "SessionRecord"),
    "core.doctor": ("DoctorCheck", "run_doctor_report", "check_database_env"),
    "core.llm_client": ("BaseLLMClient", "LLMAPIError", "LLMClient"),
}


def _critical_sys_module_pollution_errors(
    snapshot: dict[str, object], *, allow_pending_monkeypatch: bool = False
) -> list[str]:
    """Return critical module-table mutations that escaped fixture cleanup.

    Some tests intentionally replace import-heavy runtime modules with lightweight
    stubs. Those mutations must be scoped with ``monkeypatch`` or restored before
    the test exits; otherwise later tests in the same xdist worker can import a
    fake ``core.db``/``core.llm_client`` and fail nondeterministically.
    """

    errors: list[str] = []
    for name, required_attrs in _CRITICAL_SYS_MODULE_CONTRACTS.items():
        original = snapshot.get(name, _MISSING_SYS_MODULE)
        current = sys.modules.get(name, _MISSING_SYS_MODULE)
        if current is _MISSING_SYS_MODULE:
            continue
        missing_attrs = [attr for attr in required_attrs if not hasattr(current, attr)]
        replaced = original is not _MISSING_SYS_MODULE and current is not original
        if allow_pending_monkeypatch and (missing_attrs or replaced):
            # This autouse fixture finalizes before pytest's monkeypatch fixture in
            # tests that requested monkeypatch directly.  In that case the fake
            # module is still visible here but will be undone immediately after
            # this fixture finalizer.  We still restore from our own snapshot
            # below, so cross-test pollution is prevented without false failures.
            continue
        if missing_attrs or replaced:
            module_file = getattr(current, "__file__", "")
            module_path = getattr(current, "__path__", "")
            errors.append(
                f"{name} polluted in sys.modules"
                f" (replaced={replaced}, missing_attrs={missing_attrs},"
                f" file={module_file!r}, path={module_path!r})"
            )
    return errors


@pytest.fixture(autouse=True)
def _restore_polluted_sys_modules(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Restore process-global modules and reload-sensitive class identities."""

    snapshot = {name: sys.modules.get(name, _MISSING_SYS_MODULE) for name in _SENSITIVE_SYS_MODULES}
    attribute_snapshot = {
        name: {
            attribute: getattr(module, attribute, _MISSING_SYS_MODULE) for attribute in attributes
        }
        for name, attributes in _SENSITIVE_SYS_MODULE_ATTRIBUTES.items()
        if (module := snapshot.get(name, _MISSING_SYS_MODULE)) is not _MISSING_SYS_MODULE
    }
    yield
    pollution_errors = _critical_sys_module_pollution_errors(
        snapshot, allow_pending_monkeypatch="monkeypatch" in request.fixturenames
    )
    for name, original in snapshot.items():
        if original is _MISSING_SYS_MODULE:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original  # type: ignore[assignment]
    for name, attributes in attribute_snapshot.items():
        module = sys.modules.get(name)
        if module is None:
            continue
        for attribute, original in attributes.items():
            if original is _MISSING_SYS_MODULE:
                with contextlib.suppress(AttributeError):
                    delattr(module, attribute)
            else:
                setattr(module, attribute, original)
    if pollution_errors:
        pytest.fail(
            "Test polluted critical sys.modules entries; use monkeypatch.setitem/delitem "
            "or restore the original module before teardown: " + "; ".join(pollution_errors),
            pytrace=False,
        )


@pytest_asyncio.fixture(autouse=True)
async def _reset_global_agent_event_bus_runtime() -> AsyncGenerator[None, None]:
    """Her testten sonra process-global AgentEventBus runtime state'ini kapatır.

    `agent.core.event_stream` modülü `_BUS` singleton'ını process genelinde tutar,
    pytest-asyncio ise testler için function-scope event loop oluşturur.  Redis /
    RabbitMQ / Kafka listener veya bootstrap task'ları loop kapanmadan await edilmezse
    sonraki testlerde `Task was destroyed but it is pending` ve un-awaited Redis
    connection uyarıları `filterwarnings = error` nedeniyle suite'i düşürebilir.
    """

    yield

    bus_module = sys.modules.get("agent.core.event_stream")
    bus = getattr(bus_module, "_BUS", None) if bus_module is not None else None
    reset_runtime_state = getattr(bus, "reset_runtime_state", None)
    if callable(reset_runtime_state):
        await reset_runtime_state()


# Not: `cli` modülünü burada global olarak import etmiyoruz.
# Böylece pytest-cov ölçümü başlamadan önce `cli.py` yüklenip
# "already-imported" kaynaklı kapsama sapması oluşturmaz.


@pytest.fixture
def make_test_client() -> Callable[..., Any]:
    """Create FastAPI/Starlette TestClient instances through one test helper."""
    from fastapi.testclient import TestClient

    def _make_test_client(app: Any, **kwargs: Any) -> Any:
        return TestClient(app, **kwargs)

    return _make_test_client


@pytest.fixture
def mock_config() -> Callable[..., Any]:
    return make_test_config


@pytest.fixture
def hitl_request_factory() -> Callable[..., Any]:
    return build_hitl_request


@pytest.fixture
def frozen_time() -> Generator[FrozenDateTimeFactory, None, None]:
    """Tüm zaman bağımlı operasyonları deterministik hale getirmek için ortak fixture."""
    # freezegun, loaded modüllerin attribute'larını gezerken transformers'ın lazy
    # import zincirini tetikleyebiliyor; bu da opsiyonel sentencepiece bağımlılığı
    # yoksa test setup sırasında patlamaya neden oluyor.
    with freeze_time("2026-04-01 12:00:00", ignore=_build_freezegun_ignore_modules()) as frozen:
        yield frozen


@pytest.fixture
def respx_mock_router() -> Generator[Any, None, None]:
    respx = pytest.importorskip("respx")
    # Varsayılanı sıkı tut: test içinde kaydedilen her route en az bir kez çağrılmalı.
    with respx.mock(assert_all_called=True) as router:
        yield router


@pytest.fixture
def respx_mock_router_relaxed() -> Generator[Any, None, None]:
    """Bazı rotaların bilinçli olarak çağrılmadığı senaryolar için gevşek router."""
    respx = pytest.importorskip("respx")
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def fake_lsp_client() -> AsyncMock:
    """v5.x core/lsp.py testleri için deterministik Language Server Fake adaptörü."""
    client = AsyncMock()
    client.request_hover.return_value = {"contents": "mocked LSP hover documentation"}
    client.request_diagnostics.return_value = [
        {"line": 10, "message": "mocked error", "severity": 1},
    ]

    def set_timeout() -> None:
        client.request_hover.side_effect = TimeoutError("LSP connection timed out")

    client.set_timeout = set_timeout
    return client


@pytest.fixture
def fake_coverage_code_manager() -> MagicMock:
    """Coverage testleri için standart MagicMock kullanan code manager."""
    mock_manager = MagicMock()

    mock_manager.run_pytest_and_collect = AsyncMock(
        return_value={
            "analysis": {"summary": "ok", "findings": []},
            "output": "OUT",
        }
    )
    mock_manager.analyze_pytest_output = AsyncMock(
        side_effect=lambda output: {
            "summary": f"ANALYZED:{output}",
            "findings": [{"target_path": "src/m.py"}],
        }
    )
    mock_manager.read_file = AsyncMock(side_effect=lambda path: (True, f"SOURCE:{path}"))
    mock_manager.write_generated_test = AsyncMock(
        side_effect=lambda path, content, append=True: (
            True,
            f"WROTE:{path}:{append}",
        )
    )

    return mock_manager


@pytest.fixture
def fake_coverage_db_class() -> type:
    """Coverage DB için AsyncMock kullanan factory sınıfı."""

    class _FakeCoverageDB:
        def __init__(self, cfg: Any) -> None:
            self.cfg = cfg
            self.connect = AsyncMock()
            self.init_schema = AsyncMock()
            self.create_coverage_task = AsyncMock(return_value=SimpleNamespace(id=123))
            self.add_coverage_finding = AsyncMock()

    return _FakeCoverageDB


@pytest.fixture
def fake_llm_tool_sequence() -> Callable[[list[str]], AsyncMock]:
    """Araç çağrısı akışları için sıralı LLM çıktısı üreten yardımcı fixture."""

    def _build(responses: list[str]) -> AsyncMock:
        return AsyncMock(side_effect=list(responses))

    return _build


@pytest.fixture
def fake_web_search_result() -> Callable[[bool, str], AsyncMock]:
    """Web arama katmanı için deterministik sonuç üreten yardımcı fixture."""

    def _build(ok: bool, payload: str) -> AsyncMock:
        return AsyncMock(return_value=(ok, payload))

    return _build


@pytest.fixture
def fake_vector_store() -> AsyncMock:
    """core/rag.py testleri için deterministik vector DB adaptörü."""
    mock_store = AsyncMock(
        spec=["search", "add_documents", "delete", "set_empty_result", "set_db_error"]
    )

    mock_store.search.return_value = [
        {"id": "doc-1", "content": "mock context for RAG", "score": 0.95},
        {"id": "doc-2", "content": "secondary context", "score": 0.88},
    ]
    mock_store.add_documents.return_value = True

    def set_empty_result() -> None:
        mock_store.search.side_effect = None
        mock_store.search.return_value = []

    def set_db_error() -> None:
        mock_store.search.side_effect = ConnectionError("Vector DB connection lost")

    mock_store.set_empty_result = set_empty_result
    mock_store.set_db_error = set_db_error
    return mock_store


@pytest.fixture
def mock_chromadb(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """chromadb/chromadb.config bağımlılıklarını gerçek modüller üstünden patch eder."""

    def _install(
        *,
        persistent_client_factory: Callable[..., Any],
        settings_factory: Callable[..., Any] | None = None,
    ) -> None:
        chromadb = pytest.importorskip("chromadb", exc_type=ImportError)
        chromadb_config = pytest.importorskip("chromadb.config", exc_type=ImportError)
        monkeypatch.setattr(chromadb, "PersistentClient", persistent_client_factory)
        if settings_factory is not None:
            monkeypatch.setattr(chromadb_config, "Settings", settings_factory)

    return _install


@pytest.fixture
def mock_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> Callable[[type], None]:
    """sentence_transformers bağımlılığını torch/triton import etmeden fake modülle patch eder."""

    def _install(sentence_transformer_cls: type) -> None:
        fake_module = ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = sentence_transformer_cls
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    return _install


@pytest.fixture
def mock_sentence_transformer_class(monkeypatch: pytest.MonkeyPatch) -> Callable[[type], None]:
    """core.embeddings içindeki SentenceTransformer class resolver'ını fake sınıfa yönlendirir."""

    def _install(sentence_transformer_cls: type) -> None:
        from core import embeddings

        embeddings.clear_model_cache()
        monkeypatch.setattr(
            embeddings, "_load_sentence_transformer_class", lambda: sentence_transformer_cls
        )

    return _install


@pytest.fixture
def mock_requests(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """requests bağımlılığını gerçek modül üstünden patch eder."""

    def _install(*, get_impl: Callable[..., Any]) -> None:
        requests = pytest.importorskip("requests")
        monkeypatch.setattr(requests, "get", get_impl)

    return _install
