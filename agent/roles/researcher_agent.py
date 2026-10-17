"""Araştırma odaklı uzman ajan (web + RAG)."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog
from config import Config
from core.rag import DocumentStore
from managers.web_search import WebSearchManager


@AgentCatalog.register(
    capabilities=["web_search", "rag_search", "summarization"],
    description="Web ve RAG kaynaklarından doğrulanabilir araştırma özeti üreten uzman ajan.",
    is_builtin=True,
)
class ResearcherAgent(BaseAgent):
    """Yalnızca bilgi toplama araçlarını kullanan uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen yalnızca bilgi toplama odaklı bir araştırmacı ajansın. "
        "Kod yazma/değiştirme yapmazsın; web ve doküman kaynaklarından doğrulanabilir çıktı "
        "üretirsin.\n\n"
        "Her adımda YALNIZCA şu biçimde tek bir JSON nesnesi döndür:\n"
        '{"tool": "<araç>", "argument": "<metin>"}\n\n'
        "Araçlar:\n"
        "- docs_search: Projenin yerel dokümanlarında (RAG: README, AGENTS.md, docs/, "
        "kaynak kod) arar. argument = kısa arama sorgusu.\n"
        "- web_search: İnternette arar. argument = kısa arama sorgusu.\n"
        "- fetch_url: Bir web sayfasını getirir. argument = URL.\n"
        "- search_docs: Harici bir kütüphanenin resmi dokümanını arar. "
        'argument = "<kütüphane> <konu>".\n'
        "- final_answer: Kullanıcıya verilecek son yanıt. argument = yanıt metni "
        "(Türkçe, kaynak belirterek; teknik 'nasıl' sorularında kısa bir kod örneğiyle).\n\n"
        "Kurallar: Proje, Sidar, ajanlar, yapılandırma veya repodaki dosyalar hakkındaki "
        "sorularda önce docs_search kullan. Web aramasını yalnızca güncel/dış bilgi "
        "gerektiğinde kullan. final_answer'dan önce en az bir araçla kanıt topla. "
        "Araç sonucu sana geri verildiğinde yeterliyse final_answer ile "
        "yanıtla; uydurma bilgi verme."
    )

    # web/routes/collaboration.py sarmalayıcısı; gerçek kullanıcı komutu bu işaretten sonra gelir.
    _COLLABORATION_COMMAND_MARKER = "Current command:"
    _MAX_TOOL_STEPS = 4
    _WEB_TOOLS = frozenset({"web_search", "fetch_url", "search_docs"})
    # Bu ipuçlarını içeren sorular repo hakkındadır; diğerleri için web kanıtı zorunludur.
    _PROJECT_HINTS = (
        "sidar",
        "proje",
        "repo",
        "depo",
        "agents.md",
        "readme",
        "ajan",
        "agent",
        "yapılandırma",
        "config",
        "docs/",
        ".py",
        ".md",
    )
    _SYNTHESIS_SYSTEM_PROMPT = (
        "Sen bir araştırmacı ajansın. Sana verilen araç sonuçlarını kullanıcı için Türkçe, "
        "kaynaklı ve öz bir yanıta dönüştürürsün. Kod yazma/değiştirme yapmazsın."
    )

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        config: Config | None = None,
    ) -> None:
        """Create the researcher with web search and a RAG document store."""
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
        return str(result)

    async def _tool_fetch_url(self, arg: str) -> str:
        _ok, result = await WebSearchManager.fetch_url(self.web, arg)
        return str(result)

    async def _tool_search_docs(self, arg: str) -> str:
        parts = arg.split(" ", 1)
        lib = parts[0].strip() if parts else ""
        topic = parts[1].strip() if len(parts) > 1 else ""
        _ok, result = await WebSearchManager.search_docs(self.web, lib, topic)
        return str(result)

    async def _tool_docs_search(self, arg: str) -> str:
        session_id = "global"
        try:
            result_obj = await asyncio.to_thread(self.docs.search, arg, None, "auto", session_id)
        except TimeoutError:
            return "Doküman araması zaman aşımına uğradı."
        except Exception as exc:
            return f"Doküman araması şu anda kullanılamıyor: {exc}"
        if inspect.isawaitable(result_obj):
            resolved_result = await result_obj
        else:
            resolved_result = result_obj
        _ok, result = resolved_result
        return str(result)

    @classmethod
    def _extract_command(cls, prompt: str) -> str:
        """Return the user's actual request, dropping the collaboration room wrapper.

        Room context (participants, transcript, write scopes) is useful for the LLM but
        must never become a search query.
        """
        marker = cls._COLLABORATION_COMMAND_MARKER
        if prompt.lstrip().startswith("[COLLABORATION WORKSPACE]") and marker in prompt:
            command = prompt.rsplit(marker, 1)[1].strip()
            if command:
                return command
        return prompt

    @classmethod
    def _is_project_question(cls, query: str) -> bool:
        """Return True when the question is about this repository rather than general knowledge."""
        lowered = query.lower()
        return any(hint in lowered for hint in cls._PROJECT_HINTS)

    @staticmethod
    def _web_evidence_turn(query: str, observation: str) -> str:
        """Feed forced web results back with the instructions for a sourced final answer."""
        return (
            f"Araç sonucu (web_search):\n{observation[:4000]}\n\n"
            "Bu dış kaynak sonuçlarına dayanarak final_answer ile Türkçe yanıtla: kısa "
            "açıklama, teknik sorularda kısa bir kod örneği ve kaynak URL'leri.\n"
            f"Asıl soru: {query}"
        )

    @staticmethod
    def _grounding_request(query: str) -> str:
        """Build the follow-up asking the model to gather evidence before answering."""
        return (
            "Henüz hiçbir araçla kanıt toplamadan yanıt verdin. Önce docs_search (proje "
            "soruları) veya web_search (dış/güncel bilgi) ile kaynak topla; final_answer'ı "
            "bu sonuçlara dayanarak, kaynak URL'lerini belirterek ve teknik sorularda kısa "
            f"bir kod örneğiyle ver.\nAsıl soru: {query}"
        )

    async def _search_local_docs(self, query: str) -> tuple[bool, str]:
        """Search the local RAG store and report whether it produced usable results."""
        session_id = "global"
        try:
            result_obj: Any = await asyncio.to_thread(
                self.docs.search, query, None, "auto", session_id
            )
            if inspect.isawaitable(result_obj):
                result_obj = await result_obj
            ok, result = result_obj
        except Exception:
            return False, ""
        text = str(result).strip()
        return bool(ok) and bool(text), text

    async def _fallback_answer(self, query: str) -> str:
        """Prefer local project knowledge; use the web only when RAG has nothing."""
        ok, docs_result = await self._search_local_docs(query)
        if ok:
            return docs_result
        return str(await self.call_tool("web_search", query))

    async def run_task(self, task_prompt: str) -> str:
        """Handle a research task: run a ``tool|arg`` command or search and summarize."""
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş araştırma görevi verildi."

        query = self._extract_command(prompt)
        lower = query.lower()
        if lower.startswith("fetch_url|"):
            return str(await self.call_tool("fetch_url", query.split("|", 1)[1].strip()))
        if lower.startswith("search_docs|"):
            return str(await self.call_tool("search_docs", query.split("|", 1)[1].strip()))
        if lower.startswith("docs_search|"):
            return str(await self.call_tool("docs_search", query.split("|", 1)[1].strip()))

        # The original task stays in the conversation so every step still knows the goal.
        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
        last_observation = ""
        grounding_requested = False
        web_used = False
        web_forced = False
        project_question = self._is_project_question(query)
        for _ in range(self._MAX_TOOL_STEPS):
            try:
                decision = await self.call_llm(messages=messages, temperature=0.1, json_mode=True)
            except Exception:
                break
            try:
                parsed = json.loads(str(decision))
            except (TypeError, ValueError, json.JSONDecodeError):
                break
            if not isinstance(parsed, dict):
                break
            tool = str(parsed.get("tool", "")).strip().lower()
            argument = str(parsed.get("argument", "")).strip()
            if tool in ("", "final_answer"):
                if not project_question and not web_used and not web_forced:
                    # Genel/dış sorularda model web yerine yerel dokümanları seçip "bilgi
                    # bulunamadı" diyebiliyor; yanıtı kabul etmeden önce web kanıtı topla.
                    web_forced = web_used = True
                    last_observation = str(await self.call_tool("web_search", query))
                    messages.append({"role": "assistant", "content": str(decision)})
                    messages.append(
                        {
                            "role": "user",
                            "content": self._web_evidence_turn(query, last_observation),
                        }
                    )
                    continue
                if not last_observation and not grounding_requested:
                    # Küçük yerel modeller aramadan ezberden yanıt veriyor; kaynaksız ilk
                    # final_answer'ı bir kez geri çevirip önce kanıt toplamasını iste.
                    grounding_requested = True
                    messages.append({"role": "assistant", "content": str(decision)})
                    messages.append({"role": "user", "content": self._grounding_request(query)})
                    continue
                final_answer = argument or str(parsed.get("content", "")).strip()
                if final_answer:
                    return final_answer
                break
            if tool not in self.tools:
                break
            last_observation = str(await self.call_tool(tool, argument or query))
            web_used = web_used or tool in self._WEB_TOOLS
            messages.append({"role": "assistant", "content": str(decision)})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Araç sonucu ({tool}):\n{last_observation[:4000]}\n\n"
                        f"Asıl soru: {query}\n"
                        "Bu sonuç yeterliyse final_answer ile yanıtla, değilse başka bir araç seç."
                    ),
                }
            )

        if last_observation:
            # Model kanıt topladı ama özetleyemedi (bozuk JSON, boş final_answer veya bütçe
            # bitti); ham arama çıktısını basmak yerine araçsız bir özet turu iste.
            summary = await self._synthesize_answer(messages, query)
            return summary or last_observation
        return await self._fallback_answer(query)

    async def _synthesize_answer(self, messages: list[dict[str, str]], query: str) -> str:
        """Ask for a plain-text answer built from the tool results already in ``messages``.

        Returns an empty string when the model fails or still replies with a tool call, so
        the caller can fall back to the raw observation.
        """
        request = {
            "role": "user",
            "content": (
                "Araç çağrısı yapma ve JSON döndürme. Yukarıdaki araç sonuçlarına dayanarak "
                "soruyu Türkçe, düz metin olarak yanıtla: kısa bir açıklama, teknik sorularda "
                "kısa bir kod örneği ve sonunda kullandığın kaynak URL'leri. Sonuçlarda olmayan "
                f"bilgiyi uydurma.\nAsıl soru: {query}"
            ),
        }
        try:
            text = str(
                await self.call_llm(
                    messages=[*messages, request],
                    system_prompt=self._SYNTHESIS_SYSTEM_PROMPT,
                    temperature=0.2,
                    json_mode=False,
                )
            ).strip()
        except Exception:
            return ""
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return text
        if not isinstance(parsed, dict):
            return text
        if str(parsed.get("tool", "")).lower() == "final_answer":
            return str(parsed.get("argument") or parsed.get("content") or "").strip()
        return ""
