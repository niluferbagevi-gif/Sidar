from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient

from web.app_factory import create_app, register_exception_handlers


def test_create_app_registers_metadata_and_json_http_exception_handler() -> None:
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise HTTPException(status_code=418, detail={"error": "teapot", "code": "E_TEAPOT"})

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert app.title == "Sidar Web UI & REST API"
    assert response.status_code == 418
    assert response.json() == {"success": False, "error": "teapot", "code": "E_TEAPOT"}


def test_register_exception_handlers_is_noop_without_exception_handler() -> None:
    class NoExceptionHandler:
        pass

    register_exception_handlers(NoExceptionHandler())  # type: ignore[arg-type]
