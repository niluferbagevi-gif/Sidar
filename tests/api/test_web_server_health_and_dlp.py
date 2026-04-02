from __future__ import annotations

import ast
from pathlib import Path


WEB_SERVER_PATH = Path(__file__).resolve().parents[2] / "web_server.py"


def _parse_tree() -> ast.Module:
    return ast.parse(WEB_SERVER_PATH.read_text(encoding="utf-8"))


def test_mask_collaboration_helper_exists_and_uses_mask_pii_import():
    tree = _parse_tree()

    mask_fn = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_mask_collaboration_text"
    )
    fn_source = ast.get_source_segment(WEB_SERVER_PATH.read_text(encoding="utf-8"), mask_fn) or ""

    assert "from core.dlp import mask_pii" in fn_source
    assert "return _mask_pii" in fn_source


def test_healthz_and_readyz_routes_delegate_to_health_response_with_expected_flags():
    tree = _parse_tree()
    source = WEB_SERVER_PATH.read_text(encoding="utf-8")

    health_fn = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "health_check")
    ready_fn = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "readiness_check")

    health_source = ast.get_source_segment(source, health_fn) or ""
    ready_source = ast.get_source_segment(source, ready_fn) or ""

    assert "require_dependencies=False" in health_source
    assert "require_dependencies=True" in ready_source
