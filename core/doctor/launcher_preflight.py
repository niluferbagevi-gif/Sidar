"""Launcher-facing Doctor preflight orchestration.

This module keeps the CLI launcher's short readiness workflow close to the
canonical ``core.doctor`` checks so launcher preflight behavior does not drift
from the normal Doctor health-check surface. The launcher still owns UI colors,
confirmation prompts and environment reload hooks; this module owns the order,
skip policy and parallel execution plan for Doctor checks.
"""

from __future__ import annotations

import concurrent.futures
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LauncherDoctorPreflightHooks:
    """Callbacks supplied by the launcher for UI and auto-fix integration."""

    confirm: Callable[[str, bool], bool]
    print_check_summary: Callable[[Any], None]
    doctor_auto_fix_commands: Callable[[dict[str, Any]], list[str]]
    invoke_auto_fix: Callable[[Any, Any, bool], bool]
    clear_revalidation_cache: Callable[[], None]
    final_check_after_auto_fix: Callable[[Any, bool], Any]


@dataclass(frozen=True)
class LauncherDoctorPreflightStyle:
    """ANSI style fragments used by the launcher output."""

    cyan: str = ""
    yellow: str = ""
    reset: str = ""


def run_launcher_doctor_preflight(
    *,
    doctor_apply_all_yes: bool = False,
    hooks: LauncherDoctorPreflightHooks,
    style: LauncherDoctorPreflightStyle | None = None,
    max_autofix_retries: int = 2,
    stdin_isatty: Callable[[], bool] | None = None,
    handled_exceptions: tuple[type[BaseException], ...] | None = None,
) -> None:
    """Run the launcher Doctor preflight using canonical ``core.doctor`` checks."""
    try:
        from core.doctor import (
            check_database_connectivity,
            check_database_env,
            check_gpu_memory_config,
            check_graphrag_entity_memory_ready,
            check_rag_readiness,
        )
    except (ImportError, AttributeError) as exc:  # pragma: no cover - defensive launcher path
        logger.debug("Doctor ön kontrol modülü yüklenemedi: %s", exc)
        return

    handled_exceptions = handled_exceptions or (
        RuntimeError,
        ValueError,
        OSError,
        TypeError,
        AttributeError,
    )
    style = style or LauncherDoctorPreflightStyle()
    isatty = stdin_isatty or sys.stdin.isatty
    print(f"\n{style.cyan}🩺 Doctor kısa kontrolleri...{style.reset}")
    apply_all_mode = doctor_apply_all_yes
    if isatty() and not doctor_apply_all_yes:
        apply_all_mode = hooks.confirm(
            "Doctor için bulunan tüm auto-fix önerileri tek seferde otomatik uygulansın mı?",
            False,
        )
    skip_database_dependents = False
    skip_summary_printed = False
    auto_fix_attempts = 0

    def _guarded_invoke_doctor_auto_fix(check: Any, check_func: Any) -> bool:
        nonlocal auto_fix_attempts
        details = getattr(check, "details", {}) or {}
        status = str(getattr(check, "status", "warn") or "warn")
        has_auto_fix = (
            status in {"warn", "fail"}
            and isinstance(details, dict)
            and bool(hooks.doctor_auto_fix_commands(details))
        )
        if not has_auto_fix:
            return hooks.invoke_auto_fix(check, check_func, apply_all_mode)
        if auto_fix_attempts >= max_autofix_retries:
            print(
                f"{style.yellow}   • Doctor auto-fix toplam tekrar limiti aşıldı "
                f"({max_autofix_retries}); sonraki öneriler uygulanmadı.{style.reset}"
            )
            return False
        auto_fix_attempts += 1
        return hooks.invoke_auto_fix(check, check_func, apply_all_mode)

    def _run_single_doctor_check(check_name: str, check_func: Any) -> str:
        nonlocal skip_database_dependents, skip_summary_printed
        if skip_database_dependents and check_name in {
            "database_connectivity",
            "rag_readiness",
            "graphrag_entity_memory_ready",
        }:
            if not skip_summary_printed:
                print(
                    f"{style.yellow}   • Doctor/database_env hâlâ fail; "
                    "database_connectivity ve rag_readiness kontrolleri atlandı. "
                    f"Önce yukarıdaki database_env düzeltmesini tamamlayın.{style.reset}"
                )
                skip_summary_printed = True
            return "skipped"

        try:
            check = check_func()
            hooks.print_check_summary(check)
            hooks.clear_revalidation_cache()
            auto_fix_applied = _guarded_invoke_doctor_auto_fix(check, check_func)
            final_check = hooks.final_check_after_auto_fix(check, auto_fix_applied)
            final_status = str(getattr(final_check, "status", "warn") or "warn")
            if check_name == "database_env":
                skip_database_dependents = final_status == "fail"
            return final_status
        except handled_exceptions as exc:  # pragma: no cover - defensive launcher path
            logger.warning("Doctor ön kontrolü çalıştırılamadı: %s", exc)
            print(f"{style.yellow}⚠ Doctor ön kontrolü çalıştırılamadı: {exc}{style.reset}")
            return "error"

    _run_single_doctor_check("database_env", check_database_env)
    _run_single_doctor_check("database_connectivity", check_database_connectivity)
    if skip_database_dependents:
        _run_single_doctor_check("rag_readiness", check_rag_readiness)
        _run_single_doctor_check("graphrag_entity_memory_ready", check_graphrag_entity_memory_ready)
        _run_single_doctor_check("gpu_memory_config", check_gpu_memory_config)
        return

    parallel_checks = [
        ("rag_readiness", check_rag_readiness),
        ("graphrag_entity_memory_ready", check_graphrag_entity_memory_ready),
        ("gpu_memory_config", check_gpu_memory_config),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(parallel_checks)) as executor:
        futures = {
            executor.submit(check_func): (check_name, check_func)
            for check_name, check_func in parallel_checks
        }
        completed: dict[str, Any] = {}
        for future in concurrent.futures.as_completed(futures):
            check_name, _check_func = futures[future]
            try:
                completed[check_name] = future.result()
            except handled_exceptions as exc:  # pragma: no cover - defensive launcher path
                completed[check_name] = exc

    for check_name, check_func in parallel_checks:
        result = completed.get(check_name)
        if isinstance(result, Exception):
            logger.warning("Doctor ön kontrolü çalıştırılamadı: %s", result)
            print(f"{style.yellow}⚠ Doctor ön kontrolü çalıştırılamadı: {result}{style.reset}")
            continue
        hooks.print_check_summary(result)
        _guarded_invoke_doctor_auto_fix(result, check_func)
