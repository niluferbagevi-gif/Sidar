import pytest
from fastapi.routing import APIRoute

from web_server import app


@pytest.mark.integration
def test_frontend_api_calls_are_declared_by_web_server_routes() -> None:
    declared_routes = {
        (method.upper(), route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    }

    frontend_calls = {
        ("POST", "/auth/login"),
        ("POST", "/auth/register"),
        ("POST", "/admin/prompts"),
        ("POST", "/admin/prompts/activate"),
        ("POST", "/api/agents/register-file"),
    }

    missing_routes = frontend_calls - declared_routes
    assert not missing_routes, (
        "Şu API route'ları web_server.py içinde bulunamadı veya eşleşmiyor: "
        f"{missing_routes}"
    )
