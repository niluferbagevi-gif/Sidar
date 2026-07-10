"""
Sidar Project — Core Modülleri.

Bu paket ajan altyapısının temel bileşenlerini lazy olarak dışa aktarır. Ağır
ve opsiyonel alt modüller paket import'u sırasında yüklenmez; böylece provider
import sırası ve eksik opsiyonel bağımlılık hataları gerçek traceback'iyle kalır.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any

from sidar_version import PRODUCT_VERSION

__version__ = PRODUCT_VERSION

_MODULE_EXPORTS: dict[str, str] = {
    "memory": "core.memory",
    "llm_client": "core.llm_client",
    "db": "core.db",
    "rag": "core.rag",
    "llm_metrics": "core.llm_metrics",
    "multimodal": "core.multimodal",
    "voice": "core.voice",
    "active_learning": "core.active_learning",
}

_SYMBOL_EXPORTS: dict[str, tuple[str, str]] = {
    "LLMClient": ("core.llm_client", "LLMClient"),
    "ConversationMemory": ("core.memory", "ConversationMemory"),
    "DocumentStore": ("core.rag", "DocumentStore"),
    "Database": ("core.db", "Database"),
    "MultimodalPipeline": ("core.multimodal", "MultimodalPipeline"),
    "VoicePipeline": ("core.voice", "VoicePipeline"),
    "LLMMetricsCollector": ("core.llm_metrics", "LLMMetricsCollector"),
    "get_llm_metrics_collector": ("core.llm_metrics", "get_llm_metrics_collector"),
}

_ALIAS_EXPORTS: dict[str, str] = {
    "MemoryManager": "ConversationMemory",
    "RAGManager": "DocumentStore",
    "DatabaseManager": "Database",
}


def _missing_dependency_proxy(attr_name: str) -> type:
    """Return a constructor proxy used only for genuinely missing optional deps."""

    class _MissingDependencyProxy:  # pragma: no cover - yalnızca bağımlılık eksikse çalışır
        __name__ = attr_name

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                f"'{attr_name}' kullanımı için opsiyonel bağımlılıklar yüklü olmalıdır."
            )

    return _MissingDependencyProxy


def _is_missing_requested_module(exc: ModuleNotFoundError, module_name: str) -> bool:
    """Return True only when the requested optional module itself is missing."""

    missing = exc.name or ""
    return module_name == missing or module_name.startswith(f"{missing}.")


def _load_module(name: str) -> ModuleType:
    module_name = _MODULE_EXPORTS[name]
    module = import_module(module_name)
    globals()[name] = module
    return module


def _load_symbol(name: str) -> Any:
    module_name, attr_name = _SYMBOL_EXPORTS[name]
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if _is_missing_requested_module(exc, module_name):
            value = _missing_dependency_proxy(attr_name)
            globals()[name] = value
            return value
        raise
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __getattr__(name: str) -> Any:
    """Lazy-load public core modules and symbols without swallowing code errors."""

    if name in _MODULE_EXPORTS:
        return _load_module(name)
    if name in _SYMBOL_EXPORTS:
        return _load_symbol(name)
    if name in _ALIAS_EXPORTS:
        value = __getattr__(_ALIAS_EXPORTS[name])
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ConversationMemory",
    "LLMClient",
    "DocumentStore",
    "Database",
    "MultimodalPipeline",
    "VoicePipeline",
    "LLMMetricsCollector",
    "__version__",
    "MemoryManager",
    "RAGManager",
    "DatabaseManager",
    "get_llm_metrics_collector",
]
