"""Plugin source validation and in-process sandbox policy helpers.

The validator is defense-in-depth only. Production deployments should avoid
in-process plugin source execution unless explicitly enabled by an operator.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import json
import os
import shutil
import subprocess  # nosec B404 -- fixed-argument Docker client invocation
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException

from agent.base_agent import BaseAgent
from managers.code.docker import (
    DOCKER_CPUS_RE,
    DOCKER_MEMORY_RE,
    sanitize_docker_image,
    sanitize_docker_token,
)

PLUGIN_RPC_VERSION = "1"
PLUGIN_RPC_MAX_RESPONSE_BYTES = 1_048_576


class PluginSandboxError(RuntimeError):
    """Raised when the isolated plugin worker cannot return a trusted response."""


def plugin_sandbox_backend(env: Mapping[str, str] | None = None) -> str:
    """Resolve the plugin backend, defaulting production to the isolated worker."""
    environ = os.environ if env is None else env
    configured = str(environ.get("SIDAR_PLUGIN_SANDBOX_BACKEND", "")).strip().lower()
    if configured:
        if configured not in {"docker", "in_process"}:
            raise PluginSandboxError("Desteklenmeyen plugin sandbox backend'i.")
        return configured
    sidar_env = str(environ.get("SIDAR_ENV", "development")).strip().lower()
    return "docker" if sidar_env in {"prod", "production"} else "in_process"


class DockerPluginSandboxBackend:
    """Run versioned plugin RPC requests in a disposable, locked-down container."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        environ = os.environ if env is None else env
        self.image = sanitize_docker_image(
            environ.get("SIDAR_PLUGIN_SANDBOX_IMAGE", "sidar:latest")
        )
        self.timeout = max(1, int(environ.get("SIDAR_PLUGIN_SANDBOX_TIMEOUT", "10")))
        self.memory = sanitize_docker_token(
            environ.get("SIDAR_PLUGIN_SANDBOX_MEMORY", "256m"),
            pattern=DOCKER_MEMORY_RE,
            default="256m",
            kind="plugin memory",
        )
        self.cpus = sanitize_docker_token(
            environ.get("SIDAR_PLUGIN_SANDBOX_CPUS", "0.5"),
            pattern=DOCKER_CPUS_RE,
            default="0.5",
            kind="plugin cpu",
        )
        self.pids = max(1, int(environ.get("SIDAR_PLUGIN_SANDBOX_PIDS", "64")))

    def _command(self) -> list[str]:
        docker = shutil.which("docker")
        if not docker:
            raise PluginSandboxError("Docker bulunamadı; plugin sandbox fail-closed reddedildi.")
        # No source, prompt, host path or environment value is placed on the command line.
        return [
            docker,
            "run",
            "--rm",
            "--interactive",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            f"--pids-limit={self.pids}",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m",
            self.image,
            "python",
            "-m",
            "web.plugins.worker",
        ]

    def request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send one RPC envelope and validate the worker's bounded response."""
        envelope = {"rpc_version": PLUGIN_RPC_VERSION, **dict(payload)}
        try:
            completed = subprocess.run(  # nosec B603
                self._command(),
                input=json.dumps(envelope),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                env={"PATH": os.environ.get("PATH", "")},
            )
        except subprocess.TimeoutExpired as exc:
            raise PluginSandboxError("Plugin worker zaman aşımına uğradı.") from exc
        if completed.returncode != 0:
            raise PluginSandboxError("Plugin worker güvenli biçimde tamamlanamadı.")
        encoded = completed.stdout.encode("utf-8", errors="replace")
        if len(encoded) > PLUGIN_RPC_MAX_RESPONSE_BYTES:
            raise PluginSandboxError("Plugin worker yanıt limiti aşıldı.")
        try:
            response = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PluginSandboxError("Plugin worker geçersiz RPC yanıtı döndürdü.") from exc
        if not isinstance(response, dict) or response.get("rpc_version") != PLUGIN_RPC_VERSION:
            raise PluginSandboxError("Plugin worker RPC sürümü doğrulanamadı.")
        if response.get("ok") is not True:
            # Worker exceptions can contain source/prompt fragments; never relay them to
            # the host API or logs.
            raise PluginSandboxError("Plugin worker isteği güvenlik politikasıyla reddedildi.")
        return response

    def describe(
        self, source_code: str, class_name: str | None, module_label: str
    ) -> dict[str, Any]:
        """Validate a plugin and return safe class metadata without host import."""
        return self.request(
            {
                "action": "describe",
                "source": source_code,
                "class_name": class_name,
                "module_label": module_label,
            }
        )

    async def run_task(
        self, source_code: str, class_name: str, module_label: str, task_prompt: str
    ) -> str:
        """Execute a plugin task without blocking the host event loop."""
        response = await asyncio.to_thread(
            self.request,
            {
                "action": "run_task",
                "source": source_code,
                "class_name": class_name,
                "module_label": module_label,
                "task_prompt": task_prompt,
            },
        )
        return str(response.get("result", ""))


def build_isolated_plugin_proxy(
    source_code: str, class_name: str | None, module_label: str
) -> type[BaseAgent]:
    """Create a host-safe BaseAgent proxy after container-side validation."""
    backend = DockerPluginSandboxBackend()
    metadata = backend.describe(source_code, class_name, module_label)
    resolved_name = str(metadata.get("class_name") or "").strip()
    if not resolved_name:
        raise PluginSandboxError("Plugin worker sınıf metadata'sı döndürmedi.")

    async def run_task(self: BaseAgent, task_prompt: str) -> str:
        return await backend.run_task(source_code, resolved_name, module_label, task_prompt)

    return type(
        resolved_name,
        (BaseAgent,),
        {
            "__doc__": str(metadata.get("description") or "Isolated plugin agent proxy."),
            "__module__": "web.plugins.sandbox",
            "run_task": run_task,
        },
    )


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
    always fail closed: an environment variable must not turn a known lack of OS-level
    isolation into a runtime security-boundary bypass.
    """
    environ = os.environ if env is None else env
    sidar_env = str(environ.get("SIDAR_ENV", "development")).strip().lower()
    if sidar_env in {"prod", "production"}:
        return False
    explicit = str(environ.get("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "")).strip().lower()
    if explicit in {"1", "true", "yes", "on"}:
        return True
    if explicit in {"0", "false", "no", "off"}:
        return False
    return True


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


def run_plugin_source_in_process(
    source_code: str,
    module_label: str,
    *,
    validator: Callable[[str], None] = validate_plugin_source,
) -> dict[str, Any]:
    """Run a validated plugin through the explicitly legacy in-process backend.

    Keeping this backend behind one function makes the remaining isolation boundary
    explicit and gives a future Docker/process RPC backend a single replacement seam.
    Production remains fail-closed and can never select this backend.
    """
    try:
        validator(source_code)
        assert_in_process_plugin_execution_allowed()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Plugin kaynağı doğrulanamadı: {exc}") from exc

    namespace: dict[str, Any] = {
        "__name__": module_label,
        "__builtins__": build_restricted_plugin_builtins(),
    }
    try:
        execute_validated_plugin_source(source_code, module_label, namespace)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Plugin kodu derlenemedi/çalıştırılamadı: {exc}"
        ) from exc
    return namespace


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
    """Fail closed whenever the deployment policy disallows legacy in-process exec."""
    if not in_process_plugin_execution_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                "Plugin kaynak kodunun process-içi çalıştırılması deployment politikası "
                "tarafından kapalı. Production koruması ortam değişkeniyle aşılamaz; izole "
                "container/process sandbox entegrasyonu kullanılmalıdır."
            ),
        )
