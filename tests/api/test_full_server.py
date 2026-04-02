from __future__ import annotations

import ast
from pathlib import Path


WEB_SERVER_PATH = Path(__file__).resolve().parents[2] / "web_server.py"


def _parse_web_server_ast() -> ast.Module:
    return ast.parse(WEB_SERVER_PATH.read_text(encoding="utf-8"))


def test_key_routes_are_declared_on_app() -> None:
    tree = _parse_web_server_ast()
    routes: set[tuple[str, str]] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
                continue
            if not isinstance(deco.func.value, ast.Name) or deco.func.value.id != "app":
                continue
            method = deco.func.attr.lower()
            if not deco.args or not isinstance(deco.args[0], ast.Constant):
                continue
            path = str(deco.args[0].value)
            routes.add((method, path))

    assert ("post", "/auth/login") in routes
    assert ("get", "/auth/me") in routes
    assert ("get", "/admin/stats") in routes
    assert ("post", "/api/swarm/execute") in routes


def test_collaboration_and_plugin_helpers_exist() -> None:
    tree = _parse_web_server_ast()
    names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assert "_normalize_room_id" in names
    assert "_collaboration_write_scopes_for_role" in names
    assert "_collaboration_command_requires_write" in names
    assert "_sanitize_capabilities" in names
    assert "_plugin_source_filename" in names
