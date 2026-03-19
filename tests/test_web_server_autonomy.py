import asyncio
import json
import types

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


def test_autonomy_webhook_dispatches_trigger_to_agent():
    mod = _load_web_server()

    async def _respond(prompt):
        yield f"handled:{prompt}"

    agent = types.SimpleNamespace(respond=_respond)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    mod.cfg.ENABLE_EVENT_WEBHOOKS = True
    mod.cfg.AUTONOMY_WEBHOOK_SECRET = ""

    request = _FakeRequest(
        method="POST",
        path="/api/autonomy/webhook/github",
        body_bytes=json.dumps({"event_name": "push", "branch": "main"}).encode("utf-8"),
    )

    response = asyncio.run(mod.autonomy_webhook("github", request, ""))

    assert response.content["success"] is True
    assert response.content["result"]["source"] == "webhook:github"
    assert "handled:[TRIGGER]" in response.content["result"]["summary"]


def test_swarm_federation_execute_returns_structured_result():
    mod = _load_web_server()

    async def _respond(prompt):
        yield f"federated:{prompt}"

    agent = types.SimpleNamespace(respond=_respond)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    mod.cfg.ENABLE_SWARM_FEDERATION = True
    mod.cfg.SWARM_FEDERATION_SHARED_SECRET = ""

    req = mod._FederationTaskRequest(
        task_id="fed-1",
        source_system="autogen",
        source_agent="coordinator",
        target_agent="supervisor",
        goal="PR inceleme özeti üret",
        intent="review",
        context={"repo": "Sidar"},
        inputs=["PR #7"],
        meta={"priority": "high"},
    )

    response = asyncio.run(mod.swarm_federation_execute(req, ""))

    assert response.content["success"] is True
    result = response.content["result"]
    assert result["task_id"] == "fed-1"
    assert result["source_system"] == "sidar"
    assert result["target_system"] == "autogen"
    assert "federated:[FEDERATION TASK]" in result["summary"]