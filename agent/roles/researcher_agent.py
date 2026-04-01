"""Araştırma odaklı uzman ajan (web + RAG)."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Optional

from config import Config
from core.rag import DocumentStore
from managers.web_search import WebSearchManager

from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog


@AgentCatalog.register(capabilities=['web_search', 'rag_search', 'summarization'], is_builtin=True)
class ResearcherAgent(BaseAgent):
    """Yalnızca bilgi toplama araçlarını kullanan uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen yalnızca bilgi toplama odaklı bir araştırmacı ajansın. "
        "Kod yazma/değiştirme yapmazsın; web ve doküman kaynaklarından doğrulanabilir çıktı üretirsin."
    )

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="researcher")
        self.web = WebSearchManager(self.cfg)
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
        self.register_tool("docs_search", self._tool_docs_search)

    async def _tool_web_search(self, arg: str) -> str:
        _ok, result = await self.web.search(arg)
        return result

    async def _tool_fetch_url(self, arg: str) -> str:
        _ok, result = await self.web.fetch_url(arg)
        return result

    async def _tool_search_docs(self, arg: str) -> str:
        parts = arg.split(" ", 1)
        lib = parts[0].strip() if parts else ""
        topic = parts[1].strip() if len(parts) > 1 else ""
        _ok, result = await self.web.search_docs(lib, topic)
        return result

    async def _tool_docs_search(self, arg: str) -> str:
        session_id = "global"
        result_obj = await asyncio.to_thread(self.docs.search, arg, None, "auto", session_id)
        if inspect.isawaitable(result_obj):
            result_obj = await result_obj
        _ok, result = result_obj
        return result

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş araştırma görevi verildi."

        lower = prompt.lower()
        if lower.startswith("fetch_url|"):
            return await self.call_tool("fetch_url", prompt.split("|", 1)[1].strip())
        if lower.startswith("search_docs|"):
            return await self.call_tool("search_docs", prompt.split("|", 1)[1].strip())
        if lower.startswith("docs_search|"):
            return await self.call_tool("docs_search", prompt.split("|", 1)[1].strip())

        return await self.call_tool("web_search", prompt)