import asyncio
import json
import types

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


def test_autonomy_webhook_dispatches_trigger_to_agent():
    mod = _load_web_server()

    async def _handle_trigger(trigger):
        return {
            "trigger_id": trigger.trigger_id,
            "source": trigger.source,
            "event_name": trigger.event_name,
            "summary": f"handled:{trigger.to_prompt()}",
            "status": "success",
            "meta": dict(trigger.meta),
            "created_at": 1.0,
            "completed_at": 2.0,
        }

    agent = types.SimpleNamespace(handle_external_trigger=_handle_trigger)

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
    assert response.content["result"]["status"] == "success"


def test_autonomy_wake_and_activity_return_structured_payloads():
    mod = _load_web_server()

    async def _handle_trigger(trigger):
        return {
            "trigger_id": trigger.trigger_id,
            "source": trigger.source,
            "event_name": trigger.event_name,
            "summary": f"wake:{trigger.payload.get('prompt', '')}",
            "status": "success",
            "meta": dict(trigger.meta),
            "created_at": 10.0,
            "completed_at": 11.0,
        }

    agent = types.SimpleNamespace(
        handle_external_trigger=_handle_trigger,
        get_autonomy_activity=lambda limit=20: {
            "items": [{"trigger_id": "t-1", "source": "manual:ops", "event_name": "manual_wake", "status": "success"}],
            "total": 1,
            "returned": 1,
            "counts_by_status": {"success": 1},
            "counts_by_source": {"manual:ops": 1},
            "latest_trigger_id": "t-1",
        },
    )

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    wake_req = mod._AutonomyWakeRequest(
        event_name="manual_wake",
        prompt="CI pipeline failure sinyalini değerlendir",
        source="ops",
        payload={"pipeline": "build"},
        meta={"priority": "high"},
    )
    wake_response = asyncio.run(mod.autonomy_wake(wake_req))
    activity_response = asyncio.run(mod.autonomy_activity(limit=5))

    assert wake_response.content["success"] is True
    assert wake_response.content["result"]["source"] == "manual:ops"
    assert "CI pipeline failure" in wake_response.content["result"]["summary"]
    assert activity_response.content["success"] is True
    assert activity_response.content["activity"]["counts_by_status"]["success"] == 1


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


def test_github_webhook_ci_failure_dispatches_remediation_trigger():
    mod = _load_web_server()
    captured = {}

    async def _handle_trigger(trigger):
        captured["source"] = trigger.source
        captured["event_name"] = trigger.event_name
        captured["payload"] = dict(trigger.payload or {})
        return {
            "trigger_id": trigger.trigger_id,
            "source": trigger.source,
            "event_name": trigger.event_name,
            "summary": "ci remediation scheduled",
            "status": "success",
            "meta": dict(trigger.meta),
            "created_at": 1.0,
            "completed_at": 2.0,
            "remediation": {"pr_proposal": {"title": "CI remediation: stabilize CI"}},
        }

    async def _get_agent():
        return types.SimpleNamespace(
            handle_external_trigger=_handle_trigger,
            memory=types.SimpleNamespace(add=lambda *_args, **_kwargs: None),
        )

    mod.get_agent = _get_agent
    mod.cfg.GITHUB_WEBHOOK_SECRET = ""
    mod.cfg.ENABLE_EVENT_WEBHOOKS = True

    body = json.dumps(
        {
            "repository": {"full_name": "acme/sidar", "default_branch": "main"},
            "workflow_run": {
                "id": 88,
                "run_number": 3,
                "name": "CI",
                "status": "completed",
                "conclusion": "failure",
                "head_branch": "feature/failing",
                "head_sha": "deadbeef",
                "html_url": "https://github.com/acme/sidar/actions/runs/88",
                "jobs_url": "https://github.com/acme/sidar/actions/runs/88/jobs",
                "logs_url": "https://github.com/acme/sidar/actions/runs/88/logs",
                "display_title": "pytest failure",
            },
        }
    ).encode("utf-8")
    request = _FakeRequest(method="POST", path="/api/webhook", body_bytes=body)

    response = asyncio.run(mod.github_webhook(request, "workflow_run", ""))

    assert response.content["success"] is True
    assert captured["source"] == "webhook:github:ci_failure"
    assert captured["event_name"] == "ci_failure_remediation"
    assert captured["payload"]["workflow_name"] == "CI"
    assert captured["payload"]["logs_url"].endswith("/88/logs")
