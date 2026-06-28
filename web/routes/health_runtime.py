"""Runtime health/status response builders for the FastAPI server.

The route declarations live in :mod:`web.routes.health`; this module keeps the
operational payload construction out of the large ``web_server.py`` facade while
preserving the legacy ``web_server._health_response`` compatibility wrappers.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from fastapi.responses import JSONResponse


class LoggerLike(Protocol):
    """Small logger protocol used by health builders."""

    def exception(self, msg: str, *args: Any) -> None: ...


def expose_operational_error_details(app_factory: Any) -> bool:
    """Return whether operational health errors may include exception details."""
    return bool(app_factory._expose_exception_details())


def health_error_payload(error: str, exc: Exception, *, expose_details: bool) -> dict[str, Any]:
    """Build a degraded health payload, optionally exposing exception text."""
    payload: dict[str, Any] = {"status": "degraded", "error": error}
    if expose_details:
        payload["detail"] = str(exc)
    return payload


async def build_health_response(
    *,
    require_dependencies: bool = False,
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    expose_details: Callable[[], bool],
    logger: LoggerLike,
    start_time: float,
) -> JSONResponse:
    """Build the liveness/readiness response for the current Sidar agent."""
    try:
        agent = await resolve_agent_instance()
        health_data = agent.health.get_health_summary()
    except Exception as exc:
        logger.exception("Health check güvenli fallback'e düştü: %s", exc)
        payload = health_error_payload(
            "health_check_failed",
            exc,
            expose_details=expose_details(),
        )
        payload["uptime_seconds"] = int(time.monotonic() - start_time)
        return JSONResponse(
            payload,
            status_code=503,
        )

    health_data["uptime_seconds"] = int(time.monotonic() - start_time)

    # Eğer ana yapay zeka servisi (Ollama) çöktüyse 503 HTTP kodu döndür
    if agent.cfg.AI_PROVIDER == "ollama" and not health_data["ollama_online"]:
        health_data["status"] = "degraded"
        return JSONResponse(health_data, status_code=503)

    if require_dependencies:
        try:
            dependency_health = agent.health.get_dependency_health()
        except Exception as exc:
            logger.exception("Dependency health sorgusu başarısız oldu: %s", exc)
            dependency_error: dict[str, Any] = {
                "healthy": False,
                "error": "dependency_health_failed",
            }
            if expose_details():
                dependency_error["detail"] = str(exc)
            health_data["dependencies"] = {"error": dependency_error}
            health_data["status"] = "degraded"
            return JSONResponse(health_data, status_code=503)
        health_data["dependencies"] = dependency_health
        if any(item.get("healthy") is False for item in dependency_health.values()):
            health_data["status"] = "degraded"
            return JSONResponse(health_data, status_code=503)

    return JSONResponse(health_data)


async def build_status_response(
    *,
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    metrics_snapshot: Callable[[], Any],
    start_time: float,
) -> JSONResponse:
    """Return the legacy /status payload kept for backwards-compatible callers."""
    started_at = time.monotonic()
    agent = await resolve_agent_instance()
    cfg_obj = agent.cfg
    provider = str(getattr(cfg_obj, "AI_PROVIDER", "") or "")
    model = (
        str(getattr(cfg_obj, "GEMINI_MODEL", "") or "")
        if provider == "gemini"
        else str(getattr(cfg_obj, "CODING_MODEL", "") or "")
    )

    ollama_online = bool(agent.health.check_ollama())
    ollama_latency_ms = int((time.monotonic() - started_at) * 1000)

    payload: dict[str, Any] = {
        "status": "ok",
        "version": getattr(agent, "VERSION", ""),
        "uptime_seconds": int(time.monotonic() - start_time),
        "provider": provider,
        "model": model,
        "ollama_online": ollama_online,
        "ollama_latency_ms": ollama_latency_ms,
        "gpu": {
            "enabled": bool(getattr(cfg_obj, "USE_GPU", False)),
            "info": agent.health.get_gpu_info(),
            "configured_info": getattr(cfg_obj, "GPU_INFO", {}),
            "count": getattr(cfg_obj, "GPU_COUNT", 0),
            "cuda_version": getattr(cfg_obj, "CUDA_VERSION", ""),
        },
        "memory": {
            "turns": len(getattr(agent, "memory", [])),
            "encrypted": bool(getattr(cfg_obj, "MEMORY_ENCRYPTION_KEY", "")),
        },
        "access_level": getattr(cfg_obj, "ACCESS_LEVEL", ""),
        "services": {
            "github": bool(agent.github.is_available()),
            "web_search": bool(agent.web.is_available()),
            "docs": agent.docs.status(),
            "package_info": agent.pkg.status(),
        },
        "llm_metrics": metrics_snapshot(),
    }
    return JSONResponse(payload)
