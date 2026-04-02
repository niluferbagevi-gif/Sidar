from pathlib import Path

from core.rag import GraphIndex


def test_python_import_candidates_resolve_local_module(tmp_path: Path) -> None:
    root = tmp_path
    pkg = root / "pkg"
    pkg.mkdir()
    current = pkg / "service.py"
    current.write_text("# service", encoding="utf-8")
    module = pkg / "utils.py"
    module.write_text("# utils", encoding="utf-8")

    candidates = GraphIndex._python_import_candidates(current, "utils", 0, root)

    assert module.resolve() in candidates


def test_script_import_candidates_support_index_files(tmp_path: Path) -> None:
    root = tmp_path
    src = root / "src"
    src.mkdir()
    current = src / "main.js"
    current.write_text("", encoding="utf-8")
    feature_dir = src / "feature"
    feature_dir.mkdir()
    index_file = feature_dir / "index.ts"
    index_file.write_text("export const ok = true", encoding="utf-8")

    candidates = GraphIndex._script_import_candidates(current, "./feature", root)

    assert index_file.resolve() in candidates


def test_extract_dependencies_on_js_file_returns_deps_and_endpoint_calls(tmp_path: Path) -> None:
    graph = GraphIndex(tmp_path)
    app_js = tmp_path / "app.js"
    (tmp_path / "api.js").write_text("export default {}", encoding="utf-8")
    content = """
import './api'
fetch('/api/health')
new WebSocket('/ws/updates')
"""

    deps, endpoint_defs, endpoint_calls = graph._extract_dependencies(app_js, content)

    assert any(path.name == "api.js" for path in deps)
    assert endpoint_defs == []
    assert {item["endpoint_id"] for item in endpoint_calls} == {
        "endpoint:GET /api/health",
        "endpoint:WS /ws/updates",
    }
