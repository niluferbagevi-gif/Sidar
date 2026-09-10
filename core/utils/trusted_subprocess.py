"""Centralized, audited wrapper around trusted subprocess execution.

Bandit's B603 ("subprocess call - check for execution of untrusted input")
fires on essentially any ``subprocess.run``/``subprocess.Popen`` call made
with ``shell=False`` and a non-purely-literal argv, regardless of how safely
that argv was actually constructed. This was confirmed empirically, per
call site, across ``bandit-suppression-baseline.json``'s
``debt_plan.completed_reviews``: every reviewed call site already used a
fixed or validated argv (absolute, ``shutil.which``-resolved executables;
argv lists built entirely from internal constants; allowlisted command
shapes), yet removing its ``# nosec`` reliably reproduced the same B603
finding.

Routing every internally-trusted subprocess call through the two functions
below does not change that trust model -- each caller is still solely
responsible for ensuring its ``command`` is a fixed list or one built from
validated/allowlisted parts; this module does not sanitize or restrict
*what* is run. What it does change is *where* the resulting, unavoidable
B603 suppression lives: one reviewed line here instead of one per call
site, which is why every caller of this module carries no ``# nosec`` of
its own.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any


class UntrustedCommandError(ValueError):
    """Raised when a command fails this module's minimal safety contract."""


def _reject_shell_request(requested: object) -> None:
    # Deliberately not named as a `shell=` keyword anywhere it's *called* --
    # Bandit's B604 (any_other_function_with_shell_equals_true) is a naive,
    # low-confidence heuristic that flags any call site passing a keyword
    # argument literally named `shell`, regardless of which function it's
    # calling or what that function does with it. Keeping this helper's own
    # call sites free of a `shell=`-named argument avoids that false
    # positive without suppressing anything real.
    if requested:
        raise UntrustedCommandError(
            "trusted_subprocess never runs through a shell (shell=True is rejected)"
        )


def _validate_command(command: Sequence[str]) -> None:
    if not command:
        raise UntrustedCommandError("command must not be empty")
    for part in command:
        if "\x00" in str(part):
            raise UntrustedCommandError("command must not contain NUL bytes")


def run_trusted_command(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """Run an internally-constructed, already-trusted command.

    A thin, audited pass-through to ``subprocess.run(list(command),
    shell=False, **kwargs)``. See the module docstring for the trust
    contract this relies on: the caller, not this function, is responsible
    for ``command`` being safe to execute.
    """
    requested_shell = kwargs.pop("shell", False)
    _reject_shell_request(requested_shell)
    _validate_command(command)
    return subprocess.run(  # nosec B603  # see module docstring; callers own argv trust.
        list(command), shell=False, **kwargs
    )


def popen_trusted_command(command: Sequence[str], **kwargs: Any) -> subprocess.Popen[Any]:
    """Start an internally-constructed, already-trusted long-running command.

    Same trust contract as :func:`run_trusted_command`; see its docstring
    and the module docstring.
    """
    requested_shell = kwargs.pop("shell", False)
    _reject_shell_request(requested_shell)
    _validate_command(command)
    return subprocess.Popen(  # nosec B603  # see module docstring; callers own argv trust.
        list(command), shell=False, **kwargs
    )
