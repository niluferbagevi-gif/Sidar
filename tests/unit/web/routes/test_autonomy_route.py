from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from web.routes.autonomy import (
    _autonomy_webhook_secret,
    _autonomy_webhook_signature_required,
    _coerce_bool,
    _require_autonomy_admin,
    _validate_autonomy_webhook_signature,
    configure_autonomy_dependencies,
    router,
)


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (None, True, True),
        (None, False, False),
        (True, False, True),
        (False, True, False),
        ("enabled", False, True),
        ("yes", False, True),
        ("disabled", True, False),
        ("off", True, False),
        ("garbage", True, True),
        ("garbage", False, False),
    ],
)
def test_coerce_bool_handles_known_values_and_unknown_defaults(
    value: object, default: bool, expected: bool
) -> None:
    assert _coerce_bool(value, default=default) is expected


def test_autonomy_webhook_secret_supports_sidar_alias() -> None:
    assert _autonomy_webhook_secret(SimpleNamespace(AUTONOMY_WEBHOOK_SECRET="direct")) == "direct"
    assert (
        _autonomy_webhook_secret(SimpleNamespace(SIDAR_AUTONOMY_WEBHOOK_SECRET="legacy"))
        == "legacy"
    )


def test_autonomy_wake_declares_admin_dependency() -> None:
    route = next(route for route in router.routes if route.path == "/api/autonomy/wake")

    assert any(
        dependency.call is _require_autonomy_admin for dependency in route.dependant.dependencies
    )


def test_require_autonomy_admin_delegates_authenticated_request_user() -> None:
    admin = SimpleNamespace(id="admin-1", role="admin")
    calls: list[Any] = []
    configure_autonomy_dependencies(
        lambda: SimpleNamespace(
            require_admin_user=lambda user: calls.append(user) or admin,
        )
    )
    request = SimpleNamespace(state=SimpleNamespace(user=admin))

    assert _require_autonomy_admin(request) is admin
    assert calls == [admin]


def test_autonomy_webhook_signature_required_defaults_to_secure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SIDAR_ENV", raising=False)

    assert _autonomy_webhook_signature_required(SimpleNamespace()) is True
    assert (
        _autonomy_webhook_signature_required(
            SimpleNamespace(AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE="false")
        )
        is False
    )


def test_autonomy_webhook_signature_required_forces_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDAR_ENV", "production")

    assert (
        _autonomy_webhook_signature_required(
            SimpleNamespace(AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE=False)
        )
        is True
    )


def test_validate_autonomy_webhook_signature_fails_closed_when_nonproduction_secret_missing() -> (
    None
):
    calls: list[tuple[Any, ...]] = []

    with pytest.raises(HTTPException) as exc_info:
        _validate_autonomy_webhook_signature(
            payload_body=b"{}",
            cfg=SimpleNamespace(AUTONOMY_WEBHOOK_SECRET="", SIDAR_ENV="testing"),
            signature_header="",
            verify_hmac_signature=lambda *args, **kwargs: calls.append((*args, kwargs)),
        )

    assert exc_info.value.status_code == 401
    assert "Autonomy webhook secret" in str(exc_info.value.detail)
    assert calls == []


def test_validate_autonomy_webhook_signature_fails_closed_in_production_without_secret() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_autonomy_webhook_signature(
            payload_body=b"{}",
            cfg=SimpleNamespace(AUTONOMY_WEBHOOK_SECRET="", SIDAR_ENV="production"),
            signature_header="",
            verify_hmac_signature=lambda *_args, **_kwargs: None,
        )

    assert exc_info.value.status_code == 401
    assert "Autonomy webhook secret" in str(exc_info.value.detail)


def test_validate_autonomy_webhook_signature_can_bypass_for_local_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDAR_ENV", "testing")
    calls: list[tuple[Any, ...]] = []

    _validate_autonomy_webhook_signature(
        payload_body=b"{}",
        cfg=SimpleNamespace(
            AUTONOMY_WEBHOOK_SECRET="secret",
            AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE=False,
        ),
        signature_header="",
        verify_hmac_signature=lambda *args, **kwargs: calls.append((*args, kwargs)),
    )

    assert calls == []


def test_validate_autonomy_webhook_signature_delegates_to_shared_hmac_verifier() -> None:
    calls: list[tuple[Any, ...]] = []

    _validate_autonomy_webhook_signature(
        payload_body=b"{}",
        cfg=SimpleNamespace(AUTONOMY_WEBHOOK_SECRET="secret"),
        signature_header="sha256=ok",
        delivery_id="delivery-1",
        verify_hmac_signature=lambda *args, **kwargs: calls.append((*args, kwargs)),
    )

    assert calls == [
        (
            b"{}",
            "secret",
            "sha256=ok",
            {"label": "Autonomy webhook", "replay_key": "delivery-1"},
        )
    ]


def test_validate_autonomy_webhook_signature_rejects_missing_delivery_id() -> None:
    calls: list[tuple[Any, ...]] = []

    with pytest.raises(HTTPException) as exc_info:
        _validate_autonomy_webhook_signature(
            payload_body=b"{}",
            cfg=SimpleNamespace(AUTONOMY_WEBHOOK_SECRET="secret"),
            signature_header="sha256=ok",
            delivery_id="",
            verify_hmac_signature=lambda *args, **kwargs: calls.append((*args, kwargs)),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Autonomy webhook delivery kimliği eksik."
    assert calls == []


def test_validate_autonomy_webhook_signature_preserves_verifier_http_errors() -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=401, detail="Autonomy webhook imza başlığı eksik.")

    with pytest.raises(HTTPException) as exc_info:
        _validate_autonomy_webhook_signature(
            payload_body=b"{}",
            cfg=SimpleNamespace(AUTONOMY_WEBHOOK_SECRET="secret"),
            signature_header="",
            delivery_id="delivery-bad",
            verify_hmac_signature=_raise,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Autonomy webhook imza başlığı eksik."
