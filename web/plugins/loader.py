"""Plugin agent loading, persistence and registration for the web API layer.

Extracted from ``web_server.py``. Collaborators that tests monkeypatch on
``web_server`` (the sandbox runner, ``BaseAgent``, ``AgentRegistry``, the class
loader) are injected by ``web_server``'s thin wrappers at call time, so those
patches keep taking effect.
"""

from __future__ import annotations

import inspect
import re
import secrets
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import HTTPException

from web.plugins import sandbox as plugin_sandbox

if TYPE_CHECKING:
    from agent.base_agent import BaseAgent

PLUGIN_ROLE_RE = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")


def validate_plugin_role_name(role_name: str) -> str:
    """Normalize a plugin role name and reject anything outside ``PLUGIN_ROLE_RE``."""
    normalized = (role_name or "").strip().lower()
    if not PLUGIN_ROLE_RE.match(normalized):
        raise HTTPException(status_code=400, detail="Geçersiz role_name")
    return normalized


def sanitize_capabilities(capabilities: list[str] | None) -> list[str]:
    """Drop blank capability names and strip surrounding whitespace."""
    if not capabilities:
        return []
    return [c.strip() for c in capabilities if str(c).strip()]


def load_plugin_agent_class(
    source_code: str,
    class_name: str | None,
    module_label: str,
    *,
    run_in_sandbox: Callable[[str, str], dict[str, Any]],
    fallback_base: Any,
) -> type[BaseAgent]:
    """Run plugin source in the configured sandbox and return its ``BaseAgent`` subclass.

    ``fallback_base`` is the caller's ``BaseAgent`` reference; it is checked next to
    the canonical ``agent.base_agent.BaseAgent`` so reloaded/patched copies still match.
    """
    if plugin_sandbox.plugin_sandbox_backend() == "docker":
        try:
            return plugin_sandbox.build_isolated_plugin_proxy(source_code, class_name, module_label)
        except plugin_sandbox.PluginSandboxError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def _baseagent_candidates() -> list[Any]:
        # Resolve the canonical class on every call so stale monkeypatches or reloads of
        # the caller's module cannot override an available agent.base_agent module.
        base_agent_module = sys.modules.get("agent.base_agent")
        canonical_base = (
            getattr(base_agent_module, "BaseAgent", None) if base_agent_module is not None else None
        )
        candidates: list[Any] = []
        seen: set[int] = set()
        for base in (canonical_base, fallback_base):
            if (
                base is not None
                and base is not object
                and inspect.isclass(base)
                and id(base) not in seen
            ):
                seen.add(id(base))
                candidates.append(base)
        return candidates

    def _is_baseagent_derived(candidate: Any) -> bool:
        if not inspect.isclass(candidate):
            return False
        for base_cls in _baseagent_candidates():
            try:
                if issubclass(candidate, base_cls):
                    return candidate is not base_cls
            except TypeError as exc:
                raise HTTPException(
                    status_code=400, detail="Plugin BaseAgent doğrulanamadı"
                ) from exc
        # Bazı ortamlarda BaseAgent birden fazla modül kimliğiyle yüklenebilir.
        # Bu durumda isim bazlı MRO kontrolü ile eşdeğer türevleri yakalayalım.
        for base in inspect.getmro(candidate)[1:]:
            if base is object:
                continue
            base_name = getattr(base, "__name__", "")
            base_qualname = getattr(base, "__qualname__", "")
            base_module = getattr(base, "__module__", "")
            if base_name == "BaseAgent" or base_qualname.endswith("BaseAgent"):
                return True
            if base_module == "agent.base_agent":
                return True
        return False

    namespace = run_in_sandbox(source_code, module_label)

    if class_name:
        candidate = namespace.get(class_name)
        if not inspect.isclass(candidate):
            raise HTTPException(
                status_code=400, detail=f"Belirtilen sınıf bulunamadı: {class_name}"
            )
        if not _is_baseagent_derived(candidate):
            raise HTTPException(status_code=400, detail="Plugin sınıfı BaseAgent türetmelidir")
        return cast("type[BaseAgent]", candidate)

    discovered: list[type[BaseAgent]] = []
    for obj in namespace.values():
        if _is_baseagent_derived(obj):
            discovered.append(cast("type[BaseAgent]", obj))

    if not discovered:
        raise HTTPException(
            status_code=400, detail="Plugin içinde BaseAgent türevi bir sınıf bulunamadı"
        )
    return discovered[0]


def validate_and_persist_plugin_file(
    filename: str,
    source_code: str,
    module_label: str,
    *,
    run_in_sandbox: Callable[[str, str], dict[str, Any]],
) -> Path:
    """Validate uploaded plugin source in the shared sandbox before persisting it."""
    if plugin_sandbox.plugin_sandbox_backend() == "docker":
        try:
            plugin_sandbox.DockerPluginSandboxBackend().describe(source_code, None, module_label)
        except plugin_sandbox.PluginSandboxError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    else:
        run_in_sandbox(source_code, module_label)

    safe_name = Path(filename or "plugin.py").name
    if not safe_name.endswith(".py"):
        safe_name = f"{safe_name}.py"

    plugins_dir = Path("plugins")
    plugins_dir.mkdir(parents=True, exist_ok=True)
    plugin_path = plugins_dir / safe_name
    plugin_path.write_text(source_code, encoding="utf-8")
    return plugin_path


def register_plugin_agent(
    *,
    role_name: str,
    source_code: str,
    class_name: str | None,
    capabilities: list[str] | None,
    description: str,
    version: str,
    load_agent_class: Callable[[str, str | None, str], type[BaseAgent]],
    agent_registry: Any,
) -> dict[str, Any]:
    """Load a plugin agent class and register it in ``agent_registry`` as non-builtin."""
    normalized_role = validate_plugin_role_name(role_name)
    module_label = f"sidar_plugin_{normalized_role}_{secrets.token_hex(4)}"
    plugin_cls = load_agent_class(source_code, class_name, module_label)
    plugin_description = (description or "").strip() or (plugin_cls.__doc__ or "").strip().split(
        "\n"
    )[0]

    agent_registry.register_type(
        role_name=normalized_role,
        agent_class=plugin_cls,
        capabilities=sanitize_capabilities(capabilities),
        description=plugin_description,
        version=(version or "1.0.0").strip() or "1.0.0",
        is_builtin=False,
    )
    spec = agent_registry.get(normalized_role)
    return {
        "role_name": normalized_role,
        "class_name": plugin_cls.__name__,
        "capabilities": list(spec.capabilities if spec else []),
        "description": str(spec.description if spec else plugin_description),
        "version": str(spec.version if spec else version),
        "is_builtin": bool(spec.is_builtin if spec else False),
    }


def register_uploaded_plugin(
    *,
    data: bytes,
    filename: str,
    role_name: str,
    class_name: str,
    capabilities: str,
    description: str,
    version: str,
    max_bytes: int,
    persist_file: Callable[[str, str, str], Path],
    register_agent: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Validate an uploaded plugin file, persist it and register its agent class."""
    if not data:
        raise HTTPException(status_code=400, detail="Yüklü dosya boş")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Dosya çok büyük")
    try:
        source_code = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Plugin dosyası UTF-8 olmalıdır") from exc
    parsed_capabilities = [c.strip() for c in capabilities.split(",") if c.strip()]
    target_role_name = role_name.strip() or Path(filename or "").stem
    module_label = f"sidar_uploaded_plugin_{secrets.token_hex(4)}"
    persist_file(filename or target_role_name, source_code, module_label)
    return register_agent(
        role_name=target_role_name,
        source_code=source_code,
        class_name=class_name.strip() or None,
        capabilities=parsed_capabilities,
        description=description,
        version=version,
    )
