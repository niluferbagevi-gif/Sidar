"""Contract tests for built-in role registry/import/capability consistency."""

from __future__ import annotations

import ast
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _extract_builtin_import_modules() -> set[str]:
    init_path = _repo_root() / "agent" / "roles" / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 1:
            modules.add(f"agent.roles.{node.module}")
    return modules


def _extract_registry_builtin_modules() -> set[str]:
    registry_path = _repo_root() / "agent" / "registry.py"
    tree = ast.parse(registry_path.read_text(encoding="utf-8"))
    modules: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_import_builtin_roles":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    if inner.value.startswith("agent.roles."):
                        modules.add(inner.value)
    return modules


def _extract_capabilities_from_role_file(role_file: Path) -> set[str]:
    tree = ast.parse(role_file.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr != "register":
                    continue
                for keyword in decorator.keywords:
                    if keyword.arg != "capabilities":
                        continue
                    if isinstance(keyword.value, ast.List):
                        values = {
                            elt.value
                            for elt in keyword.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        }
                        if values:
                            return values
    raise AssertionError(f"No AgentCatalog.register(capabilities=...) decorator found in {role_file}")


def test_builtin_role_import_lists_are_consistent() -> None:
    from_init = _extract_builtin_import_modules()
    from_registry = _extract_registry_builtin_modules()

    assert from_init == from_registry


def test_builtin_role_capabilities_match_expected_contract() -> None:
    root = _repo_root()
    expected = {
        "coder_agent.py": {"code_generation", "file_io", "shell_execution", "code_review"},
        "researcher_agent.py": {"web_search", "rag_search", "summarization"},
        "reviewer_agent.py": {"code_review", "security_audit", "quality_check"},
        "qa_agent.py": {"test_generation", "ci_remediation"},
        "coverage_agent.py": {"coverage_analysis", "pytest_output_analysis", "autonomous_test_generation"},
        "poyraz_agent.py": {"marketing_strategy", "seo_analysis", "campaign_copy", "audience_ops"},
    }

    role_dir = root / "agent" / "roles"
    for file_name, expected_caps in expected.items():
        observed = _extract_capabilities_from_role_file(role_dir / file_name)
        assert observed == expected_caps
