from __future__ import annotations

from types import SimpleNamespace

from managers.code.docker import (
    DOCKER_CPUS_RE,
    DOCKER_MEMORY_RE,
    build_docker_cli_command,
    sanitize_docker_network,
    sanitize_docker_token,
)
from managers.code.patcher import apply_exact_block_patch
from managers.code.security_adapter import CodeSecurityAdapter


def test_docker_helper_sanitizers_and_cli_command_are_fixture_light(tmp_path):
    limits = {"memory": "--bad", "cpus": "0.25", "pids_limit": 0, "network_mode": "bad"}

    assert (
        sanitize_docker_token("128m", pattern=DOCKER_MEMORY_RE, default="256m", kind="memory")
        == "128m"
    )
    assert sanitize_docker_token("bad", pattern=DOCKER_CPUS_RE, default="0.5", kind="cpus") == "0.5"
    assert sanitize_docker_network("HOST") == "host"

    cmd = build_docker_cli_command("print(1)", limits, image="--privileged")

    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "--memory=256m" in cmd
    assert "--pids-limit=64" in cmd
    assert "--network=none" in cmd
    assert "python:3.11-slim" in cmd


def test_patcher_replaces_exactly_one_block_without_code_manager_fixture():
    ok, patched = apply_exact_block_patch("a\nb\n", "b", "c")
    assert ok is True
    assert patched == "a\nc\n"

    ok, message = apply_exact_block_patch("a\nb\n", "missing", "c")
    assert ok is False
    assert "Hedef kod bloğu" in message

    ok, message = apply_exact_block_patch("x x", "x", "y")
    assert ok is False
    assert "2 kez" in message


def test_security_adapter_delegates_policy_and_formats_safe_write_denial(tmp_path):
    security = SimpleNamespace(
        can_read=lambda path: path.endswith("ok.txt"),
        can_write=lambda path: False,
        get_safe_write_path=lambda name: tmp_path / "safe" / name,
        is_path_under=lambda path, base: str(path).startswith(str(base)),
    )
    adapter = CodeSecurityAdapter(security)

    assert adapter.can_read("ok.txt") is True
    assert adapter.can_write("blocked.txt") is False
    assert adapter.is_path_under(str(tmp_path / "file.py"), tmp_path) is True
    assert "Güvenli alternatif" in adapter.safe_write_denial("blocked.txt")
