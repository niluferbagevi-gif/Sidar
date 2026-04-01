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
        OLLAMA_URL="http://localhost:11434",
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
        memory_hub = MemoryHub()
        db = Database(cfg)
        try:
            await db.connect()
            await db.init_schema()
            user = await db.create_user("llm_memory_user", password="secret")
            session = await db.create_session(user.id, "LLM memory integration")

            # Mock kapsamı, LLM çağrısı ve tüm doğrulamaları kapsamalıdır.
            with patch("core.llm_client.LLMClient.chat", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = "Yanıt: build geçti"
                agent = _LLMMemoryAgent(cfg=cfg, role_name="integration")

                output = await asyncio.wait_for(agent.run_task("CI durumunu özetle"), timeout=30)
                memory_hub.add_role_note("integration", output)
                await db.add_message(session.id, "assistant", output)

                role_notes = memory_hub.role_context("integration")
                messages = await db.get_session_messages(session.id)

                assert role_notes[-1] == "Yanıt: build geçti"
                assert messages[-1].content == "Yanıt: build geçti"
                mock_chat.assert_awaited_once()
                called_messages = mock_chat.await_args.args[0]
                assert called_messages[-1]["content"] == "CI durumunu özetle"
        finally:
            await db.close()

    asyncio.run(_run_case())
