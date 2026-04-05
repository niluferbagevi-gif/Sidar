"""Unit tests for UploadAgent plugin."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types

import pytest


class _StubBaseAgent:  # pragma: no cover - helper only
    pass


def _load_upload_agent_module(monkeypatch: pytest.MonkeyPatch):
    """Load plugins.upload_agent with a lightweight BaseAgent stub."""
    base_agent_module = types.ModuleType("agent.base_agent")
    base_agent_module.BaseAgent = _StubBaseAgent

    monkeypatch.setitem(sys.modules, "agent.base_agent", base_agent_module)
    sys.modules.pop("plugins.upload_agent", None)

    return importlib.import_module("plugins.upload_agent")


def test_upload_agent_returns_empty_message_for_blank_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_upload_agent_module(monkeypatch)
    agent = module.UploadAgent()

    result = asyncio.run(agent.run_task("   "))
    assert result == "Boş görev alındı."


def test_upload_agent_echoes_trimmed_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_upload_agent_module(monkeypatch)
    agent = module.UploadAgent()

    result = asyncio.run(agent.run_task("  deploy plugin  "))
    assert result == "UploadAgent: deploy plugin"
