from pathlib import Path
import re

import pytest


_ROUTE_RE = re.compile(r'@app\.(get|post|put|delete|patch)\(\s*"([^"]+)"')


@pytest.mark.integration
def test_frontend_api_calls_are_declared_by_web_server_routes() -> None:
    server_source = Path("web_server.py").read_text(encoding="utf-8")
    declared_routes = {(method.upper(), path) for method, path in _ROUTE_RE.findall(server_source)}

    frontend_calls = {
        ("POST", "/auth/login"),
        ("POST", "/auth/register"),
        ("POST", "/admin/prompts"),
        ("POST", "/admin/prompts/activate"),
        ("POST", "/api/agents/register-file"),
    }

    assert frontend_calls.issubset(declared_routes)
