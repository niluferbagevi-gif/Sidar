"""Unit tests for core/utils/trusted_subprocess.py.

See that module's docstring for why it exists: it centralizes the
unavoidable Bandit B603 suppression for internally-trusted subprocess
calls into one reviewed spot instead of one per call site. These tests
pin its minimal safety contract (reject shell=True, empty commands, and
embedded NUL bytes) and that it otherwise forwards faithfully to
``subprocess.run``/``subprocess.Popen``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from core.utils.trusted_subprocess import (
    UntrustedCommandError,
    popen_trusted_command,
    run_trusted_command,
)


def test_run_trusted_command_executes_and_forwards_kwargs() -> None:
    result = run_trusted_command(
        [sys.executable, "-c", "print('hello')"], capture_output=True, text=True, check=True
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_run_trusted_command_rejects_shell_true() -> None:
    with pytest.raises(UntrustedCommandError, match="shell"):
        run_trusted_command([sys.executable, "-c", "print(1)"], shell=True)


def test_run_trusted_command_rejects_empty_command() -> None:
    with pytest.raises(UntrustedCommandError, match="empty"):
        run_trusted_command([])


def test_run_trusted_command_rejects_embedded_nul_byte() -> None:
    with pytest.raises(UntrustedCommandError, match="NUL"):
        run_trusted_command([sys.executable, "-c\x00--evil-flag"])


def test_run_trusted_command_propagates_check_true_failure() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        run_trusted_command([sys.executable, "-c", "import sys; sys.exit(1)"], check=True)


def test_popen_trusted_command_starts_and_communicates() -> None:
    proc = popen_trusted_command(
        [sys.executable, "-c", "print('hi')"], stdout=subprocess.PIPE, text=True
    )
    try:
        stdout, _stderr = proc.communicate(timeout=10)
        assert stdout.strip() == "hi"
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_popen_trusted_command_rejects_shell_true() -> None:
    with pytest.raises(UntrustedCommandError, match="shell"):
        popen_trusted_command([sys.executable, "-c", "print(1)"], shell=True)


def test_popen_trusted_command_rejects_empty_command() -> None:
    with pytest.raises(UntrustedCommandError, match="empty"):
        popen_trusted_command([])


def test_popen_trusted_command_rejects_embedded_nul_byte() -> None:
    with pytest.raises(UntrustedCommandError, match="NUL"):
        popen_trusted_command(["git", "show", "HEAD:foo\x00bar"])
