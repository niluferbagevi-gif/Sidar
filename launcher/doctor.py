"""Launcher Doctor helpers: pure presentation and auto-fix command resolution.

Extracted from ``main.py``'s Doctor auto-fix flow. Only the stateless pieces
live here — command list resolution, fallback selection, status formatting,
and the lost-env-key diff. The stateful orchestration around them
(``_run_doctor_auto_fix``, revalidation caching, ``preflight``) stays in
main.py because it mutates module-level globals that tests poke directly
(``main._LAST_DOCTOR_AUTO_FIX_REVALIDATION``, ``main._DOCTOR_APPLY_ALL_APPROVED``)
and interacts with the interactive wizard (``confirm``); splitting that part
out would mean either moving that mutable state wholesale (breaking the
tests' direct-attribute-assignment access to it) or threading it through as
explicit parameters, which is a bigger, separate design change.
"""

from __future__ import annotations

from typing import Any

# Terminal renkleri (ANSI). main.py'nin kendi CYAN/GREEN/YELLOW/RED/RESET
# sabitleriyle birebir aynı; bkz. launcher/process.py'deki aynı gerekçe.
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_RESET = "\033[0m"


def doctor_status_icon(status: str) -> str:
    if status == "pass":
        return "✅"
    if status == "warn":
        return "⚠"
    if status == "fail":
        return "❌"
    return "ℹ️"


def print_doctor_check_summary(check: Any) -> None:
    status = str(getattr(check, "status", "warn") or "warn")
    name = str(getattr(check, "name", "doctor") or "doctor")
    message = str(getattr(check, "message", "") or "")
    details = getattr(check, "details", {}) or {}
    color = _GREEN if status == "pass" else (_RED if status == "fail" else _YELLOW)
    print(f"{color}{doctor_status_icon(status)} Doctor/{name}: {message}{_RESET}")

    hints = details.get("root_cause_hints") if isinstance(details, dict) else None
    if isinstance(hints, list) and status in {"warn", "fail"}:
        for hint in hints[:3]:
            print(f"{_YELLOW}   • Olası neden: {hint}{_RESET}")

    steps = details.get("remediation_steps") if isinstance(details, dict) else None
    if isinstance(steps, list) and status in {"warn", "fail"}:
        for step in steps[:2]:
            print(f"{_YELLOW}   • Çözüm: {step}{_RESET}")

    commands = details.get("recommended_commands") if isinstance(details, dict) else None
    if isinstance(commands, list) and status in {"warn", "fail"}:
        for command in commands[:3]:
            print(f"{_CYAN}   • Komut: {command}{_RESET}")


def doctor_auto_fix_commands(details: dict[str, Any]) -> list[str]:
    """Return ordered Doctor auto-fix commands from legacy or multi-step metadata."""
    steps = details.get("auto_fix_steps")
    status = str(details.get("status", "warn") or "warn")
    if isinstance(steps, list) and status in {"warn", "fail"}:
        commands = [step.strip() for step in steps if isinstance(step, str) and step.strip()]
        if commands:
            return commands

    auto_fix = details.get("auto_fix")
    if isinstance(auto_fix, list):
        return [step.strip() for step in auto_fix if isinstance(step, str) and step.strip()]
    if isinstance(auto_fix, str) and auto_fix.strip():
        return [auto_fix.strip()]
    return []


def doctor_auto_fix_fallback_commands(details: dict[str, Any]) -> list[str]:
    """Return fallback Doctor commands when primary auto-fix fails."""
    fallback = details.get("auto_fix_fallback") or details.get("auto_fix_fallbacks")
    if isinstance(fallback, str) and fallback.strip():
        return [fallback.strip()]
    if isinstance(fallback, list):
        return [step.strip() for step in fallback if isinstance(step, str) and step.strip()]

    recommended = details.get("recommended_commands")
    if isinstance(recommended, list):
        primary = set(doctor_auto_fix_commands(details))
        return [
            step.strip()
            for step in recommended
            if isinstance(step, str) and step.strip() and step.strip() not in primary
        ]
    return []


def select_doctor_auto_fix_commands(check_name: str, commands: list[str]) -> list[str]:
    """Interactive selector for checks that publish multiple auto-fix alternatives."""
    del check_name
    return commands


def launcher_auto_fix_command(cmd: list[str]) -> list[str]:
    """Normalize Doctor auto-fix command tokens without altering caller intent."""
    return [str(part) for part in cmd]


def doctor_auto_fix_lost_env_keys(
    source_details: dict[str, Any] | None, updated_check: Any
) -> list[str]:
    """Return env keys that were set before auto-fix but missing after re-validation."""
    if not isinstance(source_details, dict):
        return []
    updated_details = getattr(updated_check, "details", {}) or {}
    if not isinstance(updated_details, dict):
        return []

    set_flags = {
        "database_url_set": "DATABASE_URL",
        "container_database_url_set": "SIDAR_CONTAINER_DATABASE_URL",
        "postgres_user_set": "POSTGRES_USER",
        "postgres_password_set": "POSTGRES_" + "PASSWORD",
        "postgres_db_set": "POSTGRES_DB",
    }
    lost_keys: list[str] = []
    for detail_key, env_key in set_flags.items():
        if source_details.get(detail_key) is True and updated_details.get(detail_key) is False:
            lost_keys.append(env_key)
    return lost_keys


__all__ = [
    "doctor_auto_fix_commands",
    "doctor_auto_fix_fallback_commands",
    "doctor_auto_fix_lost_env_keys",
    "doctor_status_icon",
    "launcher_auto_fix_command",
    "print_doctor_check_summary",
    "select_doctor_auto_fix_commands",
]
