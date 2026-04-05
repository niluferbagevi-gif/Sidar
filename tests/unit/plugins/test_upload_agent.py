"""Unit tests for UploadAgent plugin."""

from __future__ import annotations

import pytest

from plugins.upload_agent import UploadAgent


@pytest.mark.asyncio
async def test_upload_agent_returns_empty_message_for_blank_prompt() -> None:
    agent = UploadAgent()

    assert await agent.run_task("   ") == "Boş görev alındı."


@pytest.mark.asyncio
async def test_upload_agent_echoes_trimmed_prompt() -> None:
    agent = UploadAgent()

    assert await agent.run_task("  deploy plugin  ") == "UploadAgent: deploy plugin"
