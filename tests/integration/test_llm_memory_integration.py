"""LLM çıktısının bellek katmanına yazım entegrasyonu."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent.base_agent import BaseAgent
from core.db import Database
from agent.core.memory_hub import MemoryHub


class _LLMMemoryAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        answer = await self.call_llm([
            {"role": "user", "content": task_prompt},
        ])
        return answer


def _build_cfg(tmp_path: Path):
    return SimpleNamespace(
        AI_PROVIDER="ollama",
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'llm_memory.db'}",
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=3,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET="integration-secret",
        JWT_ALGORITHM="HS256",
    )


def test_agent_receives_llm_answer_and_persists_to_memory_layers(tmp_path):
    cfg = _build_cfg(tmp_path)

    async def _run_case() -> None:
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="Yanıt: build geçti")

        with patch("agent.base_agent.LLMClient", return_value=fake_llm):
            agent = _LLMMemoryAgent(cfg=cfg, role_name="integration")

        memory_hub = MemoryHub()
        db = Database(cfg)
        try:
            await db.connect()
            await db.init_schema()
            user = await db.create_user("llm_memory_user", password="secret")
            session = await db.create_session(user.id, "LLM memory integration")

            output = await agent.run_task("CI durumunu özetle")
            memory_hub.add_role_note("integration", output)
            await db.add_message(session.id, "assistant", output)

            role_notes = memory_hub.role_context("integration")
            messages = await db.get_session_messages(session.id)

            assert role_notes[-1] == "Yanıt: build geçti"
            assert messages[-1].content == "Yanıt: build geçti"
            fake_llm.chat.assert_awaited_once()
        finally:
            await db.close()

    asyncio.run(_run_case())
