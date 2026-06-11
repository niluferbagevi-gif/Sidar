"""Capability/integration routes extracted from the legacy web server module."""

from __future__ import annotations

import base64
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from web.routes import LegacyExportRouter


class VisionAnalyzeRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 kodlu görüntü verisi")
    mime_type: str = Field("image/png", description="Görüntü MIME türü")
    analysis_type: str = Field("general", description="Analiz türü: general, ui, chart, document")
    prompt: str | None = Field(None, description="Özel analiz talimatı (opsiyonel)")


class VisionMockupRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 kodlu mockup görüntüsü")
    mime_type: str = Field("image/png", description="Görüntü MIME türü")
    framework: str = Field("html", description="Hedef framework: html, react, vue")
    prompt: str | None = Field(None, description="Ek talimat (opsiyonel)")


class EntityUpsertRequest(BaseModel):
    user_id: str = Field(..., description="Kullanıcı kimliği")
    key: str = Field(..., description="Bellek anahtarı")
    value: str = Field(..., description="Saklanacak değer")
    ttl_days: int | None = Field(None, description="Yaşam süresi (gün); None = kalıcı")


class FeedbackRecordRequest(BaseModel):
    user_id: str = Field(..., description="Kullanıcı kimliği")
    prompt: str = Field(..., description="Kullanıcı girdisi")
    response: str = Field(..., description="Model çıktısı")
    rating: int = Field(..., ge=1, le=5, description="Değerlendirme puanı (1–5)")
    note: str | None = Field(None, description="Ek not")


class SlackSendRequest(BaseModel):
    text: str = Field(..., description="Gönderilecek mesaj metni")
    channel: str | None = Field(None, description="Hedef kanal (ör. #general)")
    thread_ts: str | None = Field(None, description="Thread zaman damgası")


class JiraCreateRequest(BaseModel):
    project_key: str = Field(..., description="Jira proje anahtarı (ör. SIDAR)")
    summary: str = Field(..., description="Issue başlığı")
    description: str | None = Field(None, description="Issue açıklaması")
    issue_type: str = Field("Task", description="Issue türü: Task, Bug, Story")
    priority: str | None = Field(None, description="Öncelik: Highest, High, Medium, Low")


def build_capabilities_router(
    *,
    cfg: Any,
    resolve_agent_instance: Callable[[], Awaitable[Any] | Any],
    resolve_vision_components: Callable[[], tuple[Any, Callable[[str], str]]],
    get_entity_memory: Callable[[], Awaitable[Any]],
    get_feedback_store: Callable[[], Awaitable[Any]],
    get_slack_manager: Callable[[], Awaitable[Any] | Any],
    get_jira_manager: Callable[[], Any],
) -> LegacyExportRouter:
    router = LegacyExportRouter()

    @router.post("/api/vision/analyze", summary="Görüntü Analizi", tags=["Vision"])
    async def api_vision_analyze(req: VisionAnalyzeRequest) -> Any:
        """VisionPipeline ile görüntüyü analiz eder."""
        maybe_agent = resolve_agent_instance()
        agent = await maybe_agent if inspect.isawaitable(maybe_agent) else maybe_agent
        VisionPipeline, build_analyze_prompt = resolve_vision_components()
        pipeline = VisionPipeline(agent.llm, cfg)
        prompt = req.prompt or build_analyze_prompt(req.analysis_type)
        try:
            result = await pipeline.analyze(
                image_b64=req.image_base64,
                mime_type=req.mime_type,
                prompt=prompt,
            )
        except TypeError:
            try:
                image_bytes = base64.b64decode(req.image_base64, validate=True)
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail=f"Geçersiz base64 görüntü verisi: {exc}"
                ) from exc

            result = await pipeline.analyze(
                image_bytes=image_bytes,
                mime_type=req.mime_type,
                analysis_type=req.analysis_type,
            )
        return JSONResponse({"success": True, "result": result})

    @router.post("/api/vision/mockup", summary="Mockup → Kod Dönüşümü", tags=["Vision"])
    async def api_vision_mockup(req: VisionMockupRequest) -> Any:
        """VisionPipeline ile mockup görüntüsünden kod üretir."""
        maybe_agent = resolve_agent_instance()
        agent = await maybe_agent if inspect.isawaitable(maybe_agent) else maybe_agent
        VisionPipeline, _build_analyze_prompt = resolve_vision_components()
        pipeline = VisionPipeline(agent.llm, cfg)
        try:
            code = await pipeline.mockup_to_code(
                image_b64=req.image_base64,
                mime_type=req.mime_type,
                framework=req.framework,
                extra_instructions=req.prompt or "",
            )
        except TypeError:
            try:
                image_bytes = base64.b64decode(req.image_base64, validate=True)
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail=f"Geçersiz base64 görüntü verisi: {exc}"
                ) from exc

            code = await pipeline.mockup_to_code(
                image_bytes=image_bytes,
                mime_type=req.mime_type,
                framework=req.framework,
                extra_instructions=req.prompt or "",
            )
        return JSONResponse({"success": True, "code": code})

    @router.post("/api/memory/entity/upsert", summary="Varlık Belleği Yaz", tags=["EntityMemory"])
    async def api_entity_upsert(req: EntityUpsertRequest) -> Any:
        """Kullanıcıya ait bir bellek kaydını ekler veya günceller."""
        mem = await get_entity_memory()
        await mem.upsert(user_id=req.user_id, key=req.key, value=req.value, ttl_days=req.ttl_days)
        return JSONResponse({"success": True})

    @router.get("/api/memory/entity/{user_id}", summary="Varlık Belleği Profili", tags=["EntityMemory"])
    async def api_entity_get_profile(user_id: str) -> Any:
        """Bir kullanıcının tüm bellek profilini döner."""
        mem = await get_entity_memory()
        profile = await mem.get_profile(user_id=user_id)
        return JSONResponse({"success": True, "user_id": user_id, "profile": profile})

    @router.delete(
        "/api/memory/entity/{user_id}/{key}",
        summary="Varlık Belleği Sil",
        tags=["EntityMemory"],
    )
    async def api_entity_delete(user_id: str, key: str) -> Any:
        """Kullanıcıya ait bir bellek kaydını siler."""
        mem = await get_entity_memory()
        deleted = await mem.delete(user_id=user_id, key=key)
        return JSONResponse({"success": deleted})

    @router.post("/api/feedback/record", summary="Geri Bildirim Kaydet", tags=["ActiveLearning"])
    async def api_feedback_record(req: FeedbackRecordRequest) -> Any:
        """Kullanıcı geri bildirimini FeedbackStore'a kaydeder."""
        store = await get_feedback_store()
        await store.record(
            user_id=req.user_id,
            prompt=req.prompt,
            response=req.response,
            rating=req.rating,
            note=req.note or "",
        )
        return JSONResponse({"success": True})

    @router.get("/api/feedback/stats", summary="Geri Bildirim İstatistikleri", tags=["ActiveLearning"])
    async def api_feedback_stats() -> Any:
        """FeedbackStore istatistiklerini döner."""
        store = await get_feedback_store()
        stats = await store.stats()
        return JSONResponse({"success": True, "stats": stats})

    @router.post("/api/integrations/slack/send", summary="Slack Mesajı Gönder", tags=["Slack"])
    async def api_slack_send(req: SlackSendRequest) -> Any:
        """Slack kanalına mesaj gönderir."""
        maybe_mgr = get_slack_manager()
        mgr = await maybe_mgr if inspect.isawaitable(maybe_mgr) else maybe_mgr
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Slack entegrasyonu yapılandırılmamış.")
        ok, err = await mgr.send_message(text=req.text, channel=req.channel, thread_ts=req.thread_ts)
        if not ok:
            raise HTTPException(status_code=502, detail=f"Slack hatası: {err}")
        return JSONResponse({"success": True})

    @router.get("/api/integrations/slack/channels", summary="Slack Kanal Listesi", tags=["Slack"])
    async def api_slack_channels() -> Any:
        """Workspace'deki Slack kanallarını listeler (SDK gerektirir)."""
        maybe_mgr = get_slack_manager()
        mgr = await maybe_mgr if inspect.isawaitable(maybe_mgr) else maybe_mgr
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Slack entegrasyonu yapılandırılmamış.")
        ok, channels, err = await mgr.list_channels()
        if not ok:
            raise HTTPException(status_code=502, detail=f"Slack hatası: {err}")
        return JSONResponse({"success": True, "channels": channels})

    @router.post("/api/integrations/jira/issue", summary="Jira Issue Oluştur", tags=["Jira"])
    async def api_jira_create_issue(req: JiraCreateRequest) -> Any:
        """Jira'da yeni bir issue oluşturur."""
        mgr = get_jira_manager()
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Jira entegrasyonu yapılandırılmamış.")
        ok, issue, err = await mgr.create_issue(
            project_key=req.project_key,
            summary=req.summary,
            description=req.description or "",
            issue_type=req.issue_type,
            priority=req.priority,
        )
        if not ok:
            raise HTTPException(status_code=502, detail=f"Jira hatası: {err}")
        return JSONResponse({"success": True, "issue": issue})

    @router.get("/api/integrations/jira/issues", summary="Jira Issue Arama", tags=["Jira"])
    async def api_jira_search_issues(jql: str = "", max_results: int = 20) -> Any:
        """JQL sorgusuna göre Jira issue'larını listeler."""
        mgr = get_jira_manager()
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Jira entegrasyonu yapılandırılmamış.")
        ok, issues, err = await mgr.search_issues(jql=jql, max_results=max_results)
        if not ok:
            raise HTTPException(status_code=502, detail=f"Jira hatası: {err}")
        return JSONResponse({"success": True, "issues": issues, "total": len(issues)})

    router.legacy_exports = {
        "api_vision_analyze": api_vision_analyze,
        "api_vision_mockup": api_vision_mockup,
        "api_entity_upsert": api_entity_upsert,
        "api_entity_get_profile": api_entity_get_profile,
        "api_entity_delete": api_entity_delete,
        "api_feedback_record": api_feedback_record,
        "api_feedback_stats": api_feedback_stats,
        "api_slack_send": api_slack_send,
        "api_slack_channels": api_slack_channels,
        "api_jira_create_issue": api_jira_create_issue,
        "api_jira_search_issues": api_jira_search_issues,
        "_VisionAnalyzeRequest": VisionAnalyzeRequest,
        "_VisionMockupRequest": VisionMockupRequest,
        "_EntityUpsertRequest": EntityUpsertRequest,
        "_FeedbackRecordRequest": FeedbackRecordRequest,
        "_SlackSendRequest": SlackSendRequest,
        "_JiraCreateRequest": JiraCreateRequest,
    }
    return router
