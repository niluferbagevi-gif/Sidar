"""Resolve the Sidar product version from static and dynamic pyproject metadata."""

from __future__ import annotations

import argparse
import ast
import tomllib
from pathlib import Path
from typing import Any

FALLBACK_VERSION = "0.0.0"


def _clean_version(value: object) -> str:
    return str(value or "").strip() or FALLBACK_VERSION


def _read_dynamic_version_file(project_root: Path, file_spec: object) -> str:
    file_paths = [file_spec] if isinstance(file_spec, str) else file_spec
    if not isinstance(file_paths, list):
        return FALLBACK_VERSION
    for raw_path in file_paths:
        if not isinstance(raw_path, str):
            continue
        version_file = project_root / raw_path
        try:
            for line in version_file.read_text(encoding="utf-8").splitlines():
                version = line.strip()
                if version:
                    return version
        except OSError:
            continue
    return FALLBACK_VERSION


def _module_path_for_attr(project_root: Path, module_name: str) -> Path | None:
    module_parts = module_name.split(".")
    module_file = project_root.joinpath(*module_parts).with_suffix(".py")
    if module_file.is_file():
        return module_file
    package_init = project_root.joinpath(*module_parts, "__init__.py")
    if package_init.is_file():
        return package_init
    return None


def _read_literal_attr(module_path: Path, attr_name: str) -> str:
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return FALLBACK_VERSION
    for node in tree.body:
        target_name = ""
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            target_name = target.id if isinstance(target, ast.Name) else ""
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target_name = node.target.id if isinstance(node.target, ast.Name) else ""
            value = node.value
        if target_name == attr_name and isinstance(value, ast.Constant):
            return _clean_version(value.value)
    return FALLBACK_VERSION


def _read_dynamic_version_attr(project_root: Path, attr_spec: object) -> str:
    if not isinstance(attr_spec, str):
        return FALLBACK_VERSION
    normalized_attr = attr_spec.replace(":", ".")
    module_name, separator, attr_name = normalized_attr.rpartition(".")
    if not separator or not module_name or not attr_name:
        return FALLBACK_VERSION
    module_path = _module_path_for_attr(project_root, module_name)
    if module_path is None:
        return FALLBACK_VERSION
    return _read_literal_attr(module_path, attr_name)


def _read_dynamic_version(project_root: Path, dynamic_spec: Any) -> str:
    if not isinstance(dynamic_spec, dict):
        return FALLBACK_VERSION
    version_spec = dynamic_spec.get("version", {})
    if not isinstance(version_spec, dict):
        return FALLBACK_VERSION
    if "file" in version_spec:
        version = _read_dynamic_version_file(project_root, version_spec["file"])
        if version != FALLBACK_VERSION:
            return version
    if "attr" in version_spec:
        return _read_dynamic_version_attr(project_root, version_spec["attr"])
    return FALLBACK_VERSION


def resolve_pyproject_version(pyproject_path: str | Path) -> str:
    """Resolve `[project].version` or supported setuptools dynamic version metadata."""

    pyproject = Path(pyproject_path)
    try:
        with pyproject.open("rb") as file_obj:
            pyproject_data = tomllib.load(file_obj)
    except (OSError, tomllib.TOMLDecodeError):
        return FALLBACK_VERSION

    project = pyproject_data.get("project", {})
    if not isinstance(project, dict):
        return FALLBACK_VERSION

    static_version = str(project.get("version", "")).strip()
    if static_version:
        return static_version

    dynamic_fields = project.get("dynamic", [])
    if not isinstance(dynamic_fields, list) or "version" not in dynamic_fields:
        return FALLBACK_VERSION

    tool = pyproject_data.get("tool", {})
    setuptools = tool.get("setuptools", {}) if isinstance(tool, dict) else {}
    dynamic_spec = setuptools.get("dynamic", {}) if isinstance(setuptools, dict) else {}
    return _read_dynamic_version(pyproject.parent, dynamic_spec)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", default="pyproject.toml", help="Path to pyproject.toml")
    args = parser.parse_args()
    print(resolve_pyproject_version(args.pyproject))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
