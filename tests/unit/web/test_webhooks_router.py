from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from web.routes.webhooks import build_webhooks_router


def test_webhooks_router_registers_github_webhook_legacy_export() -> None:
    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(add=lambda *_args: None))

    async def _await_if_needed(value):
        return value

    router = build_webhooks_router(
        cfg=SimpleNamespace(GITHUB_WEBHOOK_SECRET="", ENABLE_EVENT_WEBHOOKS=False),
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None, info=lambda *_args: None),
        resolve_agent_instance=_resolve_agent,
        await_if_needed=_await_if_needed,
        verify_hmac_signature=lambda *_args, **_kwargs: None,
        resolve_ci_failure_context=lambda *_args, **_kwargs: None,
        run_event_driven_federation_workflow=lambda **_kwargs: None,
        embed_event_driven_federation_payload=lambda payload, _workflow: payload,
        dispatch_autonomy_trigger=lambda **_kwargs: {"ok": True},
    )
    app = FastAPI()
    app.include_router(router)

    assert "github_webhook" in router.legacy_exports
    assert str(app.url_path_for("github_webhook")) == "/api/webhook"


@pytest.mark.asyncio
async def test_webhooks_router_legacy_export_reads_dynamic_cfg_getter() -> None:
    class _Req:
        async def body(self) -> bytes:
            return b'{"action":"noop"}'

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(add=lambda *_args: None))

    async def _await_if_needed(value):
        return value

    stale_cfg = SimpleNamespace(GITHUB_WEBHOOK_SECRET="stale-secret", ENABLE_EVENT_WEBHOOKS=True)
    active_cfg = SimpleNamespace(GITHUB_WEBHOOK_SECRET="", ENABLE_EVENT_WEBHOOKS=False)
    verifier_calls = []

    router = build_webhooks_router(
        cfg=stale_cfg,
        cfg_getter=lambda: active_cfg,
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None, info=lambda *_args: None),
        resolve_agent_instance=_resolve_agent,
        await_if_needed=_await_if_needed,
        verify_hmac_signature=lambda *args, **kwargs: verifier_calls.append((args, kwargs)),
        resolve_ci_failure_context=lambda *_args, **_kwargs: None,
        run_event_driven_federation_workflow=lambda **_kwargs: None,
        embed_event_driven_federation_payload=lambda payload, _workflow: payload,
        dispatch_autonomy_trigger=lambda **_kwargs: {"ok": True},
    )

    response = await router.legacy_exports["github_webhook"](
        _Req(), x_github_event="repository", x_hub_signature_256=""
    )

    assert response.status_code == 200
    assert verifier_calls == []
