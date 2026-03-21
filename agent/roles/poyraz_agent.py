"""Pazarlama ve dijital operasyon odaklı uzman ajan."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import Config
from core.rag import DocumentStore
from managers.social_media_manager import SocialMediaManager
from managers.web_search import WebSearchManager

from agent.base_agent import BaseAgent


class PoyrazAgent(BaseAgent):
    """SEO, kampanya içeriği ve hedef kitle operasyonları için uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen Poyraz adında pazarlama ve dijital operasyon uzmanı bir ajansın. "
        "Araştırma bulgularını eyleme dönük pazarlama çıktısına çevirir; "
        "SEO, kampanya mesajı, funnel optimizasyonu ve hedef kitle operasyonlarına odaklanırsın."
    )

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="poyraz")
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

        self.register_tool("web_search", self._tool_web_search)
        self.register_tool("fetch_url", self._tool_fetch_url)
        self.register_tool("search_docs", self._tool_search_docs)
        self.register_tool("publish_social", self._tool_publish_social)

    async def _tool_web_search(self, arg: str) -> str:
        _ok, result = await self.web.search(arg)
        return result

    async def _tool_fetch_url(self, arg: str) -> str:
        _ok, result = await self.web.fetch_url(arg)
        return result

    async def _tool_search_docs(self, arg: str) -> str:
        result_obj = self.docs.search(arg, None, "auto", "marketing")
        if hasattr(result_obj, "__await__"):
            result_obj = await result_obj
        _ok, result = result_obj
        return result

    async def _tool_publish_social(self, arg: str) -> str:
        parts = (arg.split("|||", 4) + ["", "", "", "", ""])[:5]
        platform, text, destination, media_url, link_url = (part.strip() for part in parts)
        ok, result = await self.social.publish_content(
            platform=platform,
            text=text,
            destination=destination,
            media_url=media_url,
            link_url=link_url,
        )
        if ok:
            return f"[SOCIAL:PUBLISHED] platform={platform} result={result}"
        return f"[SOCIAL:ERROR] platform={platform} reason={result}"

    async def _generate_marketing_output(self, task_prompt: str, mode: str) -> str:
        user_prompt = (
            f"Görev modu: {mode}\n"
            "Yanıtı Türkçe ver. Somut, uygulanabilir ve kısa başlıklar kullan. "
            "Varsa ölçülebilir KPI, kanal önerisi ve bir sonraki adımı ekle.\n\n"
            f"[GOREV]\n{task_prompt.strip()}"
        )
        return await self.call_llm(
            [{"role": "user", "content": user_prompt}],
            system_prompt=self.SYSTEM_PROMPT,
            temperature=0.4,
        )

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş pazarlama görevi verildi."

        lower = prompt.lower()
        if lower.startswith("web_search|"):
            return await self.call_tool("web_search", prompt.split("|", 1)[1].strip())
        if lower.startswith("fetch_url|"):
            return await self.call_tool("fetch_url", prompt.split("|", 1)[1].strip())
        if lower.startswith("search_docs|"):
            return await self.call_tool("search_docs", prompt.split("|", 1)[1].strip())
        if lower.startswith("seo_audit|"):
            return await self._generate_marketing_output(prompt.split("|", 1)[1].strip(), "seo_audit")
        if lower.startswith("campaign_copy|"):
            return await self._generate_marketing_output(prompt.split("|", 1)[1].strip(), "campaign_copy")
        if lower.startswith("audience_ops|"):
            return await self._generate_marketing_output(prompt.split("|", 1)[1].strip(), "audience_ops")
        if lower.startswith("research_to_marketing|"):
            return await self._generate_marketing_output(prompt.split("|", 1)[1].strip(), "research_to_marketing")
        if lower.startswith("publish_social|"):
            return await self.call_tool("publish_social", prompt.split("|", 1)[1].strip())

        if any(keyword in lower for keyword in ("seo", "kampanya", "hedef kitle", "pazarlama", "growth", "funnel", "operasyon")):
            return await self._generate_marketing_output(prompt, "marketing_strategy")

        return await self._generate_marketing_output(prompt, "marketing_general")
