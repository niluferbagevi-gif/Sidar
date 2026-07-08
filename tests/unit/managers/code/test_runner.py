from __future__ import annotations

import pytest

from managers.code.runner import build_sanitized_shell_args, find_destructive_shell_pattern


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
