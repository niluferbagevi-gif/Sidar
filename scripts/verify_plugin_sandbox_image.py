"""Verify the release image's plugin worker isolation with adversarial probes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from typing import Any

RPC_VERSION = "1"
SENTINEL_VALUE = "must-not-reach-plugin-worker"


def _container_command(image: str, *args: str) -> list[str]:
    """Build the same fail-closed boundary used by the production backend."""
    return [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=65534:65534",
        "--memory=256m",
        "--cpus=0.5",
        "--pids-limit=64",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--entrypoint=python",
        image,
        *args,
    ]


def _run(
    command: Sequence[str], *, stdin: str = "", timeout: float = 20.0
) -> subprocess.CompletedProcess[str]:
    """Run one bounded Docker probe without inheriting host secrets."""
    return subprocess.run(  # noqa: S603  # nosec B603
        list(command),
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
    )


def _rpc(image: str, source: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Submit source to the real worker entrypoint and decode its response."""
    request = {
        "rpc_version": RPC_VERSION,
        "action": "describe",
        "source": source,
        "class_name": "ProbeAgent",
        "module_label": "release_escape_probe",
    }
    result = _run(
        _container_command(image, "-m", "web.plugins.worker"),
        stdin=json.dumps(request),
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AssertionError(f"worker exited {result.returncode}: {result.stderr[-500:]}")
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or response.get("rpc_version") != RPC_VERSION:
        raise AssertionError(f"invalid worker response: {result.stdout[-500:]}")
    return response


def verify_image(image: str) -> None:
    """Run successful execution, escape rejection, and runtime boundary probes."""
    safe_source = """
from agent.base_agent import BaseAgent
class ProbeAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        return "ok"
"""
    if _rpc(image, safe_source).get("ok") is not True:
        raise AssertionError("valid plugin did not load in the release worker")

    attacks = {
        "filesystem": "open('/app/escape', 'w').write('x')",
        "environment": "import os\nLEAK = os.environ",
        "network": "import socket\nsocket.create_connection(('example.com', 443))",
        "subprocess": "import subprocess\nsubprocess.run(['id'])",
        "introspection": "LEAK = (lambda: 0).__globals__",
    }
    for name, source in attacks.items():
        response = _rpc(image, source)
        if response.get("ok") is not False:
            raise AssertionError(f"{name} escape source was not rejected")
        if SENTINEL_VALUE in json.dumps(response):
            raise AssertionError(f"{name} response leaked the host sentinel")

    identity = _run(
        _container_command(image, "-c", "import os; print(os.getuid(), os.getgid())")
    )
    if identity.returncode != 0 or identity.stdout.strip() != "65534 65534":
        raise AssertionError(f"worker identity is not low privilege: {identity.stdout!r}")

    filesystem = _run(
        _container_command(
            image,
            "-c",
            "from pathlib import Path; Path('/app/escape').write_text('x')",
        )
    )
    if filesystem.returncode == 0:
        raise AssertionError("release image root filesystem was writable")

    malformed = _run(
        _container_command(image, "-m", "web.plugins.worker"), stdin="not-json"
    )
    malformed_response = json.loads(malformed.stdout)
    if malformed.returncode != 0 or malformed_response.get("ok") is not False:
        raise AssertionError("malformed RPC did not fail closed")

    try:
        _rpc(image, "while True:\n    pass", timeout=2.0)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("non-terminating plugin did not hit the host timeout")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and execute the release security gate."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Locally available release image tag")
    args = parser.parse_args(argv)
    verify_image(args.image)
    print(f"Plugin sandbox release matrix passed for {args.image}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
