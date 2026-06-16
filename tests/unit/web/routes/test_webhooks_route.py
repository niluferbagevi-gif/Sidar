from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from web.routes.webhooks import (
    _github_webhook_signature_required,
    _validate_github_webhook_signature,
)


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str, *args: Any) -> None:
        self.warnings.append(message % args if args else message)


def test_github_webhook_signature_required_defaults_to_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIDAR_ENV", raising=False)

    assert _github_webhook_signature_required(SimpleNamespace()) is True
    assert (
        _github_webhook_signature_required(
            SimpleNamespace(GITHUB_WEBHOOK_REQUIRE_SIGNATURE="false")
        )
        is False
    )


def test_github_webhook_signature_required_forces_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")

    assert (
        _github_webhook_signature_required(
            SimpleNamespace(GITHUB_WEBHOOK_REQUIRE_SIGNATURE=False)
        )
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
