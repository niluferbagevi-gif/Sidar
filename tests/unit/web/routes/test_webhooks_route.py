from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from web.routes.webhooks import (
    _coerce_bool,
    _github_webhook_signature_required,
    _validate_github_webhook_signature,
    build_webhooks_router,
)


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str, *args: Any) -> None:
        self.warnings.append(message % args if args else message)


def test_github_webhook_signature_required_defaults_to_secure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SIDAR_ENV", raising=False)

    assert _github_webhook_signature_required(SimpleNamespace()) is True
    assert (
        _github_webhook_signature_required(
            SimpleNamespace(GITHUB_WEBHOOK_REQUIRE_SIGNATURE="false")
        )
        is False
    )


def test_github_webhook_signature_required_forces_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")

    assert (
        _github_webhook_signature_required(SimpleNamespace(GITHUB_WEBHOOK_REQUIRE_SIGNATURE=False))
        is True
    )


def test_validate_github_webhook_signature_bypasses_when_secret_missing() -> None:
    calls: list[tuple[Any, ...]] = []
    logger = _Logger()

    _validate_github_webhook_signature(
        payload_body=b"{}",
        cfg=SimpleNamespace(GITHUB_WEBHOOK_SECRET=""),
        signature_header="",
        verify_hmac_signature=lambda *args, **kwargs: calls.append((*args, kwargs)),
        logger=logger,
    )

    assert calls == []
    assert any("GITHUB_WEBHOOK_SECRET" in warning for warning in logger.warnings)


def test_validate_github_webhook_signature_can_bypass_for_local_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDAR_ENV", "testing")
    calls: list[tuple[Any, ...]] = []
    logger = _Logger()

    _validate_github_webhook_signature(
        payload_body=b"{}",
        cfg=SimpleNamespace(
            GITHUB_WEBHOOK_SECRET="secret",
            GITHUB_WEBHOOK_REQUIRE_SIGNATURE=False,
        ),
        signature_header="",
        verify_hmac_signature=lambda *args, **kwargs: calls.append((*args, kwargs)),
        logger=logger,
    )

    assert calls == []
    assert any("GITHUB_WEBHOOK_REQUIRE_SIGNATURE=False" in warning for warning in logger.warnings)


def test_validate_github_webhook_signature_delegates_to_shared_hmac_verifier() -> None:
    calls: list[tuple[Any, ...]] = []

    _validate_github_webhook_signature(
        payload_body=b"{}",
        cfg=SimpleNamespace(GITHUB_WEBHOOK_SECRET="secret"),
        signature_header="sha256=ok",
        verify_hmac_signature=lambda *args, **kwargs: calls.append((*args, kwargs)),
        logger=_Logger(),
    )

    assert calls == [(b"{}", "secret", "sha256=ok", {"label": "GitHub webhook"})]


def test_validate_github_webhook_signature_preserves_verifier_http_errors() -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=401, detail="Geçersiz imza.")

    with pytest.raises(HTTPException) as exc_info:
        _validate_github_webhook_signature(
            payload_body=b"{}",
            cfg=SimpleNamespace(GITHUB_WEBHOOK_SECRET="secret"),
            signature_header="sha256=bad",
            verify_hmac_signature=_raise,
            logger=_Logger(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Geçersiz imza."


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        (" false ", False),
        ("enabled", True),
        ("off", False),
        ("unknown", True),
    ],
)
def test_coerce_bool_handles_text_values_and_defaults(value: str, expected: bool) -> None:
    assert _coerce_bool(value, default=True) is expected


@pytest.mark.asyncio
async def test_github_webhook_wraps_non_dict_json_payload() -> None:
    memory_entries: list[tuple[str, str]] = []

    class _Req:
        async def body(self) -> bytes:
            return b'["non-dict"]'

    async def _resolve_agent():
        return SimpleNamespace(
            memory=SimpleNamespace(add=lambda role, message: memory_entries.append((role, message)))
        )

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

    response = await router.legacy_exports["github_webhook"](
        _Req(), x_github_event="push", x_hub_signature_256=""
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200
    assert memory_entries
    assert "dalına yeni kod yükledi" in memory_entries[0][1]
