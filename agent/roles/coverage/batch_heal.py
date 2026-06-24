"""CoverageAgent autonomous batch-heal tool implementation."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.roles.coverage_agent import CoverageAgent


async def run_autonomous_coverage_batch(
    agent: CoverageAgent,
    *,
    coverage_xml: str = "coverage.xml",
    coveragerc: str = ".coveragerc",
    limit: int = 3,
    batch_size: int = 1,
    append: bool = True,
    reviewer_gate: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
    max_missing_lines_per_finding: int = 25,
    max_missing_branches_per_finding: int = 10,
    exclude_files: list[str] | str | None = None,
) -> dict[str, Any]:
    """Generate and write tests for coverage findings in a micro-batch queue."""
    analysis_raw = await agent._tool_analyze_coverage_report(
        json.dumps(
            {"coverage_xml": coverage_xml, "coveragerc": coveragerc, "limit": limit},
            ensure_ascii=False,
        )
    )
    analysis = json.loads(analysis_raw)
    findings = [item for item in list(analysis.get("findings", []) or []) if isinstance(item, dict)]
    original_findings_count = len(findings)
    normalized_exclude_files = agent._normalize_exclude_files(exclude_files)
    excluded_findings: list[dict[str, Any]] = []
    if normalized_exclude_files:
        actionable_findings: list[dict[str, Any]] = []
        for finding in findings:
            target_path = str(finding.get("target_path", "") or "")
            if agent._is_excluded_coverage_target(target_path, normalized_exclude_files):
                excluded_findings.append(
                    {
                        "target_path": target_path,
                        "suggested_test_path": str(finding.get("suggested_test_path", "") or ""),
                    }
                )
                logging.info(
                    "[CoverageAgent] Coverage hedefi exclude listesinde olduğu için "
                    "otonom kuyruktan çıkarıldı: %s",
                    target_path,
                )
                continue
            actionable_findings.append(finding)
        findings = actionable_findings
    batches = agent._build_finding_batches(findings, batch_size=batch_size, max_findings=limit)
    results: list[dict[str, Any]] = []

    for batch_index, batch in enumerate(batches, start=1):
        for finding_index, finding in enumerate(batch, start=1):
            suggested_test_path = str(
                finding.get("suggested_test_path")
                or agent._suggest_test_path(str(finding.get("target_path", "") or ""))
            )
            scoped_finding = agent._cap_autonomous_finding_scope(
                finding,
                max_missing_lines=max_missing_lines_per_finding,
                max_missing_branches=max_missing_branches_per_finding,
            )
            generated = await agent._tool_generate_missing_tests(
                json.dumps(
                    {
                        "coverage_finding": scoped_finding,
                        "coveragerc": analysis.get("coveragerc", {}),
                    },
                    ensure_ascii=False,
                )
            )
            generated = agent._clean_code_output(generated)
            candidate_rejection_reason = agent._candidate_rejection_reason(
                generated, finding=finding
            )
            if candidate_rejection_reason:
                results.append(
                    {
                        "success": False,
                        "status": "review_rejected",
                        "batch_index": batch_index,
                        "finding_index": finding_index,
                        "target_path": finding.get("target_path", ""),
                        "suggested_test_path": suggested_test_path,
                        "review_reason": candidate_rejection_reason,
                        "generated_test_candidate": generated,
                    }
                )
                continue

            (
                isolated_ok,
                isolated_reason,
                isolated_details,
            ) = await agent._validate_candidate_with_isolated_pytest(
                suggested_test_path=suggested_test_path,
                generated_test=generated,
            )
            if not isolated_ok:
                results.append(
                    {
                        "success": False,
                        "status": "review_rejected",
                        "batch_index": batch_index,
                        "finding_index": finding_index,
                        "target_path": finding.get("target_path", ""),
                        "suggested_test_path": suggested_test_path,
                        "review_reason": isolated_reason,
                        "generated_test_candidate": generated,
                        "validation": isolated_details,
                    }
                )
                continue

            approved = True
            review_reason = "reviewer_gate_not_configured"
            review_error = ""
            if reviewer_gate is not None:
                gate_finding = {
                    **finding,
                    "batch_index": batch_index,
                    "finding_index": finding_index,
                    "suggested_test_path": suggested_test_path,
                }
                try:
                    approved = bool(await reviewer_gate(generated, gate_finding))
                except Exception as exc:  # noqa: BLE001 - fail closed when reviewer gate errors.
                    approved = False
                    review_reason = f"reviewer_gate_exception:{exc.__class__.__name__}"
                    review_error = str(exc)
                else:
                    review_reason = "approved" if approved else "rejected"
            if not approved:
                rejected_result = {
                    "success": False,
                    "status": "review_rejected",
                    "batch_index": batch_index,
                    "finding_index": finding_index,
                    "target_path": finding.get("target_path", ""),
                    "suggested_test_path": suggested_test_path,
                    "review_reason": review_reason,
                    "generated_test_candidate": generated,
                }
                if review_error:
                    rejected_result["review_error"] = review_error
                results.append(rejected_result)
                continue

            write_raw = await agent._tool_write_missing_tests(
                json.dumps(
                    {
                        "suggested_test_path": suggested_test_path,
                        "generated_test": generated,
                        "append": append,
                    },
                    ensure_ascii=False,
                )
            )
            write_result = json.loads(write_raw)
            results.append(
                {
                    "success": bool(write_result.get("success", False)),
                    "status": "tests_written" if write_result.get("success") else "write_failed",
                    "batch_index": batch_index,
                    "finding_index": finding_index,
                    "target_path": finding.get("target_path", ""),
                    "suggested_test_path": suggested_test_path,
                    "write_result": write_result,
                }
            )

    status = "batch_completed"
    if not findings:
        status = "no_actionable_findings" if excluded_findings else "no_gaps_detected"

    return {
        "success": any(item.get("success") for item in results) if results else True,
        "status": status,
        "summary": analysis.get("summary", ""),
        "total_findings": len(findings),
        "original_total_findings": original_findings_count,
        "excluded_findings_count": len(excluded_findings),
        "excluded_findings": excluded_findings,
        "exclude_files": normalized_exclude_files,
        "batch_count": len(batches),
        "results": results,
    }


async def tool_autonomous_batch_heal(agent: CoverageAgent, arg: str) -> str:
    payload = agent._parse_payload(arg)
    exclude_files = agent._normalize_exclude_files(
        payload.get("exclude_files") if "exclude_files" in payload else None
    )
    result = await agent.run_autonomous_coverage_batch(
        coverage_xml=str(payload.get("coverage_xml", "coverage.xml") or "coverage.xml"),
        coveragerc=str(payload.get("coveragerc", ".coveragerc") or ".coveragerc"),
        limit=int(payload.get("limit", 3) or 3),
        batch_size=int(payload.get("batch_size", 1) or 1),
        append=bool(payload.get("append", True)),
        max_missing_lines_per_finding=int(payload.get("max_missing_lines_per_finding", 25) or 25),
        max_missing_branches_per_finding=int(
            payload.get("max_missing_branches_per_finding", 10) or 10
        ),
        exclude_files=exclude_files,
    )
    return json.dumps(result, ensure_ascii=False)
