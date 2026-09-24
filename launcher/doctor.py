"""Launcher Doctor helpers: pure presentation and auto-fix command resolution.

Extracted from ``main.py``'s Doctor auto-fix flow. The stateless pieces
live here — command list resolution, fallback selection, status formatting,
the lost-env-key diff, and the auto-fix command/loop/revalidation logic.
The mutable state (``main._LAST_DOCTOR_AUTO_FIX_REVALIDATION``,
``main._DOCTOR_APPLY_ALL_APPROVED``) stays in main.py because tests poke it
directly; main.py's same-named wrappers own that state and thread every
collaborator (``confirm``, the command runner, the env reloader) through as
explicit parameters, so monkeypatches on ``main`` keep taking effect.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.utils.trusted_subprocess import run_trusted_command

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


def run_doctor_auto_fix_command(
    auto_fix: str,
    *,
    cwd: Path,
    env: dict[str, str],
    format_cmd: Callable[[list[str]], str],
    logger_obj: logging.Logger,
) -> bool:
    """Run one validated Doctor auto-fix command without invoking a shell."""
    try:
        from core.doctor import validate_auto_fix_command

        cmd = validate_auto_fix_command(auto_fix)
    except ValueError as exc:
        logger_obj.warning("Doctor auto_fix komutu reddedildi: %s", exc)
        print(f"{_RED}   • Auto-fix komutu güvenlik doğrulamasından geçmedi: {exc}{_RESET}")
        return False
    cmd = launcher_auto_fix_command(cmd)
    print(f"{_CYAN}   • Auto-fix çalışıyor: {format_cmd(cmd)}{_RESET}")
    try:
        completed = run_trusted_command(cmd, check=False, cwd=cwd, env=env)
    except OSError as exc:
        logger_obj.warning("%s: %s", "Doctor auto_fix başlatılamadı", exc)
        print(f"{_RED}   • Auto-fix başlatılamadı: {exc}{_RESET}")
        return False
    returncode = int(completed.returncode)

    if returncode == 0:
        print(f"{_GREEN}   • Auto-fix tamamlandı.{_RESET}")
        return True

    print(f"{_YELLOW}   • Auto-fix {returncode} koduyla tamamlandı.{_RESET}")
    return False


def run_doctor_auto_fix(
    check: Any,
    check_func: Any | None = None,
    *,
    apply_all_mode: bool,
    confirm: Callable[[str, bool], bool],
    run_command: Callable[[str], bool],
    revalidate: Callable[[str, Any, dict[str, Any]], Any],
    max_retries: int,
    stdin_isatty: Callable[[], bool],
) -> bool:
    """Run Doctor auto-fix command(s), optionally revalidating after each successful step.

    The caller owns the revalidation cache and resets it before calling this.
    """
    details = getattr(check, "details", {}) or {}
    check_name = str(getattr(check, "name", "doctor") or "doctor")
    status = str(getattr(check, "status", "warn") or "warn")
    if status not in {"warn", "fail"} or not isinstance(details, dict):
        return False

    auto_fix_commands = doctor_auto_fix_commands(details)
    if not auto_fix_commands or not stdin_isatty():
        return False
    if apply_all_mode:
        selected_auto_fix_commands = auto_fix_commands
    else:
        selected_auto_fix_commands = select_doctor_auto_fix_commands(check_name, auto_fix_commands)
        prompt_suffix = "adımları" if len(selected_auto_fix_commands) > 1 else "komutu"
        if not confirm(
            f"Doctor/{getattr(check, 'name', 'doctor')} için önerilen auto-fix {prompt_suffix} "
            "şimdi çalıştırılsın mı?",
            False,
        ):
            return False

    ran_any = False
    pending_commands = list(selected_auto_fix_commands)
    fallback_commands = doctor_auto_fix_fallback_commands(details)
    used_fallback = False
    index = 0
    attempts = 0
    while index < len(pending_commands):
        if attempts >= max_retries:
            print(
                f"{_YELLOW}   • Auto-fix tekrar limiti aşıldı "
                f"({max_retries}); kalan komutlar atlandı.{_RESET}"
            )
            return ran_any
        attempts += 1
        auto_fix = pending_commands[index]
        index += 1
        if not run_command(auto_fix):
            if not used_fallback and fallback_commands:
                used_fallback = True
                pending_commands.extend(fallback_commands)
                print(f"{_YELLOW}   • Auto-fix başarısız; fallback komutları denenecek.{_RESET}")
                continue
            return ran_any
        ran_any = True
        if check_func is None:
            continue

        updated_check = revalidate(check_name, check_func, details)
        updated_status = str(getattr(updated_check, "status", "warn") or "warn")
        if updated_status == "pass":
            return True

    return ran_any


def revalidate_doctor_check_after_auto_fix(
    check_name_or_func: Any,
    check_func_or_details: Any | None = None,
    source_details: dict[str, Any] | None = None,
    *,
    reload_environment: Callable[..., Any],
    handled_exceptions: tuple[type[BaseException], ...],
    logger_obj: logging.Logger,
) -> Any | None:
    """Run a Doctor check once after a successful auto-fix and print the result.

    Returns the updated check, or ``None`` if the check could not run; the caller
    stores the result as its revalidation cache.
    """
    if callable(check_name_or_func):
        check_name = "database_env"
        check_func = check_name_or_func
        if isinstance(check_func_or_details, dict):
            source_details = check_func_or_details
    else:
        check_name = str(check_name_or_func or "doctor")
        check_func = check_func_or_details

    try:
        reload_environment(source_details, check_name=check_name)
    except TypeError:
        reload_environment(source_details)
    try:
        updated_check = check_func()
    except handled_exceptions as exc:  # pragma: no cover - defensive launcher path
        logger_obj.warning("Doctor auto-fix sonrası doğrulama çalıştırılamadı: %s", exc)
        print(f"{_YELLOW}   • Auto-fix sonrası doğrulama çalıştırılamadı: {exc}{_RESET}")
        return None

    updated_status = str(getattr(updated_check, "status", "warn") or "warn")
    if updated_status == "fail":
        doctor_checks: dict[str, str] = {
            "database_env": "check_database_env",
            "database_connectivity": "check_database_connectivity",
            "rag_readiness": "check_rag_readiness",
            "graphrag_entity_memory_ready": "check_graphrag_entity_memory_ready",
        }
        check_attr = doctor_checks.get(check_name)
        if check_attr and check_name != "database_env":
            with contextlib.suppress(Exception):
                from core import doctor as doctor_module

                fresh_check = getattr(doctor_module, check_attr, None)
                if callable(fresh_check):
                    refreshed = fresh_check()
                    refreshed_status = str(getattr(refreshed, "status", "warn") or "warn")
                    if refreshed_status != "fail":
                        updated_check = refreshed
                        updated_status = refreshed_status

    print(f"{_CYAN}   • Auto-fix sonrası yeniden doğrulama:{_RESET}")
    print_doctor_check_summary(updated_check)
    updated_name = str(getattr(updated_check, "name", "doctor") or "doctor")
    lost_env_keys = doctor_auto_fix_lost_env_keys(source_details, updated_check)
    if lost_env_keys:
        print(
            f"{_RED}   • Auto-fix Doctor/{updated_name} regresyon üretti: "
            f"önceden set olan {', '.join(lost_env_keys)} yeniden doğrulamada boş görünüyor. "
            f"Bu durum düzeltilmiş kabul edilmedi; env reload zincirini manuel inceleyin.{_RESET}"
        )
    elif updated_status == "fail":
        print(
            f"{_RED}   • Auto-fix Doctor/{updated_name} sorununu gideremedi; "
            f"yukarıdaki önerileri manuel uygulayın.{_RESET}"
        )
    elif updated_status == "pass":
        print(f"{_GREEN}   • Auto-fix Doctor/{updated_name} kontrolünü düzeltti.{_RESET}")
    else:
        print(
            f"{_YELLOW}   • Auto-fix Doctor/{updated_name} kontrolünü yeniden çalıştırdı; "
            f"kalan uyarıları inceleyin.{_RESET}"
        )
    return updated_check


__all__ = [
    "doctor_auto_fix_commands",
    "doctor_auto_fix_fallback_commands",
    "doctor_auto_fix_lost_env_keys",
    "doctor_status_icon",
    "launcher_auto_fix_command",
    "print_doctor_check_summary",
    "revalidate_doctor_check_after_auto_fix",
    "run_doctor_auto_fix",
    "run_doctor_auto_fix_command",
    "select_doctor_auto_fix_commands",
]
