from __future__ import annotations

import pytest
from fastapi import HTTPException

from sidar_version import PRODUCT_VERSION
from web.app_factory import (
    _expose_api_docs,
    _expose_exception_details,
    _noop_lifespan,
    create_app,
    get_runtime_state,
    initialize_runtime_state,
    register_exception_handlers,
)


@pytest.mark.asyncio
async def test_noop_lifespan_async_context_manager_yields_none() -> None:
    app = create_app(register_handlers=False)

    async with _noop_lifespan(app) as yielded:
        assert yielded is None


def test_expose_exception_details_follows_environment(monkeypatch) -> None:
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    assert _expose_exception_details() is True

    monkeypatch.setenv("SIDAR_ENV", "development")
    assert _expose_exception_details() is True

    monkeypatch.setenv("SIDAR_ENV", " production ")
    assert _expose_exception_details() is False


def test_expose_api_docs_follows_environment(monkeypatch) -> None:
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    assert _expose_api_docs() is True

    monkeypatch.setenv("SIDAR_ENV", "development")
    assert _expose_api_docs() is True

    monkeypatch.setenv("SIDAR_ENV", " production ")
    assert _expose_api_docs() is False


def test_create_app_disables_api_documentation_routes_in_production(
    monkeypatch, make_test_client
) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")
    app = create_app()
    client = make_test_client(app)

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_create_app_keeps_api_documentation_routes_outside_production(
    monkeypatch, make_test_client
) -> None:
    monkeypatch.setenv("SIDAR_ENV", "development")
    app = create_app()
    client = make_test_client(app)

    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_create_app_allows_explicit_api_documentation_override(monkeypatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")

    app = create_app(expose_api_docs=True)

    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"


def test_create_app_registers_metadata_and_json_http_exception_handler(make_test_client) -> None:
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise HTTPException(status_code=418, detail={"error": "teapot", "code": "E_TEAPOT"})

    response = make_test_client(app, raise_server_exceptions=False).get("/boom")

    assert app.title == "Sidar Web UI & REST API"
    assert app.version == PRODUCT_VERSION
    assert response.status_code == 418
    assert response.json() == {"success": False, "error": "teapot", "code": "E_TEAPOT"}


def test_create_app_json_http_exception_handler_handles_string_detail(make_test_client) -> None:
    app = create_app()

    @app.get("/plain-boom")
    async def plain_boom() -> None:
        raise HTTPException(status_code=400, detail="plain error")

    response = make_test_client(app, raise_server_exceptions=False).get("/plain-boom")

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "plain error"}


def test_create_app_allows_central_version_override() -> None:
    app = create_app(version="9.8.7")

    assert app.version == "9.8.7"


def test_create_app_attaches_isolated_runtime_state() -> None:
    first = create_app()
    second = create_app()

    first_state = get_runtime_state(first)
    second_state = get_runtime_state(second)

    assert first_state is first.state.sidar_runtime
    assert second_state is second.state.sidar_runtime
    assert first_state is not second_state
    assert first_state.agent is None
    assert first_state.agent_lock is None


def test_initialize_runtime_state_preserves_existing_values_and_applies_overrides() -> None:
    app = create_app()
    state = initialize_runtime_state(app, agent="agent-1")

    same_state = initialize_runtime_state(app, redis_lock="redis-lock")

    assert same_state is state
    assert state.agent == "agent-1"
    assert state.redis_lock == "redis-lock"
    assert hasattr(state, "rag_prewarm_task")


def test_create_app_hides_unhandled_exception_detail_in_production(
    monkeypatch, make_test_client
) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")
    app = create_app()

    @app.get("/secret-boom")
    async def secret_boom() -> None:
        raise RuntimeError("dsn=postgresql://sidar:secret@example/internal")

    response = make_test_client(app, raise_server_exceptions=False).get("/secret-boom")

    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "İç sunucu hatası"}


def test_create_app_keeps_unhandled_exception_detail_in_development(
    monkeypatch, make_test_client
) -> None:
    monkeypatch.setenv("SIDAR_ENV", "development")
    app = create_app()

    @app.get("/debug-boom")
    async def debug_boom() -> None:
        raise RuntimeError("debug detail")

    response = make_test_client(app, raise_server_exceptions=False).get("/debug-boom")

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "error": "İç sunucu hatası",
        "detail": "debug detail",
    }


def test_register_exception_handlers_is_noop_without_exception_handler() -> None:
    class NoExceptionHandler:
        pass

    register_exception_handlers(NoExceptionHandler())  # type: ignore[arg-type]


def test_register_routers_includes_routes_and_collects_legacy_exports(make_test_client) -> None:
    from fastapi import APIRouter

    from web.app_factory import register_routers

    app = create_app()
    router = APIRouter()

    @router.get("/factory-ping")
    async def factory_ping() -> dict[str, bool]:
        return {"ok": True}

    router.legacy_exports = {"factory_ping": factory_ping}  # type: ignore[attr-defined]
    router_without_exports = APIRouter()

    @router_without_exports.get("/factory-pong")
    async def factory_pong() -> dict[str, bool]:
        return {"ok": True}

    router_without_exports.legacy_exports = ["not", "a", "dict"]  # type: ignore[attr-defined]

    exports = register_routers(app, [router, router_without_exports])
    response = make_test_client(app).get("/factory-ping")

    assert response.json() == {"ok": True}
    assert exports == {"factory_ping": factory_ping}
