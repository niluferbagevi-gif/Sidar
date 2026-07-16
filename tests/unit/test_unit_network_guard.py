"""Regression tests for the unit-suite real network guard."""

from __future__ import annotations

import socket

import pytest

from tests.unit.conftest import UnitTestNetworkAccessError


def test_unit_network_guard_blocks_socket_connect() -> None:
    """A raw unit-test socket connection fails in the originating test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(UnitTestNetworkAccessError, match="Blocked endpoint: 127.0.0.1:9"):
            sock.connect(("127.0.0.1", 9))


def test_unit_network_guard_blocks_socket_create_connection() -> None:
    """Synchronous client helpers are blocked before they open a socket."""
    with pytest.raises(UnitTestNetworkAccessError, match="socket.create_connection"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)
