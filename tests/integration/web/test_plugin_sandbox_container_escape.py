"""Real-Docker container escape/integration matrix for the plugin sandbox.

``tests/unit/web/plugins/test_sandbox.py`` and ``test_worker.py`` cover the RPC
contract and the ``docker run`` argv construction with mocked ``subprocess.run``
calls; they prove the *command we build* is correct but never actually launch a
container, so they cannot catch a regression in the underlying OS-level
isolation (e.g. a kernel/Docker default silently widening what an in-container
process can reach). ``docs/REFACTOR_PLAN.md`` (``SEC-PLUGIN-001``) tracks this
gap explicitly: AST validation and the restricted-builtins exec are defense in
depth, not the security boundary -- the container is. This module closes that
gap by spinning up real, disposable containers under the exact production
isolation flags (``DockerPluginSandboxBackend.container_command`` /
``.request``) and asserting that network, filesystem, environment/secret,
subprocess (pid-limit/OOM), and host-process escape attempts are all rejected
at the container boundary, matching ``SEC-PLUGIN-001`` acceptance criteria 2
and 3.

Requires a reachable Docker daemon *and* a pre-built target image
(``SIDAR_PLUGIN_SANDBOX_IMAGE``, default ``sidar:latest``) -- the whole module
skips otherwise, so it is a no-op on developer machines and any CI job that
does not build the image. ``ci.yml`` already builds ``sidar:latest`` via
``AUTO_BUILD_DOCKER_TEST_IMAGE=1`` before the integration test stage runs, and
``release-quality.yml``'s ``docker-smoke`` job points
``SIDAR_PLUGIN_SANDBOX_IMAGE`` at the freshly built release candidate image, so
this matrix runs against a real image on every PR and again at the release
gate. ``make plugin-sandbox-security`` builds the current checkout locally and
sets ``SIDAR_REQUIRE_PLUGIN_SANDBOX_CONTAINER_TESTS=1`` so unavailable
prerequisites fail instead of producing six misleading skips.
"""

from __future__ import annotations

import asyncio
import json
import os

# B404 review: fixed-argument docker CLI invocations only, mirrors sandbox.py.
import subprocess  # nosec B404
import time
import uuid

import pytest

from tests._helpers.docker_sandbox import docker_bin, require_or_skip_reason
from web.plugins.sandbox import (
    DockerPluginSandboxBackend,
    PluginSandboxError,
    build_isolated_plugin_proxy,
)

# Probe script executed *inside* the sandbox container under the production
# isolation flags. It never goes through validate_plugin_source/the RPC worker
# -- the point is to prove the container boundary itself (network namespace,
# read-only rootfs, non-root user, capability drop, pid namespace) rejects
# these actions regardless of what code runs, since the AST/builtins gate is
# explicitly documented as defense-in-depth rather than the real boundary.
_ESCAPE_MATRIX_SCRIPT = r"""
import json
import os
import socket
import subprocess

results = {}

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(("1.1.1.1", 80))
    s.close()
    results["network_egress"] = "escaped"
except OSError as exc:
    results["network_egress"] = f"blocked:{type(exc).__name__}"

try:
    with open("/app/_escape_probe.txt", "w") as fh:
        fh.write("x")
    results["root_fs_write"] = "escaped"
except OSError as exc:
    results["root_fs_write"] = f"blocked:{type(exc).__name__}"

try:
    with open("/tmp/_escape_probe.sh", "w") as fh:
        fh.write("#!/bin/sh\necho pwned\n")
    os.chmod("/tmp/_escape_probe.sh", 0o755)
    results["tmp_write"] = "ok"
    try:
        subprocess.run(["/tmp/_escape_probe.sh"], capture_output=True, timeout=3, check=True)
        results["tmp_exec"] = "escaped"
    except (OSError, subprocess.CalledProcessError) as exc:
        results["tmp_exec"] = f"blocked:{type(exc).__name__}"
except OSError as exc:
    results["tmp_write"] = f"blocked:{type(exc).__name__}"
    results["tmp_exec"] = "n/a"

results["environment"] = sorted(os.environ.keys())

try:
    results["visible_pids"] = sorted(int(p) for p in os.listdir("/proc") if p.isdigit())
except OSError as exc:
    results["visible_pids"] = f"error:{type(exc).__name__}"

results["docker_socket_present"] = os.path.exists("/var/run/docker.sock")

results["uid"] = os.getuid()
try:
    os.setuid(0)
    results["setuid_root"] = "escaped"
except OSError as exc:
    results["setuid_root"] = f"blocked:{type(exc).__name__}"

try:
    priv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    priv.bind(("0.0.0.0", 80))
    priv.close()
    results["privileged_port_bind"] = "escaped"
except OSError as exc:
    results["privileged_port_bind"] = f"blocked:{type(exc).__name__}"

try:
    raw = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    raw.close()
    results["raw_socket"] = "escaped"
except OSError as exc:
    results["raw_socket"] = f"blocked:{type(exc).__name__}"

print(json.dumps(results))
"""

_FORK_BOMB_SCRIPT = r"""
import json
import os

spawned = 0
children = []
try:
    for _ in range(200):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        children.append(pid)
        spawned += 1
    outcome = "unlimited"
except BlockingIOError:
    outcome = "blocked"
except OSError:
    outcome = "blocked"
finally:
    for pid in children:
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass

print(json.dumps({"outcome": outcome, "spawned": spawned}))
"""

_SECRET_TOKEN = f"host-secret-{uuid.uuid4().hex}"


def _backend(**env_overrides: str) -> DockerPluginSandboxBackend:
    """Build a backend that resolves the real target image from the environment."""
    merged = dict(os.environ)
    merged.update(env_overrides)
    return DockerPluginSandboxBackend(merged)


_TARGET_IMAGE = _backend().image
_IMAGE_READY, _SKIP_REASON = require_or_skip_reason(_TARGET_IMAGE)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.docker,
    pytest.mark.skipif(not _IMAGE_READY, reason=_SKIP_REASON),
]


def _run_probe(script: str, *, env: dict[str, str] | None = None, timeout: int = 20) -> str:
    backend = _backend()
    command = backend.container_command("-c", script)
    completed = subprocess.run(  # nosec B603
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env if env is not None else {"PATH": os.environ.get("PATH", "")},
    )
    return completed.stdout


def _running_containers_for_image(image: str) -> list[str]:
    docker = docker_bin()
    assert docker is not None
    completed = subprocess.run(  # nosec B603
        [docker, "ps", "-a", "-q", "--filter", f"ancestor={image}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _assert_no_orphan_containers(image: str) -> None:
    """Poll for --rm cleanup; Docker removes the container asynchronously.

    30s (not the original 5s, nor the 5s->15s first widening) headroom: a CI
    runner building the target image, running Postgres/Redis service
    containers, and this module's own xdist workers concurrently can
    genuinely make async ``--rm`` teardown slower than on an idle developer
    machine. This has now needed widening twice under real CI contention --
    once for a client-triggered kill (subprocess timeout), once for a cgroup
    OOM-kill (SIGKILL from the kernel, which plausibly takes Docker longer to
    notice and reap than a client-side kill) -- so this round doubles the
    budget again rather than nudging it, instead of re-learning the same
    lesson a third time one test at a time.
    """
    deadline = time.monotonic() + 30
    remaining: list[str] = []
    while time.monotonic() < deadline:
        remaining = _running_containers_for_image(image)
        if not remaining:
            return
        time.sleep(0.5)
    pytest.fail(f"Sandbox container(ler) --rm ile temizlenmedi: {remaining}")


def test_container_escape_matrix_rejects_network_fs_env_and_host_process_access() -> None:
    """SEC-PLUGIN-001 acceptance criterion 2 -- network/fs/env/subprocess/host-process.

    Escape attempts are all rejected at the container boundary, verified against a
    real image instead of asserting on the constructed argv alone.
    """
    fake_host_env = {
        "PATH": os.environ.get("PATH", ""),
        "SIDAR_ESCAPE_TEST_SECRET_TOKEN": _SECRET_TOKEN,
    }
    stdout = _run_probe(_ESCAPE_MATRIX_SCRIPT, env=fake_host_env)
    results = json.loads(stdout)

    assert results["network_egress"].startswith("blocked:"), results
    assert results["root_fs_write"].startswith("blocked:"), results
    assert results["tmp_write"] == "ok", results
    assert results["tmp_exec"].startswith("blocked:"), results
    assert results["uid"] == 65534, results
    assert results["setuid_root"].startswith("blocked:"), results
    assert results["privileged_port_bind"].startswith("blocked:"), results
    assert results["raw_socket"].startswith("blocked:"), results
    assert results["docker_socket_present"] is False, results
    assert len(results["visible_pids"]) <= 5, results

    # The docker CLI process (host side) was handed a fake host secret in its own
    # environment to simulate the worst case (an operator forgetting to scope the
    # subprocess env); the container must never see it because no `-e` flag ever
    # forwards it in -- this proves the container boundary, not just our own
    # defensive `env={"PATH": ...}` restriction in sandbox.py.
    assert "SIDAR_ESCAPE_TEST_SECRET_TOKEN" not in results["environment"], results


def test_container_enforces_pids_limit_against_fork_bomb() -> None:
    """A low, test-scoped pids-limit must bound runaway process creation."""
    backend = _backend(SIDAR_PLUGIN_SANDBOX_PIDS="8")
    command = backend.container_command("-c", _FORK_BOMB_SCRIPT)
    completed = subprocess.run(  # nosec B603
        command,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env={"PATH": os.environ.get("PATH", "")},
    )

    if completed.returncode == 0:
        result = json.loads(completed.stdout)
        assert result["outcome"] == "blocked", result
        assert result["spawned"] < 200, result
    else:
        # The cgroup can also terminate the worker outright once the pid limit
        # is hit mid-fork; either outcome is an accepted fail-closed result.
        assert completed.returncode != 0


def test_container_is_oom_killed_and_fails_closed_when_exceeding_memory_limit() -> None:
    """SEC-PLUGIN-001 acceptance criterion 3 -- OOM fails closed.

    Verified through the real production RPC path
    (``DockerPluginSandboxBackend.request``), not a raw probe.
    """
    backend = _backend(SIDAR_PLUGIN_SANDBOX_MEMORY="96m")
    source = """
from agent.base_agent import BaseAgent

class MemoryBombAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        blob = bytearray(400 * 1024 * 1024)
        return str(len(blob))
"""

    with pytest.raises(PluginSandboxError):
        backend.request(
            {
                "action": "run_task",
                "source": source,
                "class_name": "MemoryBombAgent",
                "module_label": "memory_bomb",
                "task_prompt": "go",
            }
        )

    _assert_no_orphan_containers(backend.image)


def test_container_timeout_is_enforced_and_cleaned_up_for_a_real_hanging_process() -> None:
    """Real (unmocked) end-to-end verification of the timeout path.

    The worker genuinely hangs inside the container and the host
    ``subprocess.run`` timeout kills + removes it, instead of the mocked
    ``TimeoutExpired`` unit test.
    """
    backend = _backend(SIDAR_PLUGIN_SANDBOX_TIMEOUT="2")
    source = """
import asyncio

from agent.base_agent import BaseAgent

class HangingAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        await asyncio.sleep(30)
        return "never"
"""

    with pytest.raises(PluginSandboxError, match="zaman aşımına uğradı"):
        backend.request(
            {
                "action": "run_task",
                "source": source,
                "class_name": "HangingAgent",
                "module_label": "hanging_plugin",
                "task_prompt": "go",
            }
        )

    _assert_no_orphan_containers(backend.image)


def test_container_never_relays_worker_exception_text_to_the_host() -> None:
    """SEC-PLUGIN-001 acceptance criterion 3 -- no sensitive data is logged/relayed.

    Verified with a real worker exception (not a mocked ``ok: false`` payload).
    """
    backend = _backend()
    secret = f"do-not-leak-{uuid.uuid4().hex}"
    source = f"""
from agent.base_agent import BaseAgent

class LeakyAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        raise RuntimeError("{secret}")
"""

    with pytest.raises(PluginSandboxError) as exc_info:
        backend.request(
            {
                "action": "run_task",
                "source": source,
                "class_name": "LeakyAgent",
                "module_label": "leaky_plugin",
                "task_prompt": "go",
            }
        )

    assert secret not in str(exc_info.value)


def test_isolated_plugin_proxy_executes_successfully_against_the_real_image() -> None:
    """SEC-PLUGIN-001 acceptance criterion 6 -- container integration/marketplace smoke.

    A marketplace-style plugin registration/execution smoke test against the
    real built image, exercising the exact host-safe ``BaseAgent`` proxy path
    used by plugin registration.
    """
    source = """
from agent.base_agent import BaseAgent

class ContainerEscapeSmokeAgent(BaseAgent):
    \"\"\"Container escape matrix smoke plugin.\"\"\"
    async def run_task(self, task_prompt: str) -> str:
        return f"isolated-ok:{task_prompt}"
"""
    proxy_cls = build_isolated_plugin_proxy(source, "ContainerEscapeSmokeAgent", "escape_smoke")

    result = asyncio.run(proxy_cls().run_task("ping"))

    assert result == "isolated-ok:ping"
