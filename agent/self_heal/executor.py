"""Self-heal plan execution boundary extracted from ``agent.sidar_agent``.

Phase 1 keeps ``SidarAgent`` as the public facade and moves the patch/rollback
execution mechanics into this service module. Planning and normalization remain
wired through the facade while follow-up slices migrate more self-heal logic here.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from core.ci_remediation import normalize_self_heal_plan

if TYPE_CHECKING:
    from typing import Protocol

    class _CodeManagerLike(Protocol):
        def read_file(self, path: str, include_line_numbers: bool = False) -> tuple[bool, str]: ...

        def write_file(
            self, path: str, content: str, include_line_numbers: bool = False
        ) -> tuple[bool, str]: ...

        def patch_file(self, path: str, target: str, replacement: str) -> tuple[bool, str]: ...

        def run_shell_in_sandbox(self, command: str, workdir: str) -> tuple[bool, str]: ...
else:
    _CodeManagerLike = Any


async def restore_self_heal_backups(code: _CodeManagerLike, backups: dict[str, str]) -> None:
    """Restore backed-up file contents after a failed self-heal execution."""

    for path, content in backups.items():
        await asyncio.to_thread(code.write_file, path, content, False)


async def execute_self_heal_plan(
    *,
    code: _CodeManagerLike,
    base_dir: str,
    remediation_loop: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Apply a normalized self-heal patch plan, validate it, and rollback on failure."""

    operations = list(plan.get("operations") or [])
    validation_commands = list(
        plan.get("validation_commands") or remediation_loop.get("validation_commands") or []
    )
    result: dict[str, Any] = {
        "status": "skipped",
        "summary": str(plan.get("summary") or "").strip() or "Self-heal planı uygulanmadı.",
        "operations_applied": [],
        "validation_results": [],
        "reverted": False,
        "confidence": str(plan.get("confidence") or "unknown"),
    }
    if not operations:
        result["summary"] = "Self-heal planı patch operasyonu içermediği için atlandı."
        return result
    if not validation_commands:
        result["status"] = "blocked"
        result["summary"] = "Self-heal planı güvenli doğrulama komutu içermediği için engellendi."
        return result

    allowed_paths = {
        str(path).strip().lstrip("./")
        for path in list(remediation_loop.get("scope_paths") or [])
        if str(path).strip()
    }
    operation_paths = [
        str(item.get("path") or "").strip().lstrip("./")
        for item in operations
        if str(item.get("path") or "").strip()
    ]
    if not allowed_paths:
        result["status"] = "blocked"
        result["summary"] = (
            "Self-heal planı engellendi: remediation_loop içinde scope_paths tanımlı değil "
            "(fail-closed varsayılan; boş kapsam sınırsız dosya erişimi anlamına gelmez)."
        )
        return result
    out_of_scope_paths = sorted({path for path in operation_paths if path not in allowed_paths})
    if out_of_scope_paths:
        result["status"] = "blocked"
        result["summary"] = (
            "Self-heal planı kapsam dışı dosya değiştirmeye çalıştığı için engellendi: "
            f"{', '.join(out_of_scope_paths[:5])}"
        )
        return result

    backups: dict[str, str] = {}
    applied: list[str] = []
    try:
        for item in operations:
            path = str(item.get("path") or "").strip()
            target = str(item.get("target") or "")
            replacement = str(item.get("replacement") or "")
            if path not in backups:
                ok, original = await asyncio.to_thread(code.read_file, path, False)
                if not ok:
                    raise RuntimeError(f"Self-heal yedekleme başarısız: {original}")
                backups[path] = str(original)
            ok, message = await asyncio.to_thread(code.patch_file, path, target, replacement)
            if not ok:
                raise RuntimeError(f"{path} patch edilemedi: {message}")
            applied.append(path)

        for command in validation_commands:
            ok, output = await asyncio.to_thread(code.run_shell_in_sandbox, command, base_dir)
            result["validation_results"].append({"command": command, "ok": ok, "output": output})
            if not ok:
                raise RuntimeError(f"Sandbox doğrulaması başarısız: {command}")

        result["status"] = "applied"
        result["operations_applied"] = applied
        result["summary"] = (
            f"Self-heal başarıyla uygulandı: {len(applied)} patch, "
            f"{len(result['validation_results'])} sandbox doğrulaması geçti."
        )
        return result
    except Exception as exc:
        await restore_self_heal_backups(code, backups)
        result["status"] = "reverted"
        result["reverted"] = True
        result["operations_applied"] = applied
        result["summary"] = f"Self-heal başarısız oldu ve geri alındı: {exc}"
        return result


__all__ = ["execute_self_heal_plan", "normalize_self_heal_plan", "restore_self_heal_backups"]
