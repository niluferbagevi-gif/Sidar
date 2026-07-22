"""Plugin source validation and in-process sandbox policy helpers.

The validator is defense-in-depth only. Production deployments should avoid
in-process plugin source execution unless explicitly enabled by an operator.
"""

from __future__ import annotations

import ast
import builtins
import os
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException

from agent.base_agent import BaseAgent

# The runtime __builtins__/__import__ gate below (restricted_plugin_import,
# build_restricted_plugin_builtins) used to have a second, independently
# maintained copy of these allowlists in web_server.py, with values that had
# drifted apart (e.g. this module's PLUGIN_SAFE_IMPORT_ROOTS additionally
# allowed "datetime"/"enum" but was never actually wired into the exec path).
# These constants are now the single enforced source; web_server.py aliases
# them instead of keeping its own copy. PLUGIN_SAFE_IMPORT_ROOTS intentionally
# stays at the narrower, already-enforced set rather than the wider one that
# was dead code, so consolidating here does not silently widen the sandbox.
PLUGIN_BANNED_BUILTINS: frozenset[str] = frozenset(
    {
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "globals",
        "input",
        "locals",
        "memoryview",
        "open",
        "vars",
    }
)
PLUGIN_SAFE_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "abc",
        "asyncio",
        "collections",
        "dataclasses",
        "math",
        "pydantic",
        "typing",
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


def restricted_plugin_import(
    name: str,
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    """Allowlist-based import gate for plugin code."""
    del globals, locals
    if level != 0:
        raise ImportError("Plugin güvenlik politikası: relative import engellendi.")
    module_name = str(name or "").strip()
    root = module_name.split(".", 1)[0]
    requested = tuple(str(item) for item in (fromlist or ()))

    if module_name == "web_server":
        if requested and any(item not in PLUGIN_SAFE_WEB_SERVER_FROM_IMPORTS for item in requested):
            raise ImportError("Plugin güvenlik politikası: web_server import kapsamı engellendi.")
        return SimpleNamespace(BaseAgent=BaseAgent)

    if module_name == "fastapi":
        if requested and any(item not in PLUGIN_SAFE_FASTAPI_FROM_IMPORTS for item in requested):
            raise ImportError("Plugin güvenlik politikası: fastapi import kapsamı engellendi.")
        return SimpleNamespace(HTTPException=HTTPException)

    if module_name == "agent.base_agent":
        if requested and any(item != "BaseAgent" for item in requested):
            raise ImportError(
                "Plugin güvenlik politikası: agent.base_agent import kapsamı engellendi."
            )
        return builtins.__import__(module_name, {}, {}, requested, 0)

    if root not in PLUGIN_SAFE_IMPORT_ROOTS:
        raise ImportError("Plugin güvenlik politikası: import allowlist dışında.")
    return builtins.__import__(module_name, {}, {}, requested, 0)


def build_restricted_plugin_builtins() -> dict[str, Any]:
    """Plugin exec'i için tehlikeli built-in'leri elenmiş bir __builtins__ haritası üretir.

    AST doğrulayıcı statik olarak `exec`, `eval`, `compile`, `__import__`, `open`, `input`
    çağrılarını engeller; bu fonksiyon ise runtime'da bu sembolleri tamamen erişilmez
    kılarak defense-in-depth sağlar. `from ... import ...` deyiminin çalışabilmesi için
    sadece güvenli modülleri döndüren allowlist tabanlı `__import__` kullanılır.
    """
    safe: dict[str, Any] = {}
    for name in dir(builtins):
        if name in PLUGIN_BANNED_BUILTINS:
            continue
        safe[name] = getattr(builtins, name)
    safe["__import__"] = restricted_plugin_import
    return safe


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
