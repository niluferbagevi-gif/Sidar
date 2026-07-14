#!/usr/bin/env python3
"""Web boot smoke test for the production-minimal dependency profile.

Boots ``web_server:app`` under uvicorn with only ``sidar[postgres]``
installed and polls ``/health`` until the process responds. The gate does
not require a fully "healthy" top-level status: with no live Ollama backend
in CI, ``/health`` legitimately reports ``degraded`` (503) via the
AI_PROVIDER liveness check in ``web/routes/health_runtime.py``, which is
expected and unrelated to dependency completeness. What this script asserts
instead is that the process came up and the agent role catalog loaded
without import failures (``agent_catalog.degraded is False``) — the signal
that actually depends on the production-minimal package surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import httpx

HOST = "127.0.0.1"
PORT = int(os.environ.get("PRODUCTION_MINIMAL_SMOKE_PORT", "8099"))
HEALTH_URL = f"http://{HOST}:{PORT}/health"
BOOT_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 1.0


def _wait_for_health() -> httpx.Response | None:
    deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            return httpx.get(HEALTH_URL, timeout=5.0)
        except httpx.TransportError:
            time.sleep(POLL_INTERVAL_SECONDS)
    return None


def main() -> int:
    server = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no untrusted input
        [sys.executable, "-m", "uvicorn", "web_server:app", "--host", HOST, "--port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        response = _wait_for_health()
        if response is None:
            print(
                f"❌ production-minimal web boot smoke: no response within {BOOT_TIMEOUT_SECONDS}s"
            )
            return 1

        try:
            payload = response.json()
        except json.JSONDecodeError:
            print(f"❌ production-minimal web boot smoke: non-JSON /health body: {response.text!r}")
            return 1

        catalog = payload.get("agent_catalog", {})
        import_failures = catalog.get("import_failures") or {}
        if catalog.get("degraded") is not False or import_failures:
            print("❌ production-minimal web boot smoke: agent role catalog degraded")
            print(json.dumps(payload, indent=2))
            return 1

        print(
            "✅ production-minimal web boot smoke ok "
            f"(http_status={response.status_code}, top_level_status={payload.get('status')!r}, "
            "agent_catalog healthy)"
        )
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
        if server.stdout is not None:
            output = server.stdout.read()
            if output:
                print("---- uvicorn output ----")
                print(output)


if __name__ == "__main__":
    sys.exit(main())
