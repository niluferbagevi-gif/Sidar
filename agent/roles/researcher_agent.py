"""Araştırma odaklı uzman ajan (web + RAG)."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog
from config import Config
from core.rag import DocumentStore
from managers.web_search import WebSearchManager


@AgentCatalog.register(capabilities=["web_search", "rag_search", "summarization"], is_builtin=True)
class ResearcherAgent(BaseAgent):
    """Yalnızca bilgi toplama araçlarını kullanan uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen yalnızca bilgi toplama odaklı bir araştırmacı ajansın. "
        "Kod yazma/değiştirme yapmazsın; web ve doküman kaynaklarından doğrulanabilir çıktı üretirsin."
    )

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        config: Config | None = None,
    ) -> None:
        resolved_cfg = cfg or config
        super().__init__(cfg=resolved_cfg, role_name="researcher")
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

        tool_map = {
            "web_search": self._tool_web_search,
            "fetch_url": self._tool_fetch_url,
            "search_docs": self._tool_search_docs,
            "docs_search": self._tool_docs_search,
        }
        for name, func in tool_map.items():
            self.register_tool(name, func)
            # Bazı testlerde BaseAgent.register_tool monkeypatch ile no-op olabilir.
            # Bu durumda da araç sözlüğünü deterministic şekilde doldur.
            if name not in self.tools:
                self.tools[name] = func

    async def _tool_web_search(self, arg: str) -> str:
        _ok, result = await WebSearchManager.search(self.web, arg)
        return result

    async def _tool_fetch_url(self, arg: str) -> str:
        _ok, result = await WebSearchManager.fetch_url(self.web, arg)
        return result

    async def _tool_search_docs(self, arg: str) -> str:
        parts = arg.split(" ", 1)
        lib = parts[0].strip() if parts else ""
        topic = parts[1].strip() if len(parts) > 1 else ""
        _ok, result = await WebSearchManager.search_docs(self.web, lib, topic)
        return result

    async def _tool_docs_search(self, arg: str) -> str:
        session_id = "global"
        try:
            result_obj = await asyncio.to_thread(self.docs.search, arg, None, "auto", session_id)
        except TimeoutError:
            return "Doküman araması zaman aşımına uğradı."
        except Exception as exc:
            return f"Doküman araması şu anda kullanılamıyor: {exc}"
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

        for _ in range(4):
            try:
                decision = await self.call_llm(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    json_mode=True,
                )
            except Exception:
                break
            try:
                parsed = json.loads(str(decision))
            except (TypeError, ValueError, json.JSONDecodeError):
                break
            tool = str(parsed.get("tool", "")).strip().lower()
            argument = str(parsed.get("argument", "")).strip()
            if tool in ("", "final_answer"):
                final_answer = argument or str(parsed.get("content", "")).strip()
                return final_answer or str(decision)
            if tool not in self.tools:
                break
            prompt = await self.call_tool(tool, argument)

        return await self.call_tool("web_search", prompt)
