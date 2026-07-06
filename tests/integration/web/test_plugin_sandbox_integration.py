"""Integration coverage for plugin sandbox registration paths.

Smoke boot tests only prove that the app starts. Plugin registration executes
untrusted admin-supplied source through the shared sandbox and then wires the
resulting class into ``AgentCatalog``; that path needs integration coverage so
production readiness is not inferred from smoke success alone.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_server
from agent.registry import AgentCatalog


@pytest.mark.integration
def test_plugin_sandbox_registers_agent_and_blocks_forbidden_imports() -> None:
    """Register a sandboxed plugin agent and reject an unsafe import in the same path."""

    role_name = "integration_plugin_sandbox_agent"
    AgentCatalog.unregister(role_name)
    source = """
from agent.base_agent import BaseAgent

class IntegrationPluginAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        return f"plugin-ok:{task_prompt}"
"""

    try:
        result = web_server._register_plugin_agent(
            role_name=role_name,
            source_code=source,
            class_name="IntegrationPluginAgent",
            capabilities=["plugin_sandbox_integration"],
            description="Integration plugin sandbox agent",
            version="1.0.0",
        )

        spec = AgentCatalog.get(role_name)
        agent = AgentCatalog.create(role_name, cfg=SimpleNamespace(AI_PROVIDER="ollama"))

        assert result["role_name"] == role_name
        assert result["is_builtin"] is False
        assert spec is not None
        assert spec.is_builtin is False
        assert "plugin_sandbox_integration" in spec.capabilities
        assert agent.role_name == "base"

        with pytest.raises(HTTPException) as exc_info:
            web_server._run_plugin_source_in_sandbox(
                "import os\nVALUE = os.environ\n", "integration_plugin_rejected"
            )
        assert exc_info.value.status_code == 400
        assert "Plugin güvenlik politikası" in str(exc_info.value.detail)
    finally:
        AgentCatalog.unregister(role_name)
