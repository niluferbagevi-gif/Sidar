"""Plugin source validation and isolated sandbox policy helpers.

The validator is defense-in-depth only. Docker is the default in every
environment; the legacy in-process backend requires an explicit, non-production
operator opt-in.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import json
import os
import shutil
import subprocess  # nosec B404
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

# B404 review: subprocess is limited to the fixed-argument Docker client invocation below.

PLUGIN_RPC_VERSION = "1"
PLUGIN_RPC_MAX_RESPONSE_BYTES = 1_048_576


class PluginSandboxError(RuntimeError):
    """Raised when the isolated plugin worker cannot return a trusted response."""


def plugin_sandbox_backend(env: Mapping[str, str] | None = None) -> str:
    """Resolve the plugin backend, defaulting every environment to Docker."""
    environ = os.environ if env is None else env
    configured = str(environ.get("SIDAR_PLUGIN_SANDBOX_BACKEND", "")).strip().lower()
    if configured:
        if configured not in {"docker", "in_process"}:
            raise PluginSandboxError("Desteklenmeyen plugin sandbox backend'i.")
        if configured == "in_process" and not in_process_plugin_execution_allowed(environ):
            raise PluginSandboxError(
                "Legacy process-içi plugin backend'i yalnız açık "
                "SIDAR_ENABLE_IN_PROCESS_PLUGINS=1 opt-in'i ile kullanılabilir."
            )
        return configured
    return "docker"


class DockerPluginSandboxBackend:
    """Run versioned plugin RPC requests in a disposable, locked-down container."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        environ = os.environ if env is None else env
        self.image = sanitize_docker_image(
            environ.get("SIDAR_PLUGIN_SANDBOX_IMAGE", "sidar:latest")
        )
        self.timeout = max(1, int(environ.get("SIDAR_PLUGIN_SANDBOX_TIMEOUT", "10")))
        # 256m (this project's default elsewhere for lighter CLI/SDK code-exec
        # sandboxes -- managers/code/docker.py, managers/code_manager.py) was
        # never actually enough here: describe() (imports the full
        # agent.base_agent chain -- config/LLM client/RAG deps -- but never
        # instantiates BaseAgent) fits, but run_task() additionally
        # constructs a real BaseAgent (Config() + LLMClient(...)) inside the
        # container and the process died with a non-zero exit -- no timeout,
        # no malformed JSON, the signature of an OOM kill -- once this test
        # group's first real end-to-end run finally exercised that path.
        # 512m gives that construction headroom without loosening any other
        # isolation flag.
        self.memory = sanitize_docker_token(
            environ.get("SIDAR_PLUGIN_SANDBOX_MEMORY", "512m"),
            pattern=DOCKER_MEMORY_RE,
            default="512m",
            kind="plugin memory",
        )
        self.cpus = sanitize_docker_token(
            environ.get("SIDAR_PLUGIN_SANDBOX_CPUS", "0.5"),
            pattern=DOCKER_CPUS_RE,
            default="0.5",
            kind="plugin cpu",
        )
        # Widened alongside the memory bump: the same real BaseAgent
        # construction may spin up thread pools (BLAS/OpenMP workers in the
        # ML dependency stack) that a lightweight describe()-only call never
        # touches; 64 was sized for the latter.
        self.pids = max(1, int(environ.get("SIDAR_PLUGIN_SANDBOX_PIDS", "128")))

    def _isolation_argv(self) -> list[str]:
        """Return the ``docker run`` isolation flags shared by every invocation.

        Kept separate from the worker entrypoint so tests can reuse the exact
        production isolation contract (network/fs/user/resource limits) against
        arbitrary in-container commands instead of maintaining a second,
        independently-drifting copy of these security-critical flags.
        """
        docker = shutil.which("docker")
        if not docker:
            raise PluginSandboxError("Docker bulunamadı; plugin sandbox fail-closed reddedildi.")
        # No source, prompt, host path, secret or other host-derived value is
        # placed on the command line -- the two -e flags below are fixed,
        # non-secret isolation-contract constants (see their own comment),
        # not host environment values being forwarded.
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
            # Pin memory-swap to the same value as --memory so the container cannot
            # double its effective ceiling via swap before the OOM killer engages;
            # Docker otherwise defaults memory-swap to 2x --memory when swap is
            # available on the host.
            f"--memory-swap={self.memory}",
            f"--cpus={self.cpus}",
            f"--pids-limit={self.pids}",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m",
            # Pin the unprivileged-port floor explicitly instead of trusting the
            # host's ambient net.ipv4.ip_unprivileged_port_start default. This
            # sysctl is namespaced per network namespace but a *new* namespace
            # (which --network=none still creates -- only its interfaces are
            # empty) inherits whatever value the host currently has, not a
            # fixed 1024. SEC-PLUGIN-001's container-escape matrix
            # (test_plugin_sandbox_container_escape.py) caught this in CI:
            # some hosts/runner images lower this sysctl (e.g. to 0) for their
            # own service needs, which silently lets --user=65534:65534 +
            # --cap-drop=ALL bind privileged ports (<1024) with no capability
            # required -- --cap-drop/--security-opt cannot affect this sysctl,
            # only an explicit --sysctl can. Reproduced and verified with
            # `unshare --net` + `setpriv` at ip_unprivileged_port_start=0
            # (bind succeeds) vs. the standard 1024 (bind is rejected).
            "--sysctl=net.ipv4.ip_unprivileged_port_start=1024",
            # web/plugins/worker.py (running inside this container) executes
            # plugin source via run_plugin_source_in_process(), which is the
            # same helper the *host's* legacy in-process backend uses and is
            # gated by assert_in_process_plugin_execution_allowed() -- fail
            # closed unless SIDAR_ENABLE_IN_PROCESS_PLUGINS=1 is set (and
            # SIDAR_ENV isn't production). That gate exists to stop the
            # *unsandboxed host process* from ever falling back to running
            # untrusted plugin code directly; it was never meant to also
            # block the worker executing inside this already-isolated,
            # network-none/cap-dropped/non-root container -- the container
            # boundary itself is what makes running "in-process" here safe.
            # Without these, every real Docker-backed RPC call fails closed
            # with a generic "rejected by security policy" (SEC-PLUGIN-001's
            # container-integration test caught this: the plugin sandbox had
            # never actually executed a single real request end-to-end
            # before this test finally ran against a real image). Scoped to
            # only this container's environment via -e, never the host's.
            "-e",
            "SIDAR_ENABLE_IN_PROCESS_PLUGINS=1",
            "-e",
            "SIDAR_ENV=development",
            # The image's own ENTRYPOINT is the Sidar launcher (`python main.py`);
            # without this override, trailing argv (e.g. "-m web.plugins.worker")
            # is appended as *arguments to main.py* instead of replacing the
            # command, so the RPC worker never actually runs. Fixing the
            # entrypoint to the interpreter mirrors the already-correct
            # `managers/code/docker.py` CLI sandbox fallback.
            "--entrypoint=python",
        ]

    def _command(self) -> list[str]:
        return [*self._isolation_argv(), self.image, "-m", "web.plugins.worker"]

    def container_command(self, *args: str) -> list[str]:
        """Build the production isolation argv (python entrypoint) with caller args.

        Exposed for integration tests that need to run arbitrary in-container
        probes (escape attempts) under the exact same isolation flags the RPC
        worker runs under, rather than re-deriving them. Callers pass the
        arguments to ``python`` (e.g. ``"-c", script``), not "python" itself --
        the entrypoint is already fixed to the interpreter.
        """
        if not args:
            raise ValueError("args boş olamaz.")
        return [*self._isolation_argv(), self.image, *args]

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

    Development/test deployments require an explicit legacy opt-in. Production
    deployments always fail closed: an environment variable must not turn a known
    lack of OS-level isolation into a runtime security-boundary bypass.
    """
    environ = os.environ if env is None else env
    sidar_env = str(environ.get("SIDAR_ENV", "development")).strip().lower()
    if sidar_env in {"prod", "production"}:
        return False
    explicit = str(environ.get("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "")).strip().lower()
    return explicit in {"1", "true", "yes", "on"}


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
                "tarafından kapalı. Legacy geliştirme/test kullanımı açık opt-in gerektirir; "
                "production koruması ortam değişkeniyle aşılamaz. İzole container/process "
                "sandbox entegrasyonu kullanılmalıdır."
            ),
        )
