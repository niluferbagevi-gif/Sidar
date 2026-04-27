"""Pazarlama ve dijital operasyon odaklı uzman ajan."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog
from config import Config
from core.rag import DocumentStore
from managers.social_media_manager import SocialMediaManager
from managers.web_search import WebSearchManager

if TYPE_CHECKING:
    from core.db import Database

MultimodalPipelineRuntime: type[Any] | None
try:
    from core.multimodal import MultimodalPipeline as _MultimodalPipeline

    MultimodalPipelineRuntime = cast(type[Any], _MultimodalPipeline)
except Exception:  # pragma: no cover - test/stub ortamlarda opsiyonel olabilir
    MultimodalPipelineRuntime = None

try:
    from agent.tooling import parse_tool_argument
except Exception:  # pragma: no cover - test stub ortamında pydantic olmayabilir

    class _FallbackPayload:
        def __init__(self, payload: dict[str, object]) -> None:
            self.__dict__.update(payload)

        def __getattr__(self, _name: str) -> str:
            return ""

    def parse_tool_argument(_tool_name: str, raw_arg: str) -> _FallbackPayload:
        return _FallbackPayload(json.loads(raw_arg))


@AgentCatalog.register(
    capabilities=["marketing_strategy", "seo_analysis", "campaign_copy", "audience_ops"],
    is_builtin=True,
)
class PoyrazAgent(BaseAgent):
    """SEO, kampanya içeriği ve hedef kitle operasyonları için uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen Poyraz adında pazarlama ve dijital operasyon uzmanı bir ajansın. "
        "Araştırma bulgularını eyleme dönük pazarlama çıktısına çevirir; "
        "SEO, kampanya mesajı, funnel optimizasyonu ve hedef kitle operasyonlarına odaklanırsın."
    )

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        config: Config | None = None,
    ) -> None:
        resolved_cfg = cfg or config
        super().__init__(cfg=resolved_cfg, role_name="poyraz")
        self.web = WebSearchManager(self.cfg)
        self.social = SocialMediaManager(
            graph_api_token=getattr(self.cfg, "META_GRAPH_API_TOKEN", ""),
            instagram_business_account_id=getattr(self.cfg, "INSTAGRAM_BUSINESS_ACCOUNT_ID", ""),
            facebook_page_id=getattr(self.cfg, "FACEBOOK_PAGE_ID", ""),
            whatsapp_phone_number_id=getattr(self.cfg, "WHATSAPP_PHONE_NUMBER_ID", ""),
            api_version=getattr(self.cfg, "META_GRAPH_API_VERSION", "v20.0"),
        )
        self.docs = DocumentStore(
            Path(self.cfg.RAG_DIR),
            top_k=self.cfg.RAG_TOP_K,
            chunk_size=self.cfg.RAG_CHUNK_SIZE,
            chunk_overlap=self.cfg.RAG_CHUNK_OVERLAP,
            use_gpu=self.cfg.USE_GPU,
            gpu_device=self.cfg.GPU_DEVICE,
            mixed_precision=self.cfg.GPU_MIXED_PRECISION,
            cfg=self.cfg,
        )
        self._db: Database | None = None
        self._db_lock: asyncio.Lock | None = None

        self.register_tool("web_search", self._tool_web_search)
        self.register_tool("fetch_url", self._tool_fetch_url)
        self.register_tool("search_docs", self._tool_search_docs)
        self.register_tool("publish_social", self._tool_publish_social)
        self.register_tool("publish_instagram_post", self._tool_publish_instagram_post)
        self.register_tool("publish_facebook_post", self._tool_publish_facebook_post)
        self.register_tool("send_whatsapp_message", self._tool_send_whatsapp_message)
        self.register_tool("build_landing_page", self._tool_build_landing_page)
        self.register_tool("generate_campaign_copy", self._tool_generate_campaign_copy)
        self.register_tool("ingest_video_insights", self._tool_ingest_video_insights)
        self.register_tool("create_marketing_campaign", self._tool_create_marketing_campaign)
        self.register_tool("store_content_asset", self._tool_store_content_asset)
        self.register_tool("create_operation_checklist", self._tool_create_operation_checklist)
        self.register_tool("plan_service_operations", self._tool_plan_service_operations)

    async def _ensure_db(self) -> Database:
        if self._db is not None:
            return self._db
        if self._db_lock is None:
            self._db_lock = asyncio.Lock()
        async with self._db_lock:
            if self._db is not None:
                return self._db
            from core.db import Database

            self._db = Database(self.cfg)
            await self._db.connect()
            await self._db.init_schema()
            return self._db

    async def _tool_web_search(self, arg: str) -> str:
        _ok, result = await self.web.search(arg)
        return str(result)

    async def _tool_fetch_url(self, arg: str) -> str:
        _ok, result = await self.web.fetch_url(arg)
        return str(result)

    async def _tool_search_docs(self, arg: str) -> str:
        result_obj = self.docs.search(arg, None, "auto", "marketing")
        if hasattr(result_obj, "__await__"):
            resolved_result = await result_obj
        else:
            resolved_result = result_obj
        _ok, result = resolved_result
        return str(result)

    async def _tool_publish_social(self, arg: str) -> str:
        raw = (arg or "").strip()
        if raw.startswith("{"):
            try:
                payload = parse_tool_argument("publish_social", raw)
                platform = payload.platform.strip()
                text = payload.text.strip()
                destination = payload.destination.strip()
                media_url = payload.media_url.strip()
                link_url = payload.link_url.strip()
            except Exception as exc:
                return f"[SOCIAL:ERROR] platform=unknown reason=invalid_payload:{exc}"
        else:
            raw_parts = raw.split("|||")
            if len(raw_parts) < 5:
                platform, text, destination, media_url, link_url = ("unknown", "", "", "", "")
            else:
                parts = (raw_parts[:5] + ["", "", "", "", ""])[:5]
                platform, text, destination, media_url, link_url = (part.strip() for part in parts)
        try:
            ok, result = await self.social.publish_content(
                platform=platform,
                text=text,
                destination=destination,
                media_url=media_url,
                link_url=link_url,
            )
        except Exception as exc:
            reason = str(exc).strip() or exc.__class__.__name__
            if "rate limit" in reason.lower():
                return f"[SOCIAL:ERROR] platform={platform} reason=rate_limit:{reason}. Lütfen bekleyip tekrar deneyin."
            return f"[SOCIAL:ERROR] platform={platform} reason={reason}"

        if ok:
            return f"[SOCIAL:PUBLISHED] platform={platform} result={result}"
        return f"[SOCIAL:ERROR] platform={platform} reason={result}"

    async def _tool_publish_instagram_post(self, arg: str) -> str:
        payload = parse_tool_argument("publish_instagram_post", arg)
        ok, result = await self.social.publish_instagram_post(
            caption=payload.caption.strip(),
            image_url=payload.image_url.strip(),
        )
        if ok:
            return f"[INSTAGRAM:PUBLISHED] result={result}"
        return f"[INSTAGRAM:ERROR] reason={result}"

    async def _tool_publish_facebook_post(self, arg: str) -> str:
        payload = parse_tool_argument("publish_facebook_post", arg)
        ok, result = await self.social.publish_facebook_post(
            message=payload.message.strip(),
            link_url=payload.link_url.strip(),
        )
        if ok:
            return f"[FACEBOOK:PUBLISHED] result={result}"
        return f"[FACEBOOK:ERROR] reason={result}"

    async def _tool_send_whatsapp_message(self, arg: str) -> str:
        payload = parse_tool_argument("send_whatsapp_message", arg)
        ok, result = await self.social.send_whatsapp_message(
            to=payload.to.strip(),
            text=payload.text.strip(),
            preview_url=bool(payload.preview_url),
        )
        if ok:
            return f"[WHATSAPP:SENT] result={result}"
        return f"[WHATSAPP:ERROR] reason={result}"

    async def _persist_content_asset(
        self,
        *,
        campaign_id: int,
        tenant_id: str,
        asset_type: str,
        title: str,
        content: str,
        channel: str,
        metadata: dict[str, object] | None = None,
    ) -> str:
        db = await self._ensure_db()
        asset = await db.add_content_asset(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            asset_type=asset_type,
            title=title,
            content=content,
            channel=channel,
            metadata=metadata or {},
        )
        return json.dumps(
            {
                "success": True,
                "asset": {
                    "id": asset.id,
                    "campaign_id": asset.campaign_id,
                    "tenant_id": asset.tenant_id,
                    "asset_type": asset.asset_type,
                    "title": asset.title,
                    "channel": asset.channel,
                },
            },
            ensure_ascii=False,
        )

    async def _tool_build_landing_page(self, arg: str) -> str:
        raw = (arg or "").strip()
        payload = None
        if raw.startswith("{"):
            payload = parse_tool_argument("build_landing_page", raw)
            sections = (
                ", ".join(payload.sections or []) or "hero, problem, çözüm, sosyal kanıt, CTA"
            )
            brief = (
                f"Marka: {payload.brand_name}\n"
                f"Teklif: {payload.offer}\n"
                f"Hedef kitle: {payload.audience}\n"
                f"CTA: {payload.call_to_action}\n"
                f"Ton: {payload.tone}\n"
                f"Bölümler: {sections}"
            )
        else:
            brief = raw
        output = await self._generate_marketing_output(
            "Aşağıdaki brief için landing page taslağı üret. "
            "Çıktıda hero başlığı, alt başlık, değer önerisi, section akışı ve CTA metinleri olsun.\n\n"
            f"{brief}",
            "landing_page",
        )
        if payload and payload.store_asset and payload.campaign_id is not None:
            await self._persist_content_asset(
                campaign_id=int(payload.campaign_id),
                tenant_id=payload.tenant_id.strip() or "default",
                asset_type="landing_page",
                title=payload.asset_title.strip() or "Landing Page Taslağı",
                content=output,
                channel=payload.channel.strip() or "web",
                metadata={
                    "brand_name": payload.brand_name,
                    "offer": payload.offer,
                    "audience": payload.audience,
                    "sections": list(payload.sections or []),
                },
            )
        return output

    async def _tool_generate_campaign_copy(self, arg: str) -> str:
        raw = (arg or "").strip()
        payload = None
        if raw.startswith("{"):
            payload = parse_tool_argument("generate_campaign_copy", raw)
            channels = ", ".join(payload.channels or []) or "instagram, facebook, whatsapp"
            brief = (
                f"Kampanya adı: {payload.campaign_name}\n"
                f"Hedef: {payload.objective}\n"
                f"Hedef kitle: {payload.audience}\n"
                f"Kanallar: {channels}\n"
                f"Teklif: {payload.offer}\n"
                f"Ton: {payload.tone}\n"
                f"CTA: {payload.call_to_action}"
            )
        else:
            brief = raw
        output = await self._generate_marketing_output(
            "Aşağıdaki brief için kanal bazlı kampanya kopyaları üret. "
            "Her kanal için kısa ana mesaj, CTA ve önerilen kreatif açıyı ekle.\n\n"
            f"{brief}",
            "campaign_copy_tool",
        )
        if payload and payload.store_asset and payload.campaign_id is not None:
            await self._persist_content_asset(
                campaign_id=int(payload.campaign_id),
                tenant_id=payload.tenant_id.strip() or "default",
                asset_type="campaign_copy",
                title=payload.asset_title.strip() or "Kampanya Kopyası",
                content=output,
                channel="multi",
                metadata={
                    "campaign_name": payload.campaign_name,
                    "objective": payload.objective,
                    "channels": list(payload.channels or []),
                },
            )
        return output

    async def _tool_ingest_video_insights(self, arg: str) -> str:
        runtime_pipeline_cls = MultimodalPipelineRuntime
        if runtime_pipeline_cls is None:
            try:
                runtime_pipeline_cls = importlib.import_module("core.multimodal").MultimodalPipeline
            except Exception:
                runtime_pipeline_cls = None

        if runtime_pipeline_cls is None:
            return "[VIDEO:ERROR] source=unknown reason=multimodal_pipeline_unavailable"

        raw = (arg or "").strip()
        if raw.startswith("{"):
            payload = parse_tool_argument("ingest_video_insights", raw)
            source_url = payload.source_url.strip()
            prompt = payload.prompt.strip()
            language = payload.language.strip() or None
            session_id = payload.session_id.strip() or "marketing"
            max_frames = max(1, int(payload.max_frames or 6))
            frame_interval_seconds = max(0.1, float(payload.frame_interval_seconds or 5.0))
        else:
            parts = (raw.split("|||", 4) + ["", "", "", "", ""])[:5]
            source_url = parts[0].strip()
            prompt = parts[1].strip()
            language = parts[2].strip() or None
            session_id = parts[3].strip() or "marketing"
            max_frames = max(1, int(parts[4].strip() or 6))
            frame_interval_seconds = 5.0

        pipeline = runtime_pipeline_cls(self.llm, self.cfg)
        result = await pipeline.analyze_media_source(
            media_source=source_url,
            prompt=prompt,
            language=language,
            max_frames=max_frames,
            frame_interval_seconds=frame_interval_seconds,
            ingest_document_store=self.docs,
            ingest_session_id=session_id,
            ingest_title=f"Video İçgörü Özeti - {source_url}",
            ingest_tags=["video", "multimodal", "marketing", "poyraz"],
        )
        if not result.get("success"):
            return f"[VIDEO:ERROR] source={source_url} reason={result.get('reason', 'unknown')}"
        ingest = dict(result.get("document_ingest") or {})
        return (
            f"[VIDEO:INGESTED] source={source_url} "
            f"doc_id={ingest.get('doc_id', '')} "
            f"scene_summary={result.get('scene_summary', '')}"
        )

    async def _tool_create_marketing_campaign(self, arg: str) -> str:
        payload = parse_tool_argument("create_marketing_campaign", arg)
        db = await self._ensure_db()
        campaign = await db.upsert_marketing_campaign(
            tenant_id=payload.tenant_id.strip() or "default",
            name=payload.name.strip(),
            channel=payload.channel.strip(),
            objective=payload.objective.strip(),
            status=payload.status.strip() or "draft",
            owner_user_id=payload.owner_user_id.strip(),
            budget=float(payload.budget or 0.0),
            metadata=dict(payload.metadata or {}),
            campaign_id=payload.campaign_id,
        )
        return json.dumps(
            {
                "success": True,
                "campaign": {
                    "id": campaign.id,
                    "tenant_id": campaign.tenant_id,
                    "name": campaign.name,
                    "channel": campaign.channel,
                    "objective": campaign.objective,
                    "status": campaign.status,
                    "owner_user_id": campaign.owner_user_id,
                    "budget": campaign.budget,
                },
            },
            ensure_ascii=False,
        )

    async def _tool_store_content_asset(self, arg: str) -> str:
        payload = parse_tool_argument("store_content_asset", arg)
        return await self._persist_content_asset(
            campaign_id=int(payload.campaign_id),
            tenant_id=payload.tenant_id.strip() or "default",
            asset_type=payload.asset_type.strip(),
            title=payload.title.strip(),
            content=payload.content,
            channel=payload.channel.strip(),
            metadata=dict(payload.metadata or {}),
        )

    async def _tool_create_operation_checklist(self, arg: str) -> str:
        payload = parse_tool_argument("create_operation_checklist", arg)
        db = await self._ensure_db()
        checklist = await db.add_operation_checklist(
            tenant_id=payload.tenant_id.strip() or "default",
            title=payload.title.strip(),
            items=list(payload.items or []),
            status=payload.status.strip() or "pending",
            owner_user_id=payload.owner_user_id.strip(),
            campaign_id=payload.campaign_id,
        )
        return json.dumps(
            {
                "success": True,
                "checklist": {
                    "id": checklist.id,
                    "campaign_id": checklist.campaign_id,
                    "tenant_id": checklist.tenant_id,
                    "title": checklist.title,
                    "status": checklist.status,
                    "items_json": checklist.items_json,
                },
            },
            ensure_ascii=False,
        )

    async def _tool_plan_service_operations(self, arg: str) -> str:
        payload = parse_tool_argument("plan_service_operations", arg)
        items: list[dict[str, object]] = []
        for group_name, options in dict(payload.menu_plan or {}).items():
            if list(options or []):
                items.append(
                    {
                        "type": "menu_plan",
                        "group": group_name,
                        "options": [
                            str(option).strip()
                            for option in list(options or [])
                            if str(option).strip()
                        ],
                    }
                )
        for role_name, assignee in dict(payload.vendor_assignments or {}).items():
            if str(assignee).strip():
                items.append(
                    {
                        "type": "vendor_assignment",
                        "role": role_name,
                        "assignee": str(assignee).strip(),
                    }
                )
        for entry in list(payload.timeline or []):
            if str(entry).strip():
                items.append({"type": "timeline", "entry": str(entry).strip()})
        if payload.notes.strip():
            items.append({"type": "note", "text": payload.notes.strip()})

        summary = {
            "campaign_name": payload.campaign_name,
            "service_name": payload.service_name,
            "audience": payload.audience,
            "items": items,
        }
        if payload.persist_checklist:
            db = await self._ensure_db()
            checklist = await db.add_operation_checklist(
                tenant_id=payload.tenant_id.strip() or "default",
                title=payload.checklist_title.strip() or "Operasyon Planı",
                items=items,
                status="planned",
                owner_user_id=payload.owner_user_id.strip(),
                campaign_id=payload.campaign_id,
            )
            summary["checklist"] = {
                "id": checklist.id,
                "title": checklist.title,
                "status": checklist.status,
            }
        return json.dumps({"success": True, "service_plan": summary}, ensure_ascii=False)

    async def _generate_marketing_output(self, task_prompt: str, mode: str) -> str:
        user_prompt = (
            f"Görev modu: {mode}\n"
            "Yanıtı Türkçe ver. Somut, uygulanabilir ve kısa başlıklar kullan. "
            "Varsa ölçülebilir KPI, kanal önerisi ve bir sonraki adımı ekle.\n\n"
            f"[GOREV]\n{task_prompt.strip()}"
        )
        return str(
            await self.call_llm(
            [{"role": "user", "content": user_prompt}],
            system_prompt=self.SYSTEM_PROMPT,
            temperature=0.4,
            )
        )

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş pazarlama görevi verildi."

        lower = prompt.lower()
        if lower.startswith("web_search|"):
            return str(await self.call_tool("web_search", prompt.split("|", 1)[1].strip()))
        if lower.startswith("fetch_url|"):
            return str(await self.call_tool("fetch_url", prompt.split("|", 1)[1].strip()))
        if lower.startswith("search_docs|"):
            return str(await self.call_tool("search_docs", prompt.split("|", 1)[1].strip()))
        if lower.startswith("build_landing_page|") or lower.startswith("landing_page|"):
            return str(await self.call_tool("build_landing_page", prompt.split("|", 1)[1].strip()))
        if lower.startswith("generate_campaign_copy|"):
            return str(await self.call_tool("generate_campaign_copy", prompt.split("|", 1)[1].strip()))
        if lower.startswith("publish_instagram_post|"):
            return str(await self.call_tool("publish_instagram_post", prompt.split("|", 1)[1].strip()))
        if lower.startswith("publish_facebook_post|"):
            return str(await self.call_tool("publish_facebook_post", prompt.split("|", 1)[1].strip()))
        if lower.startswith("send_whatsapp_message|"):
            return str(await self.call_tool("send_whatsapp_message", prompt.split("|", 1)[1].strip()))
        if lower.startswith("ingest_video_insights|") or lower.startswith("analyze_video|"):
            return str(await self.call_tool("ingest_video_insights", prompt.split("|", 1)[1].strip()))
        if lower.startswith("create_marketing_campaign|"):
            return str(
                await self.call_tool(
                "create_marketing_campaign", prompt.split("|", 1)[1].strip()
                )
            )
        if lower.startswith("store_content_asset|"):
            return str(await self.call_tool("store_content_asset", prompt.split("|", 1)[1].strip()))
        if lower.startswith("create_operation_checklist|"):
            return str(
                await self.call_tool(
                "create_operation_checklist", prompt.split("|", 1)[1].strip()
                )
            )
        if lower.startswith("plan_service_operations|"):
            return str(await self.call_tool("plan_service_operations", prompt.split("|", 1)[1].strip()))
        if lower.startswith("seo_audit|"):
            return await self._generate_marketing_output(
                prompt.split("|", 1)[1].strip(), "seo_audit"
            )
        if lower.startswith("campaign_copy|"):
            return await self._generate_marketing_output(
                prompt.split("|", 1)[1].strip(), "campaign_copy"
            )
        if lower.startswith("audience_ops|"):
            return await self._generate_marketing_output(
                prompt.split("|", 1)[1].strip(), "audience_ops"
            )
        if lower.startswith("research_to_marketing|"):
            return await self._generate_marketing_output(
                prompt.split("|", 1)[1].strip(), "research_to_marketing"
            )
        if lower.startswith("publish_social|"):
            return str(await self.call_tool("publish_social", prompt.split("|", 1)[1].strip()))

        if any(
            keyword in lower
            for keyword in ("landing page", "landing_page", "açılış sayfası", "landing")
        ):
            return str(
                await self.call_tool(
                "build_landing_page",
                json.dumps(
                    {
                        "brand_name": "SİDAR",
                        "offer": prompt,
                        "audience": "genel",
                        "call_to_action": "İletişime geç",
                        "tone": "professional",
                    },
                    ensure_ascii=False,
                ),
                )
            )

        if any(
            keyword in lower
            for keyword in (
                "seo",
                "kampanya",
                "hedef kitle",
                "pazarlama",
                "growth",
                "funnel",
                "operasyon",
            )
        ):
            return await self._generate_marketing_output(prompt, "marketing_strategy")

        return await self._generate_marketing_output(prompt, "marketing_general")
