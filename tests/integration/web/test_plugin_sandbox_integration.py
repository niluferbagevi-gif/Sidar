"""Integration coverage for plugin sandbox registration paths.

Smoke boot tests only prove that the app starts. Plugin registration executes
untrusted admin-supplied source through the shared sandbox and then wires the
resulting class into ``AgentCatalog``; that path needs integration coverage so
production readiness is not inferred from smoke success alone.

The plugin sandbox backend defaults to Docker in every environment
(``SEC-PLUGIN-001``, ``web/plugins/sandbox.py:plugin_sandbox_backend``), so
this test exercises a real Docker daemon and the built
``SIDAR_PLUGIN_SANDBOX_IMAGE`` (default ``sidar:latest``), same as
``test_plugin_sandbox_container_escape.py``. ``make dev-full``/``make
base-quality-gates`` (and therefore CI's "Run base quality gates" step and
``make production-readiness``) build that image automatically
(``AUTO_BUILD_DOCKER_TEST_IMAGE=1``) *before* this module is collected, so it
runs for real -- never skipped -- on every path that matters for release
readiness. That Makefile fix is the actual defense; the skip guard below is
only a secondary safety net for ad-hoc runs that bypass it entirely (e.g.
``pytest tests/integration/web/test_plugin_sandbox_integration.py`` on its
own, without ``make``/``run_tests.sh``) where the image may not exist yet --
without the guard, a missing image turns into an opaque
``PluginSandboxError``/``HTTPException(503)`` instead of a clear skip. It is
deliberately *not* wired into ``make plugin-sandbox-security`` or CI's
dedicated container-escape enforcement step the way
``test_plugin_sandbox_container_escape.py`` is: unlike that module, this one
imports ``web_server`` and depends on the full test environment
(config/secret env vars) that only ``run_tests.sh`` sets up, so forcing it
into that lean, Docker-only target would trade a Docker-availability failure
mode for an unrelated environment-config one. Anyone who wants a hard failure
instead of a skip for an ad-hoc run can still opt in directly with
``SIDAR_REQUIRE_PLUGIN_SANDBOX_CONTAINER_TESTS=1``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import web_server
from agent.registry import AgentCatalog
from tests._helpers.docker_sandbox import require_or_skip_reason
from web.plugins.sandbox import DockerPluginSandboxBackend

_TARGET_IMAGE = DockerPluginSandboxBackend().image
_IMAGE_READY, _SKIP_REASON = require_or_skip_reason(_TARGET_IMAGE)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(not _IMAGE_READY, reason=_SKIP_REASON),
]


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
