"""Shared Docker-availability probes for the plugin sandbox security tests.

Two test modules need to know, at collection time, whether a real Docker
daemon *and* the plugin sandbox target image are actually available before
they can exercise the real container boundary:
``tests/integration/web/test_plugin_sandbox_container_escape.py`` (the
SEC-PLUGIN-001 container escape matrix) and
``tests/integration/web/test_plugin_sandbox_integration.py`` (the plugin
registration/rejection path, which also always runs the real Docker backend
per ``web/plugins/sandbox.py:plugin_sandbox_backend``). Keeping this probe
logic in one place avoids the two modules' checks drifting apart -- the same
class of bug this project has hit before with duplicated allowlists (see
``web/plugins/sandbox.py``'s own note on ``PLUGIN_SAFE_IMPORT_ROOTS``).

Both modules use the same ``SIDAR_REQUIRE_PLUGIN_SANDBOX_CONTAINER_TESTS``
opt-in: unset, missing prerequisites produce a clean pytest skip (a no-op on
developer machines and any CI job that does not build the image); set to
``1``, missing prerequisites raise at collection time instead, so
``make plugin-sandbox-security`` and CI's dedicated enforcement step turn six
(now seven) misleading skips into a hard failure.
"""

from __future__ import annotations

import os
import shutil

# B404 review: fixed-argument docker CLI invocations only, mirrors sandbox.py.
import subprocess  # nosec B404


def docker_bin() -> str | None:
    return shutil.which("docker")


def docker_daemon_available() -> bool:
    docker = docker_bin()
    if not docker:
        return False
    try:
        completed = subprocess.run(  # nosec B603
            [docker, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def image_available(image: str) -> bool:
    docker = docker_bin()
    if not docker:
        return False
    try:
        completed = subprocess.run(  # nosec B603
            [docker, "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def container_tests_required() -> bool:
    return os.getenv("SIDAR_REQUIRE_PLUGIN_SANDBOX_CONTAINER_TESTS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_or_skip_reason(image: str) -> tuple[bool, str]:
    """Return ``(image_ready, skip_reason)`` for a module's ``pytestmark``.

    Raises ``RuntimeError`` instead of returning when
    ``SIDAR_REQUIRE_PLUGIN_SANDBOX_CONTAINER_TESTS=1`` is set and the image
    isn't ready, so an enforced run fails loudly rather than silently
    skipping.
    """
    image_ready = docker_daemon_available() and image_available(image)
    if container_tests_required() and not image_ready:
        raise RuntimeError(
            "SIDAR_REQUIRE_PLUGIN_SANDBOX_CONTAINER_TESTS=1 ancak gerçek Docker daemon'ı "
            f"ve plugin sandbox imajı ({image}) hazır değil."
        )
    reason = (
        "Gerçek Docker daemon'ı ve build edilmiş plugin sandbox imajı "
        f"({image}) gerektirir; imaj/daemon yoksa bu modül atlanır. "
        "ci.yml AUTO_BUILD_DOCKER_TEST_IMAGE=1 ile ve release-quality.yml "
        "docker-smoke job'u SIDAR_PLUGIN_SANDBOX_IMAGE ile gerçek imajı sağlar; "
        "yerelde make plugin-sandbox-security kullanın."
    )
    return image_ready, reason
