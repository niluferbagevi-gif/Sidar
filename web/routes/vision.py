from __future__ import annotations

import base64
from collections.abc import Callable
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


def _decode_image_payload(image_base64: str) -> bytes:
    try:
        return base64.b64decode(image_base64, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Geçersiz base64 görüntü verisi: {exc}"
        ) from exc


def build_vision_router(
    *,
    cfg: Any,
    resolve_agent_instance: Callable[[], Any],
    resolve_vision_components: Callable[[], tuple[Any, Any]],
) -> LegacyExportRouter:
    router = LegacyExportRouter()

    @router.post("/api/vision/analyze", summary="Görüntü Analizi", tags=["Vision"])
    async def api_vision_analyze(req: VisionAnalyzeRequest) -> Any:
        agent = await resolve_agent_instance()
        VisionPipeline, build_analyze_prompt = resolve_vision_components()
        pipeline = VisionPipeline(agent.llm, cfg)
        prompt = req.prompt or build_analyze_prompt(req.analysis_type)
        try:
            result = await pipeline.analyze(
                image_b64=req.image_base64, mime_type=req.mime_type, prompt=prompt
            )
        except TypeError:
            result = await pipeline.analyze(
                image_bytes=_decode_image_payload(req.image_base64),
                mime_type=req.mime_type,
                analysis_type=req.analysis_type,
            )
        return JSONResponse({"success": True, "result": result})

    @router.post("/api/vision/mockup", summary="Mockup → Kod Dönüşümü", tags=["Vision"])
    async def api_vision_mockup(req: VisionMockupRequest) -> Any:
        agent = await resolve_agent_instance()
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
            code = await pipeline.mockup_to_code(
                image_bytes=_decode_image_payload(req.image_base64),
                mime_type=req.mime_type,
                framework=req.framework,
                extra_instructions=req.prompt or "",
            )
        return JSONResponse({"success": True, "code": code})

    router.legacy_exports = {
        "api_vision_analyze": api_vision_analyze,
        "api_vision_mockup": api_vision_mockup,
    }
    return router
