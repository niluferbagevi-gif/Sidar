from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from web.routes import health_runtime


class _Logger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, tuple[object, ...]]] = []

    def exception(self, msg: str, *args: object) -> None:
        self.messages.append((msg, args))


class _Health:
    def __init__(self) -> None:
        self.dependency_health = {"postgres": {"healthy": True}}

    def get_health_summary(self) -> dict[str, object]:
        return {"status": "ok", "ollama_online": True}

    def get_dependency_health(self) -> dict[str, dict[str, bool]]:
        return self.dependency_health

    def check_ollama(self) -> bool:
        return True

    def get_gpu_info(self) -> dict[str, object]:
        return {"name": "test-gpu"}


@pytest.mark.asyncio
async def test_build_health_response_adds_dependency_status() -> None:
    agent = SimpleNamespace(cfg=SimpleNamespace(AI_PROVIDER="openai"), health=_Health())

    async def resolve_agent() -> object:
        return agent

    response = await health_runtime.build_health_response(
        require_dependencies=True,
        resolve_agent_instance=resolve_agent,
        expose_details=lambda: False,
        logger=_Logger(),
        start_time=0.0,
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["status"] == "ok"
    assert payload["dependencies"] == {"postgres": {"healthy": True}}
    assert isinstance(payload["uptime_seconds"], int)


@pytest.mark.asyncio
async def test_build_health_response_hides_exception_details_by_default() -> None:
    async def resolve_agent() -> object:
        raise RuntimeError("secret-detail")

    logger = _Logger()
    response = await health_runtime.build_health_response(
        resolve_agent_instance=resolve_agent,
        expose_details=lambda: False,
        logger=logger,
        start_time=0.0,
    )

    assert response.status_code == 503
    payload = json.loads(response.body)
    assert payload["error"] == "health_check_failed"
    assert "detail" not in payload
    assert logger.messages


def test_domain_config_loaders_preserve_defaults() -> None:
    from core.config_app import load_app_runtime_settings
    from core.config_observability import load_observability_settings
    from core.config_orchestrator import load_orchestrator_settings

    app_settings = load_app_runtime_settings()
    observability_settings = load_observability_settings()
    orchestrator_settings = load_orchestrator_settings()

    assert app_settings.project_name == "Sidar"
    assert observability_settings.otel_service_name
    assert orchestrator_settings.max_react_steps >= 1
