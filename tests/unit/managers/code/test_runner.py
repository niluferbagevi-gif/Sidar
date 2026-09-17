from __future__ import annotations

from typing import get_type_hints

import pytest

from managers.code.runner import (
    SandboxRunner,
    build_sanitized_shell_args,
    find_destructive_shell_pattern,
    requires_container_shell,
    run_shell_command,
)


class _Security:
    @staticmethod
    def can_run_shell() -> bool:
        return True


class _Manager:
    def __init__(self, environment: str) -> None:
        self.cfg = type("Config", (), {"SIDAR_ENV": environment})()
        self.security = _Security()
        self.base_dir = "/workspace"
        self.max_output_chars = 1000
        self.sandbox_calls: list[tuple[str, str | None]] = []

    def run_shell_in_sandbox(self, command: str, *, cwd: str | None = None) -> tuple[bool, str]:
        self.sandbox_calls.append((command, cwd))
        return True, "sandboxed"


class _FailingSandboxManager(_Manager):
    def run_shell_in_sandbox(self, command: str, *, cwd: str | None = None) -> tuple[bool, str]:
        self.sandbox_calls.append((command, cwd))
        return False, "sandbox rejected command"


class _ManagerWithoutSandbox:
    def __init__(self) -> None:
        self.cfg = type("Config", (), {"SIDAR_ENV": "production"})()
        self.security = _Security()
        self.base_dir = "/workspace"
        self.max_output_chars = 1000


def test_production_full_access_routes_shell_to_container_without_host_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager("production")
    monkeypatch.setattr(
        "managers.code.runner.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("production must not execute on host"),
    )

    assert requires_container_shell(manager) is True
    assert run_shell_command(manager, "echo safe", cwd="/workspace") == (True, "sandboxed")
    assert manager.sandbox_calls == [("echo safe", "/workspace")]


def test_non_production_shell_does_not_require_container() -> None:
    assert requires_container_shell(_Manager("development")) is False


def test_production_propagates_sandbox_delegate_failure() -> None:
    manager = _FailingSandboxManager("production")

    result = run_shell_command(manager, "exit 7", cwd="/workspace")

    assert result == (False, "sandbox rejected command")
    assert manager.sandbox_calls == [("exit 7", "/workspace")]


def test_production_fails_closed_without_sandbox_runner() -> None:
    manager = _ManagerWithoutSandbox()

    ok, message = run_shell_command(manager, "echo safe")

    assert ok is False
    assert "host komut yürütme kapalıdır" in message


def test_sandbox_runner_protocol_declares_tuple_result_contract() -> None:
    return_type = get_type_hints(SandboxRunner.__call__)["return"]

    assert return_type == tuple[bool, str]


def test_build_sanitized_shell_args_rejects_unclosed_quotes_without_shell_features() -> None:
    with pytest.raises(ValueError, match="No closing quotation"):
        build_sanitized_shell_args(
            'python -c "print(1)',
            allow_shell_features=False,
            find_executable=lambda _name: None,
        )


@pytest.mark.parametrize("command", ["", "   ", "\t\n"])
def test_build_sanitized_shell_args_rejects_empty_commands(command: str) -> None:
    with pytest.raises(ValueError, match="ayrıştırılamadı"):
        build_sanitized_shell_args(
            command,
            allow_shell_features=False,
            find_executable=lambda _name: None,
        )


def test_build_sanitized_shell_args_rejects_nul_bytes_before_splitting() -> None:
    with pytest.raises(ValueError, match="NUL"):
        build_sanitized_shell_args(
            "echo ok\x00",
            allow_shell_features=False,
            find_executable=lambda _name: None,
        )


def test_build_sanitized_shell_args_returns_plain_argv_without_shell_features() -> None:
    assert build_sanitized_shell_args(
        "python -m pytest -q",
        allow_shell_features=False,
        find_executable=lambda _name: None,
    ) == ["python", "-m", "pytest", "-q"]


def test_build_sanitized_shell_args_prefers_bash_for_shell_features() -> None:
    def _find_executable(name: str) -> str | None:
        return "/bin/bash" if name == "bash" else None

    assert build_sanitized_shell_args(
        "echo ok && pwd",
        allow_shell_features=True,
        find_executable=_find_executable,
    ) == ["/bin/bash", "-lc", "echo ok && pwd"]


def test_build_sanitized_shell_args_falls_back_to_sh_when_bash_missing() -> None:
    def _find_executable(name: str) -> str | None:
        return "/bin/sh" if name == "sh" else None

    assert build_sanitized_shell_args(
        "echo ok && pwd",
        allow_shell_features=True,
        find_executable=_find_executable,
    ) == ["/bin/sh", "-lc", "echo ok && pwd"]


def test_build_sanitized_shell_args_rejects_shell_features_without_interpreter() -> None:
    with pytest.raises(ValueError, match="bash/sh"):
        build_sanitized_shell_args(
            "echo ok && pwd",
            allow_shell_features=True,
            find_executable=lambda _name: None,
        )


@pytest.mark.parametrize(
    ("command", "expected_fragment"),
    [
        ('rm -rf "$TARGET"', "rm + değişken/komut ikamesi"),
        ("rm -rf ${TARGET}", "rm + değişken/komut ikamesi"),
        ("rm -rf $(echo /)", "rm -rf"),
        ("rm -rf `echo /`", "rm -rf"),
        ("rm -rf $TARGET", "rm + değişken/komut ikamesi"),
        ("chmod -R 777 /", "chmod -R 777 /"),
        ("chmod --recursive 0777 /root", "chmod -R 777 /"),
        ("chmod -R ugo+rwx ~", "chmod -R 777 /"),
        ("chown -R sidar /", "chown -R"),
        ("chown --recursive user:group /home", "chown -R"),
        ("dd if=image.raw of=/dev/nvme0n1 bs=4M", "dd of=/dev/*"),
        ("dd of=/dev/sda if=/tmp/image", "dd of=/dev/*"),
        ("wipefs --all /dev/nvme0n1", "shred/wipefs /dev/*"),
        ("mkfs /dev/sdb1", "mkfs"),
        ("mkfs.ext4 /dev/sdb1", "mkfs"),
        ("mkfs.btrfs /dev/sdb1", "mkfs"),
        ("cat secret.txt > /etc/passwd", "> /etc/passwd"),
    ],
)
def test_find_destructive_shell_pattern_blocks_high_risk_variants(
    command: str, expected_fragment: str
) -> None:
    detected = find_destructive_shell_pattern(command)

    assert detected is not None
    assert expected_fragment in detected


@pytest.mark.parametrize(
    "command",
    [
        'rm -rf "$TARGET',
        "dd if=image.raw of=$TARGET",
        "shred $TARGET",
        "wipefs $TARGET",
        'mkfs.ext4 "/dev/sdb1',
    ],
)
def test_find_destructive_shell_pattern_fails_closed_for_dynamic_or_unparseable_segments(
    command: str,
) -> None:
    assert find_destructive_shell_pattern(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ./build",
        "rm -rf node_modules",
        "chmod 755 ./scripts",
        "chown sidar ./workspace",
        "dd if=/dev/zero of=./disk.img bs=1M count=1",
    ],
)
def test_find_destructive_shell_pattern_allows_relative_non_recursive_maintenance(
    command: str,
) -> None:
    assert find_destructive_shell_pattern(command) is None
