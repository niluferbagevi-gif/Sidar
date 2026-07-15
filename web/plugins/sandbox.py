"""Plugin source validation and in-process sandbox policy helpers.

The validator is defense-in-depth only. Production deployments should avoid
in-process plugin source execution unless explicitly enabled by an operator.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

PLUGIN_BANNED_BUILTINS: frozenset[str] = frozenset(
    {
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "globals",
        "input",
        "locals",
        "open",
        "vars",
    }
)
PLUGIN_SAFE_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "agent",
        "collections",
        "dataclasses",
        "datetime",
        "enum",
        "fastapi",
        "math",
        "typing",
        "web_server",
    }
)
PLUGIN_SAFE_WEB_SERVER_FROM_IMPORTS: frozenset[str] = frozenset({"BaseAgent"})
PLUGIN_SAFE_FASTAPI_FROM_IMPORTS: frozenset[str] = frozenset({"HTTPException"})


def plugin_source_filename(module_label: str) -> str:
    """Return a synthetic filename for plugin compile errors."""
    safe_label = "".join(
        ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in module_label
    )
    return f"<sidar-plugin:{safe_label or 'inline'}>"


def in_process_plugin_execution_allowed(env: Mapping[str, str] | None = None) -> bool:
    """Return whether in-process plugin source execution is allowed.

    Development/test deployments keep the legacy behavior. Production deployments
    fail closed unless an operator explicitly sets ``SIDAR_ENABLE_IN_PROCESS_PLUGINS=1``.
    """
    environ = os.environ if env is None else env
    explicit = str(environ.get("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "")).strip().lower()
    if explicit in {"1", "true", "yes", "on"}:
        return True
    if explicit in {"0", "false", "no", "off"}:
        return False
    sidar_env = str(environ.get("SIDAR_ENV", "development")).strip().lower()
    return sidar_env not in {"prod", "production"}


def validate_plugin_source(source_code: str) -> None:
    """Validate plugin source before any in-process execution is attempted."""
    try:
        tree = ast.parse(source_code, mode="exec")
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"Plugin söz dizimi hatası: {exc}") from exc

    banned_calls = {
        "exec",
        "eval",
        "compile",
        "__import__",
        "open",
        "input",
        "getattr",
        "setattr",
        "delattr",
    }
    banned_import_roots = {"os", "subprocess", "socket", "ctypes", "multiprocessing"}
    banned_attribute_roots = banned_import_roots | {"builtins", "importlib", "pathlib", "shutil"}
    banned_introspection_attrs = {
        "__base__",
        "__bases__",
        "__class__",
        "__closure__",
        "__code__",
        "__dict__",
        "__getattribute__",
        "__globals__",
        "__mro__",
        "__subclasses__",
    }

    def _attribute_root_name(expr: ast.AST) -> str:
        """Return the left-most name in a chained attribute expression, if any."""
        current = expr
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name):
            return current.id
        if isinstance(current, ast.Call):
            return _attribute_root_name(current.func)
        if isinstance(current, ast.Subscript):
            return _attribute_root_name(current.value)
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            else:
                modules = [(node.module or "").split(".")[0]]
            if any(mod in banned_import_roots for mod in modules if mod):
                raise HTTPException(
                    status_code=400,
                    detail="Plugin güvenlik politikası: tehlikeli modül import'u engellendi.",
                )
        if isinstance(node, ast.Attribute) and node.attr in banned_introspection_attrs:
            raise HTTPException(
                status_code=400,
                detail="Plugin güvenlik politikası: tehlikeli introspection erişimi engellendi.",
            )
        if isinstance(node, ast.Call):
            fn_name = ""
            if isinstance(node.func, ast.Name):
                fn_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                root_name = _attribute_root_name(node.func)
                fn_name = f"{root_name}.{node.func.attr}" if root_name else node.func.attr
            if fn_name in banned_calls or fn_name.endswith(".exec") or fn_name.endswith(".eval"):
                raise HTTPException(
                    status_code=400,
                    detail="Plugin güvenlik politikası: dinamik kod çalıştırma çağrısı engellendi.",
                )
            if (
                isinstance(node.func, ast.Attribute)
                and _attribute_root_name(node.func) in banned_attribute_roots
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Plugin güvenlik politikası: tehlikeli modül çağrısı engellendi.",
                )


def execute_validated_plugin_source(
    source_code: str, module_label: str, namespace: dict[str, Any]
) -> None:
    """Compile and execute already-validated plugin source in the provided namespace."""
    code = compile(source_code, plugin_source_filename(module_label), "exec")
    exec(code, namespace)  # nosec B102


def assert_in_process_plugin_execution_allowed() -> None:
    """Fail closed for production unless an operator explicitly enables legacy exec."""
    if not in_process_plugin_execution_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                "Plugin kaynak kodunun process-içi çalıştırılması production ortamında kapalı. "
                "İzole container/process sandbox entegrasyonu kullanılmalı veya risk kabulüyle "
                "SIDAR_ENABLE_IN_PROCESS_PLUGINS=1 açıkça verilmelidir."
            ),
        )
