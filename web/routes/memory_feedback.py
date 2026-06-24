from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from web.routes import LegacyExportRouter


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


def build_memory_feedback_router(
    *, cfg: Any, entity_memory_cache: dict[str, Any], feedback_store_cache: dict[str, Any]
) -> LegacyExportRouter:
    router = LegacyExportRouter()

    async def get_entity_memory() -> Any:
        if entity_memory_cache.get("instance") is None:
            try:
                from core.entity_memory import get_entity_memory as factory

                entity_memory_cache["instance"] = factory(cfg)
                await entity_memory_cache["instance"].initialize()
            except Exception as exc:
                raise HTTPException(
                    status_code=501, detail=f"EntityMemory başlatılamadı: {exc}"
                ) from exc
        return entity_memory_cache["instance"]

    async def get_feedback_store() -> Any:
        if feedback_store_cache.get("instance") is None:
            try:
                from core.active_learning import get_feedback_store as factory

                feedback_store_cache["instance"] = factory(cfg)
                await feedback_store_cache["instance"].initialize()
            except Exception as exc:
                raise HTTPException(
                    status_code=501, detail=f"FeedbackStore başlatılamadı: {exc}"
                ) from exc
        return feedback_store_cache["instance"]

    @router.post("/api/memory/entity/upsert", summary="Varlık Belleği Yaz", tags=["EntityMemory"])
    async def api_entity_upsert(req: EntityUpsertRequest) -> Any:
        mem = await get_entity_memory()
        await mem.upsert(user_id=req.user_id, key=req.key, value=req.value, ttl_days=req.ttl_days)
        return JSONResponse({"success": True})

    @router.get(
        "/api/memory/entity/{user_id}", summary="Varlık Belleği Profili", tags=["EntityMemory"]
    )
    async def api_entity_get_profile(user_id: str) -> Any:
        mem = await get_entity_memory()
        profile = await mem.get_profile(user_id=user_id)
        return JSONResponse({"success": True, "user_id": user_id, "profile": profile})

    @router.delete(
        "/api/memory/entity/{user_id}/{key}", summary="Varlık Belleği Sil", tags=["EntityMemory"]
    )
    async def api_entity_delete(user_id: str, key: str) -> Any:
        mem = await get_entity_memory()
        deleted = await mem.delete(user_id=user_id, key=key)
        return JSONResponse({"success": deleted})

    @router.post("/api/feedback/record", summary="Geri Bildirim Kaydet", tags=["ActiveLearning"])
    async def api_feedback_record(req: FeedbackRecordRequest) -> Any:
        store = await get_feedback_store()
        await store.record(
            user_id=req.user_id,
            prompt=req.prompt,
            response=req.response,
            rating=req.rating,
            note=req.note or "",
        )
        return JSONResponse({"success": True})

    @router.get(
        "/api/feedback/stats", summary="Geri Bildirim İstatistikleri", tags=["ActiveLearning"]
    )
    async def api_feedback_stats() -> Any:
        store = await get_feedback_store()
        stats = await store.stats()
        return JSONResponse({"success": True, "stats": stats})

    router.legacy_exports = {
        "api_entity_upsert": api_entity_upsert,
        "api_entity_get_profile": api_entity_get_profile,
        "api_entity_delete": api_entity_delete,
        "api_feedback_record": api_feedback_record,
        "api_feedback_stats": api_feedback_stats,
        "_get_entity_memory": get_entity_memory,
        "_get_feedback_store": get_feedback_store,
    }
    return router
