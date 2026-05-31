"""Shell-command classification helpers used by CodeManager pytest preflight."""

from __future__ import annotations

import shlex


def extract_pytest_args(command: str) -> list[str]:
    """Return only pytest arguments from a normalized pytest command."""
    parts = shlex.split(command)
    if not parts:
        return ["-q"]
    lowered = [part.lower() for part in parts]
    if len(lowered) >= 3 and lowered[0] == "uv" and lowered[1] == "run":
        try:
            pytest_index = lowered.index("pytest", 2)
        except ValueError:
            return ["-q"]
        return parts[pytest_index + 1 :] or ["-q"]
    if len(lowered) >= 3 and lowered[0] == "python" and lowered[1] == "-m":
        return parts[3:] or ["-q"]
    if lowered[0] == "pytest":
        return parts[1:] or ["-q"]
    return ["-q"]


def command_requires_uv_tooling(command: str) -> bool:
    """Return whether a sandbox command needs project uv tooling."""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    lowered = [part.lower() for part in parts]
    return any(
        part == "uv"
        or part.endswith("/uv")
        or part == "pytest"
        or part.endswith("/pytest")
        or (part == "python" and lowered[index + 1 : index + 3] == ["-m", "pytest"])
        or part.endswith("run_tests.sh")
        or part.endswith("autonomous_loop.sh")
        for index, part in enumerate(lowered)
    )


def command_invokes_pytest(command: str) -> bool:
    """Return whether a sandbox command directly invokes pytest."""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    lowered = [part.lower() for part in parts]
    if not lowered:
        return False
    return (
        lowered[0] == "pytest"
        or lowered[0].endswith("/pytest")
        or lowered[:3] == ["python", "-m", "pytest"]
        or lowered[:3] == ["uv", "run", "pytest"]
    )


__all__ = ["command_invokes_pytest", "command_requires_uv_tooling", "extract_pytest_args"]
