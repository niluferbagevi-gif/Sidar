"""Contract tests for the route request-model boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from web.routes import request_models


def test_swarm_execute_request_builds_typed_tasks() -> None:
    payload = request_models.SwarmExecuteRequest(
        mode="pipeline",
        tasks=[{"goal": "Review", "intent": "review"}],
        max_concurrency=2,
    )

    assert payload.mode == "pipeline"
    assert payload.tasks == [request_models.SwarmTaskRequest(goal="Review", intent="review")]
    assert payload.max_concurrency == 2


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (request_models.RegisterRequest, {"username": "user", "password": "pw", "tenant_id": ""}),
        (request_models.PromptActivateRequest, {"prompt_id": 0}),
        (request_models.PluginMarketplaceInstallRequest, {"plugin_id": "x"}),
        (request_models.SwarmExecuteRequest, {"mode": "serial", "tasks": [{"goal": "Run"}]}),
    ],
)
def test_request_models_reject_invalid_route_payloads(
    model: type, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)
