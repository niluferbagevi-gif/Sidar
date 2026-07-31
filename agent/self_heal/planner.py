"""Runtime self-heal patch planning isolated from the Sidar agent facade.

``core.ci_remediation`` owns deterministic failure diagnosis and remediation policy;
this module owns the LLM-facing plan generation step.  Keeping that boundary here
prevents the runtime agent from growing a second copy of remediation policy.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol


class _CodeReader(Protocol):
    def read_file(
        self, path: str, include_line_numbers: bool = False
    ) -> tuple[bool, Any]:
        raise NotImplementedError


class _ChatClient(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        raise NotImplementedError


async def collect_snapshots(code: _CodeReader, scope_paths: list[str]) -> list[dict[str, str]]:
    """Read the bounded source snapshots supplied to the patch-planning model."""
    snapshots: list[dict[str, str]] = []
    for path in scope_paths[:6]:
        normalized = str(path or "").strip().lstrip("./")
        if not normalized:
            continue
        ok, content = await asyncio.to_thread(code.read_file, normalized, False)
        if ok:
            snapshots.append({"path": normalized, "content": str(content)})
    return snapshots


def resolve_scope_batches(
    scope_paths: list[str], remediation_loop: dict[str, Any], *, batch_size: int
) -> list[list[str]]:
    """Normalize explicit or generated autonomous scope batches without duplicates."""
    candidate_batches: list[list[str]] = []
    for item in list(remediation_loop.get("autonomous_batches") or []):
        if not isinstance(item, dict):
            continue
        batch_scope = [
            str(path).strip() for path in list(item.get("scope_paths") or []) if str(path).strip()
        ]
        if batch_scope:
            candidate_batches.append(batch_scope)
    if not candidate_batches:
        size = max(1, batch_size)
        candidate_batches = [
            scope_paths[index : index + size] for index in range(0, len(scope_paths), size)
        ]

    normalized: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for batch_scope in candidate_batches:
        chunk: list[str] = []
        seen_in_chunk: set[str] = set()
        for path in batch_scope:
            if path not in scope_paths or path in seen_in_chunk:
                continue
            seen_in_chunk.add(path)
            chunk.append(path)
        key = tuple(chunk)
        if chunk and key not in seen_keys:
            seen_keys.add(key)
            normalized.append(chunk)
    return normalized


async def build_plan(
    *,
    code: _CodeReader,
    llm: _ChatClient,
    cfg: Any,
    ci_context: dict[str, Any],
    diagnosis: str,
    remediation_loop: dict[str, Any],
    prompt_builder: Callable[..., str],
    plan_normalizer: Callable[..., dict[str, Any]],
    logger: Any,
    range_factory: Callable[..., Any] = range,
) -> dict[str, Any]:
    """Generate a normalized, bounded patch plan for one remediation loop."""
    scope_paths = [
        str(item).strip()
        for item in list(remediation_loop.get("scope_paths") or [])
        if str(item).strip()
    ]
    fallback_commands = list(remediation_loop.get("validation_commands") or [])
    if not scope_paths:
        return {
            "summary": "Self-heal kapsamı boş olduğu için plan oluşturulmadı.",
            "confidence": "unknown",
            "operations": [],
            "validation_commands": fallback_commands,
        }

    max_operations = max(1, int(getattr(cfg, "SELF_HEAL_MAX_PATCHES", 3) or 3))
    timeout_seconds = max(30, int(getattr(cfg, "SELF_HEAL_PLAN_TIMEOUT_SECONDS", 180) or 180))
    max_retries = max(1, int(getattr(cfg, "SELF_HEAL_PLAN_MAX_RETRIES", 3) or 3))
    skip_full_scope_min = max(1, int(getattr(cfg, "SELF_HEAL_SKIP_FULL_SCOPE_MIN_FILES", 6) or 6))
    batch_size = max(1, int(getattr(cfg, "SELF_HEAL_AUTONOMOUS_BATCH_SIZE", 5) or 5))

    async def generate(paths: list[str]) -> dict[str, Any]:
        last_plan: dict[str, Any] | None = None
        for attempt in range_factory(1, max_retries + 1):
            snapshots = await collect_snapshots(code, paths)
            scope_loop = dict(remediation_loop)
            scope_loop["scope_paths"] = paths
            scope_loop["plan_retry"] = {"attempt": attempt, "max_retries": max_retries}
            prompt = prompt_builder(ci_context, diagnosis, scope_loop, snapshots)
            try:
                raw_plan = await asyncio.wait_for(
                    llm.chat(
                        messages=[{"role": "user", "content": prompt}],
                        model=getattr(cfg, "CODING_MODEL", None),
                        temperature=0.1,
                        stream=False,
                        json_mode=True,
                    ),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                logger.warning(
                    "Self-heal plan generation timeout: scope=%s timeout=%ss attempt=%s/%s",
                    ",".join(paths[:6]),
                    timeout_seconds,
                    attempt,
                    max_retries,
                )
                last_plan = {
                    "summary": (
                        "Self-heal planı zaman aşımına uğradı; daha küçük batch ile "
                        "yeniden denenecek."
                    ),
                    "confidence": "unknown",
                    "operations": [],
                    "validation_commands": fallback_commands,
                }
                continue
            except Exception as exc:
                logger.warning(
                    "Self-heal plan generation failed for scope %s at attempt %s/%s: %s",
                    paths,
                    attempt,
                    max_retries,
                    exc,
                )
                last_plan = {
                    "summary": f"Self-heal planı üretilemedi: {exc}",
                    "confidence": "unknown",
                    "operations": [],
                    "validation_commands": fallback_commands,
                }
                continue

            normalized = plan_normalizer(
                raw_plan,
                scope_paths=paths,
                fallback_validation_commands=fallback_commands,
                max_operations=max_operations,
            )
            normalized["plan_attempt"] = attempt
            normalized["plan_max_retries"] = max_retries
            if list(normalized.get("operations") or []):
                return normalized
            last_plan = normalized

        if last_plan is None:
            return {
                "summary": "Self-heal planı üretilemedi; plan deneme döngüsü çalışmadı.",
                "confidence": "unknown",
                "operations": [],
                "validation_commands": fallback_commands,
                "plan_attempt": 0,
                "plan_max_retries": max_retries,
            }
        summary = str(last_plan.get("summary") or "").strip()
        attempts_info = f" (attempts: {max_retries}/{max_retries})"
        last_plan["summary"] = f"{summary}{attempts_info}" if summary else attempts_info.strip()
        last_plan["plan_attempt"] = max_retries
        last_plan["plan_max_retries"] = max_retries
        return last_plan

    attempt_full_scope = len(scope_paths) < skip_full_scope_min and not list(
        remediation_loop.get("autonomous_batches") or []
    )
    fallback_plan: dict[str, Any] | None = None
    if attempt_full_scope:
        initial_plan = await generate(scope_paths)
        if list(initial_plan.get("operations") or []):
            return initial_plan
        fallback_plan = initial_plan

    for chunk in resolve_scope_batches(scope_paths, remediation_loop, batch_size=batch_size):
        batch_plan = await generate(chunk)
        if list(batch_plan.get("operations") or []):
            summary = str(batch_plan.get("summary") or "").strip()
            batch_plan["summary"] = (
                f"{summary} (batch plan: {len(chunk)}/{len(scope_paths)} dosya)"
                if summary
                else f"Batch plan ile patch üretildi: {len(chunk)}/{len(scope_paths)} dosya."
            )
            return batch_plan
        fallback_plan = batch_plan

    return fallback_plan or {
        "summary": "Self-heal planı üretilemedi.",
        "confidence": "unknown",
        "operations": [],
        "validation_commands": fallback_commands,
    }


__all__ = ["build_plan", "collect_snapshots", "resolve_scope_batches"]
