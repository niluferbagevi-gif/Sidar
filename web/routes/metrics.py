from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, Response

from web.routes import LegacyExportRouter


def build_metrics_router(
    *,
    require_metrics_access: Callable[..., Any],
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    start_time: float,
    local_rate_limits: dict[str, list[float]],
    get_llm_metrics_collector: Callable[[], Any],
    render_llm_metrics_prometheus: Callable[[dict[str, Any]], str],
    set_current_metrics_user_id: Callable[[str], Any],
    reset_current_metrics_user_id: Callable[[Any], None],
    logger: Any,
) -> LegacyExportRouter:
    router = LegacyExportRouter()

    @router.get("/metrics")
    async def metrics(
        request: Request,
        _user: dict[str, Any] = Depends(require_metrics_access),
    ) -> Response:
        user_id = str(getattr(_user, "id", "") or (_user.get("id") if isinstance(_user, dict) else "") or "metrics-admin")
        metrics_token = set_current_metrics_user_id(user_id)
        agent = await resolve_agent_instance()
        try:
            uptime_s = int(time.monotonic() - start_time)
            rag_docs = agent.docs.doc_count
            if hasattr(agent.memory, "aget_all_sessions"):
                sessions = await agent.memory.aget_all_sessions()
            else:
                sessions = agent.memory.get_all_sessions()
                if inspect.isawaitable(sessions):
                    sessions = await sessions
            rl_total = sum(len(v) for v in local_rate_limits.values())
            llm_totals = get_llm_metrics_collector().snapshot().get("totals", {})
            payload = {
                "version": agent.VERSION,
                "uptime_seconds": uptime_s,
                "sessions_total": len(sessions),
                "active_session_turns": len(agent.memory),
                "rag_documents": rag_docs,
                "rate_limit_buckets": len(local_rate_limits),
                "rate_limit_requests_in_window": rl_total,
                "provider": agent.cfg.AI_PROVIDER,
                "gpu_enabled": agent.cfg.USE_GPU,
                "llm_calls": llm_totals.get("calls", 0),
                "llm_total_tokens": llm_totals.get("total_tokens", 0),
            }
            accept = request.headers.get("Accept", "")
            if isinstance(request, Request) and "text/plain" in accept:
                try:
                    from prometheus_client import (
                        CONTENT_TYPE_LATEST,
                        CollectorRegistry,
                        Gauge,
                        generate_latest,
                    )
                    from starlette.responses import Response as _PromeResp

                    reg = CollectorRegistry()
                    Gauge("sidar_uptime_seconds", "Sunucu çalışma süresi (s)", registry=reg).set(uptime_s)
                    Gauge("sidar_sessions_total", "Toplam oturum sayısı", registry=reg).set(len(sessions))
                    Gauge("sidar_rag_documents_total", "RAG belge sayısı", registry=reg).set(rag_docs)
                    Gauge("sidar_active_turns", "Aktif oturum tur sayısı", registry=reg).set(
                        len(agent.memory)
                    )
                    Gauge("sidar_rate_limit_requests", "Rate limit penceredeki istek", registry=reg).set(
                        rl_total
                    )
                    return _PromeResp(generate_latest(reg), media_type=CONTENT_TYPE_LATEST)
                except ImportError:
                    pass
            return JSONResponse(payload)
        finally:
            reset_current_metrics_user_id(metrics_token)

    @router.get("/metrics/llm/prometheus")
    async def llm_prometheus_metrics(
        _user: dict[str, Any] = Depends(require_metrics_access),
    ) -> Response:
        snapshot = get_llm_metrics_collector().snapshot()
        llm_part = render_llm_metrics_prometheus(snapshot)
        delegation_part = ""
        try:
            from core.agent_metrics import get_agent_metrics_collector

            delegation_part = get_agent_metrics_collector().render_prometheus()
        except Exception as exc:
            logger.debug("Delegation metrikleri render edilemedi: %s", exc)
        return Response(content=llm_part + delegation_part, media_type="text/plain; version=0.0.4")

    @router.get("/metrics/llm")
    @router.get("/api/budget")
    async def llm_budget_metrics(
        _user: dict[str, Any] = Depends(require_metrics_access),
    ) -> Response:
        collector = get_llm_metrics_collector()
        return JSONResponse(collector.snapshot())

    router.legacy_exports = {
        "metrics": metrics,
        "llm_prometheus_metrics": llm_prometheus_metrics,
        "llm_budget_metrics": llm_budget_metrics,
    }
    return router
