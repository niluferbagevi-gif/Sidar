"""Smoke tests for application boot sanity."""

import inspect
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from agent.registry import AgentCatalog
from tests.helpers import make_test_config


def _is_external_infra_checks_disabled() -> bool:
    return os.getenv("SMOKE_SKIP_EXTERNAL_INFRA", "0") == "1"


def test_boot_agent_catalog_api_available() -> None:
    """Boot sonrası AgentCatalog API'sinin çalıştığını doğrular."""
    specs = AgentCatalog.list_all()
    assert isinstance(specs, list)


def test_boot_agent_catalog_unknown_role_returns_none() -> None:
    """Kayıtlı olmayan rol sorgusunda None dönüldüğünü doğrular."""
    assert AgentCatalog.get("__missing_role__") is None


def test_boot_agent_catalog_can_instantiate_coder_agent() -> None:
    """Kritik yerleşik rolün bağımlılıklarıyla birlikte örneklenebildiğini doğrular."""
    # Dekoratör-kayıt zinciri bu import ile tetiklenir; import başarısızsa smoke fail olmalıdır.
    from agent.roles.coder_agent import CoderAgent  # noqa: F401

    cfg = make_test_config(BASE_DIR=os.getcwd())
    coder_agent = AgentCatalog.create("coder", cfg=cfg)

    assert getattr(coder_agent, "role_name", "") == "coder"
    assert callable(getattr(coder_agent, "run_task", None))
    assert {"read_file", "write_file", "execute_code"}.issubset(set(getattr(coder_agent, "tools", {}).keys()))


def test_environment_sanity_required_ai_provider_settings() -> None:
    """Aktif AI sağlayıcısı için zorunlu kimlik/endpoint ayarlarının yüklü olduğunu doğrular."""
    config_module = pytest.importorskip("config")
    cfg = config_module.Config

    provider = str(getattr(cfg, "AI_PROVIDER", "") or "").strip().lower()
    requirements: dict[str, tuple[str, ...]] = {
        "openai": ("OPENAI_API_KEY",),
        "anthropic": ("ANTHROPIC_API_KEY",),
        "gemini": ("GEMINI_API_KEY",),
        "litellm": ("LITELLM_GATEWAY_URL",),
        "ollama": ("OLLAMA_URL",),
    }
    required_fields = requirements.get(provider, tuple())

    missing_fields = [field for field in required_fields if not str(getattr(cfg, field, "") or "").strip()]
    assert not missing_fields, (
        f"Aktif AI sağlayıcısı '{provider}' için eksik yapılandırmalar: {', '.join(missing_fields)}"
    )

    if provider == "ollama":
        assert str(getattr(cfg, "OLLAMA_URL", "")).startswith("http"), "OLLAMA_URL http/https ile başlamalı."
    if provider == "litellm":
        assert str(getattr(cfg, "LITELLM_GATEWAY_URL", "")).startswith(
            "http"
        ), "LITELLM_GATEWAY_URL http/https ile başlamalı."


@pytest.mark.asyncio
async def test_boot_fastapi_app_healthz_starts_with_mocked_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """FastAPI uygulamasının temel boot akışında çökmeden ayağa kalktığını doğrular."""
    web_server = pytest.importorskip("web_server")

    fake_agent = SimpleNamespace(
        cfg=SimpleNamespace(AI_PROVIDER="ollama"),
        health=SimpleNamespace(get_health_summary=lambda: {"status": "ok", "ollama_online": True}),
    )

    async def _fake_get_agent():
        return fake_agent

    close_redis = AsyncMock(return_value=None)
    shutdown_local_llm = AsyncMock(return_value=None)

    monkeypatch.setattr(web_server.Config, "validate_critical_settings", lambda: None)
    monkeypatch.setattr(web_server, "_reload_persisted_marketplace_plugins", lambda: None)
    monkeypatch.setattr(web_server, "_close_redis_client", close_redis)
    monkeypatch.setattr(web_server, "_async_force_shutdown_local_llm_processes", shutdown_local_llm)
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    try:
        async with web_server.app.router.lifespan_context(web_server.app):
            async with AsyncClient(transport=ASGITransport(app=web_server.app), base_url="http://test") as client:
                response = await client.get("/healthz")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert "uptime_seconds" in payload
        assert close_redis.await_count == 1
        assert shutdown_local_llm.await_count == 1
    finally:
        web_server.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_boot_health_probes_bypass_ddos_redis_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Health probe endpoint'leri DDOS Redis rate-limit kontrolünü tetiklememelidir."""
    web_server = pytest.importorskip("web_server")

    fake_agent = SimpleNamespace(
        cfg=SimpleNamespace(AI_PROVIDER="ollama"),
        health=SimpleNamespace(get_health_summary=lambda: {"status": "ok", "ollama_online": True}),
    )

    async def _fake_get_agent():
        return fake_agent

    redis_rate_limiter = AsyncMock(return_value=False)

    monkeypatch.setattr(web_server.Config, "validate_critical_settings", lambda: None)
    monkeypatch.setattr(web_server, "_reload_persisted_marketplace_plugins", lambda: None)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", redis_rate_limiter)
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    try:
        async with web_server.app.router.lifespan_context(web_server.app):
            async with AsyncClient(transport=ASGITransport(app=web_server.app), base_url="http://test") as client:
                healthz = await client.get("/healthz")

        assert healthz.status_code == 200
        assert redis_rate_limiter.await_count == 0
        ddos_source = inspect.getsource(web_server.ddos_rate_limit_middleware)
        assert "/readyz" in ddos_source
    finally:
        web_server.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_boot_real_lifespan_uses_actual_config_validation() -> None:
    """Mock'suz boot: gerçek Config doğrulamasıyla lifespan açılıp kapanabilmelidir."""
    web_server = pytest.importorskip("web_server")

    async with web_server.app.router.lifespan_context(web_server.app):
        assert web_server._agent_lock is not None
        assert web_server._redis_lock is not None
        assert web_server._local_rate_lock is not None


@pytest.mark.asyncio
async def test_boot_postgresql_connection_select_1() -> None:
    """Boot sırasında PostgreSQL erişiminin temel sorguyla doğrulandığını garanti eder."""
    if _is_external_infra_checks_disabled():
        pytest.skip("Harici altyapı smoke testleri SMOKE_SKIP_EXTERNAL_INFRA=1 ile kapatıldı.")

    asyncpg = pytest.importorskip("asyncpg", reason="PostgreSQL smoke testi için asyncpg gereklidir.")

    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sidar")
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    conn = await asyncpg.connect(dsn=database_url, timeout=3)
    try:
        result = await conn.fetchval("SELECT 1")
    finally:
        await conn.close()

    assert result == 1


@pytest.mark.asyncio
async def test_boot_redis_ping() -> None:
    """Boot sırasında Redis erişiminin ping ile doğrulandığını garanti eder."""
    if _is_external_infra_checks_disabled():
        pytest.skip("Harici altyapı smoke testleri SMOKE_SKIP_EXTERNAL_INFRA=1 ile kapatıldı.")

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True, socket_connect_timeout=3)
    try:
        try:
            is_alive = await client.ping()
        except RedisConnectionError as exc:
            pytest.skip(f"Redis smoke testi atlandı: erişim yok ({exc})")
    finally:
        await client.aclose()

    assert is_alive is True
