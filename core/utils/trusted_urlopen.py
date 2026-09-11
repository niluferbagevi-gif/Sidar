"""Centralized, audited wrapper around trusted ``urllib.request.urlopen`` calls.

Bandit's B310 ("urllib_urlopen" / audit url open for permitted schemes)
flags any ``urlopen`` call regardless of how its target URL was
constructed, because it cannot statically prove the scheme stays
restricted to http(s) -- ``file://``/``ftp://``/etc. are handled by the
same call transparently, a genuine SSRF/LFI-adjacent concern when the URL
comes from untrusted input, but a low-signal static warning when it
doesn't. Every call site currently suppressing this finding already
targets a fixed https:// origin (GitHub's REST API, a pinned installer
refresh endpoint) with no attacker-influenced scheme. Centralizing them
here collapses several per-call-site suppressions into one reviewed line,
the same pattern already established for subprocess execution in
``core/utils/trusted_subprocess.py`` -- see that module's docstring for
the fuller rationale.

Routing every internally-trusted HTTP(S) request through the function
below does not change the trust model: each caller remains solely
responsible for ensuring its ``Request`` targets a fixed/trusted origin;
this module does not validate *that*. What it adds is one small,
unconditional safety net (reject any non-http(s) scheme outright) and one
place instead of many for the unavoidable B310 suppression to live.
"""

from __future__ import annotations

import urllib.request
from http.client import HTTPResponse
from typing import cast
from urllib.parse import urlsplit


class UntrustedRequestError(ValueError):
    """Raised when a Request fails this module's minimal safety contract."""


def urlopen_trusted_request(request: urllib.request.Request, *, timeout: float) -> HTTPResponse:
    """Open an internally-constructed, already-trusted HTTP(S) request.

    A thin, audited pass-through to ``urllib.request.urlopen(request,
    timeout=timeout)``. See the module docstring for the trust contract
    this relies on: the caller, not this function, is responsible for
    ``request``'s URL targeting a fixed, trusted origin.
    """
    scheme = urlsplit(request.full_url).scheme
    if scheme not in {"http", "https"}:
        raise UntrustedRequestError(f"unsupported URL scheme: {scheme!r}")
    return cast(
        HTTPResponse,
        urllib.request.urlopen(  # nosec B310  # see module docstring; callers own URL trust.
            request, timeout=timeout
        ),
    )
