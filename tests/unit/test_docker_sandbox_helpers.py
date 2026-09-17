"""Unit coverage for tests/_helpers/docker_sandbox.py's pure-logic helpers.

These run with no Docker daemon required, unlike the integration modules that
consume them (tests/integration/web/test_plugin_sandbox_container_escape.py,
test_plugin_sandbox_integration.py), which skip entirely without a reachable
daemon and a pre-built target image.
"""

from __future__ import annotations

import pytest

from tests._helpers.docker_sandbox import orphan_cleanup_timeout_seconds


def test_orphan_cleanup_timeout_seconds_defaults_to_sixty(monkeypatch):
    monkeypatch.delenv("SIDAR_SANDBOX_TEST_CLEANUP_TIMEOUT_S", raising=False)
    assert orphan_cleanup_timeout_seconds() == 60.0


def test_orphan_cleanup_timeout_seconds_honors_a_positive_override(monkeypatch):
    monkeypatch.setenv("SIDAR_SANDBOX_TEST_CLEANUP_TIMEOUT_S", "180")
    assert orphan_cleanup_timeout_seconds() == 180.0


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not-a-number", "0", "-5", "-0.1"],
)
def test_orphan_cleanup_timeout_seconds_falls_back_to_default_on_bad_input(monkeypatch, raw):
    """Blank/unparsable/non-positive overrides must never disable the poll budget."""
    monkeypatch.setenv("SIDAR_SANDBOX_TEST_CLEANUP_TIMEOUT_S", raw)
    assert orphan_cleanup_timeout_seconds() == 60.0
