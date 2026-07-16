"""Unit-test specific pytest guards."""

from __future__ import annotations

import socket
from collections.abc import Generator
from typing import Any

import pytest


class UnitTestNetworkAccessError(AssertionError):
    """Raised when a unit test attempts to open a real network socket."""


def _format_blocked_endpoint(address: object) -> str:
    """Return a stable human-readable endpoint for socket guard failures."""
    if isinstance(address, tuple) and address:
        host = address[0]
        port = address[1] if len(address) > 1 else "?"
        return f"{host}:{port}"
    return repr(address)


@pytest.fixture(autouse=True)
def _block_real_network_in_unit_tests(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Generator[None, None, None]:
    """Fail unit tests at the call site when they try to open a real socket.

    The project treats warnings as errors, so leaked httpx/anyio connection
    attempts can otherwise be reported later as ``PytestUnraisableExceptionWarning``
    against an unrelated neighboring test. Unit tests must mock HTTP clients
    (for example with respx/fakes) instead of touching real network endpoints.
    Integration, smoke, and e2e tests keep their normal network behavior because
    this fixture is scoped to ``tests/unit``.
    """
    if request.node.get_closest_marker("allow_unit_network") is not None:
        yield
        return

    original_socket_connect = socket.socket.connect
    original_socket_connect_ex = socket.socket.connect_ex

    def _blocked_connect(self: socket.socket, address: object) -> None:
        raise UnitTestNetworkAccessError(
            "Unit tests may not open real network sockets; mock the client or "
            "move the scenario to an integration/smoke/e2e test. "
            f"Blocked endpoint: {_format_blocked_endpoint(address)}"
        )

    def _blocked_connect_ex(self: socket.socket, address: object) -> int:
        _blocked_connect(self, address)
        return 1

    def _blocked_create_connection(
        address: object,
        timeout: float | object = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> socket.socket:
        raise UnitTestNetworkAccessError(
            "Unit tests may not open real network sockets via "
            "socket.create_connection; mock the client or move the scenario to "
            "an integration/smoke/e2e test. "
            f"Blocked endpoint: {_format_blocked_endpoint(address)}"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connect_ex)
    monkeypatch.setattr(socket, "create_connection", _blocked_create_connection)
    try:
        yield
    finally:
        # Restore explicitly before monkeypatch teardown so late finalizers in the
        # same test do not inherit a half-restored socket module state.
        monkeypatch.setattr(socket.socket, "connect", original_socket_connect)
        monkeypatch.setattr(socket.socket, "connect_ex", original_socket_connect_ex)
