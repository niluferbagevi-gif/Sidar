"""Unit tests for core/utils/trusted_urlopen.py.

See that module's docstring for why it exists: it centralizes the
unavoidable Bandit B310 suppression for internally-trusted
``urllib.request.urlopen`` calls into one reviewed spot instead of one
per call site. These tests pin its minimal safety contract (reject
non-http(s) schemes) and that it otherwise forwards faithfully to
``urllib.request.urlopen``.
"""

from __future__ import annotations

import urllib.request
from types import SimpleNamespace

import pytest

import core.utils.trusted_urlopen as trusted_urlopen
from core.utils.trusted_urlopen import UntrustedRequestError, urlopen_trusted_request


def test_urlopen_trusted_request_forwards_to_urlopen_and_returns_its_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Unit tests must not open real sockets (see tests/unit/conftest.py's
    # network guard); mock the real urllib.request.urlopen call directly
    # rather than standing up a live HTTP server.
    calls: list[tuple[urllib.request.Request, float]] = []
    fake_response = SimpleNamespace(status=200, read=lambda: b"hello")

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> SimpleNamespace:
        calls.append((request, timeout))
        return fake_response

    monkeypatch.setattr(trusted_urlopen.urllib.request, "urlopen", fake_urlopen)

    request = urllib.request.Request("https://sidar.example.test/")
    response = urlopen_trusted_request(request, timeout=5)

    assert response is fake_response
    assert calls == [(request, 5)]


def test_urlopen_trusted_request_rejects_file_scheme() -> None:
    request = urllib.request.Request("file:///etc/passwd")
    with pytest.raises(UntrustedRequestError, match="scheme"):
        urlopen_trusted_request(request, timeout=5)


def test_urlopen_trusted_request_rejects_ftp_scheme() -> None:
    request = urllib.request.Request("ftp://example.test/")
    with pytest.raises(UntrustedRequestError, match="scheme"):
        urlopen_trusted_request(request, timeout=5)


def test_urlopen_trusted_request_rejects_scheme_before_dialing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheme guard must reject before urlopen is ever reached."""

    def _fail_if_called(*_args: object, **_kwargs: object) -> None:
        pytest.fail("urlopen must not run for a rejected scheme")

    monkeypatch.setattr(trusted_urlopen.urllib.request, "urlopen", _fail_if_called)

    request = urllib.request.Request("file:///etc/passwd")
    with pytest.raises(UntrustedRequestError):
        urlopen_trusted_request(request, timeout=5)
