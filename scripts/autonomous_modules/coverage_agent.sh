#!/usr/bin/env bash

# Helper functions sourced by autonomous_loop.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

run_coverage_agent() {
  if [ ! -f "${AUTONOMOUS_COVERAGE_XML}" ]; then
    echo "[HEAL] ${AUTONOMOUS_COVERAGE_XML} bulunamadı; CoverageAgent adımı atlandı."
    return 0
  fi

  echo "[HEAL] CoverageAgent tetikleniyor (coverage analizi + test önerisi)..."
  AUTONOMOUS_LOOP_COVERAGE_XML="${AUTONOMOUS_COVERAGE_XML}" \
  AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT="${AUTONOMOUS_COVERAGE_AGENT_LIMIT}" \
  AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE="${AUTONOMOUS_COVERAGE_AGENT_BATCH_SIZE}" \
  AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_LINES="${AUTONOMOUS_COVERAGE_MAX_MISSING_LINES}" \
  AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_BRANCHES="${AUTONOMOUS_COVERAGE_MAX_MISSING_BRANCHES}" \
  AUTONOMOUS_LOOP_EXCLUDE_FILES="${AUTONOMOUS_EXCLUDE_FILES}" \
    uv run python - <<'PY_COVERAGE_AGENT'
import asyncio
import json
import os
from pathlib import Path

from agent.roles.coverage_agent import CoverageAgent
from agent.roles.reviewer_agent import ReviewerAgent
from config import Config


def _static_candidate_rejection_reason(code: str, finding: dict | None = None) -> str:
    return CoverageAgent._candidate_rejection_reason(code, finding=finding or {})


def _looks_trivial_test(code: str) -> bool:
    return bool(_static_candidate_rejection_reason(code))


REJECTION_STATE_PATH = Path(os.getenv("AUTONOMOUS_LOOP_REVIEWER_BLOCK_STATE", "artifacts/coverage_reviewer_rejections.json"))
REVIEWER_GATE_SEMANTIC_CRITERIA = (
    "eksik exception path'i",
    "tautolojik mock kontrolü",
    "hedef modül davranışına bağlanmayan assertion",
    "import-only veya sabit/trivial coverage testi",
)
REVIEWER_GATE_MISSING_REASON = "(neden belirtilmedi)"


def _rejection_signatures(result: dict) -> list[str]:
    signatures: list[str] = []
    for item in result.get("results", []) or []:
        if not isinstance(item, dict) or item.get("status") != "review_rejected":
            continue
        target_path = str(item.get("target_path") or "<unknown>").strip() or "<unknown>"
        review_reason = str(item.get("review_reason") or "<unknown>").strip() or "<unknown>"
        signatures.append(f"{target_path}|{review_reason}")
    return sorted(set(signatures))


def _update_reviewer_block_state(result: dict) -> dict:
    """Aynı hedef+red tipi tekrar ederse otonom döngüyü reviewer blokajı olarak işaretler."""
    signatures = _rejection_signatures(result)
    has_success = any(
        bool(item.get("success")) for item in result.get("results", []) or [] if isinstance(item, dict)
    )
    if has_success:
        if REJECTION_STATE_PATH.exists():
            REJECTION_STATE_PATH.unlink(missing_ok=True)
        return result
    if not signatures:
        return result

    previous_signatures: set[str] = set()
    repeat_count = 1
    if REJECTION_STATE_PATH.exists():
        try:
            previous = json.loads(REJECTION_STATE_PATH.read_text(encoding="utf-8"))
            previous_signatures = set(str(item) for item in previous.get("signatures", []) or [])
            repeat_count = int(previous.get("repeat_count", 1) or 1)
        except Exception as exc:  # noqa: BLE001 - bozuk state dosyası döngüyü kırmamalı.
            print(f"[CoverageAgent] reviewer block state okunamadı; sıfırlanıyor: {exc}")
            previous_signatures = set()
            repeat_count = 1

    repeated = sorted(set(signatures) & previous_signatures)
    if repeated:
        repeat_count += 1
        result["status"] = "blocked_by_reviewer"
        result["success"] = False
        result["blocked_reason"] = "same_target_same_rejection_repeated"
        result["manual_action"] = "Manuel test yazılması gerekiyor; aynı hedef dosya aynı red tipiyle tekrar reddedildi."
        result["repeated_rejections"] = repeated
    else:
        repeat_count = 1

    REJECTION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REJECTION_STATE_PATH.write_text(
        json.dumps(
            {
                "signatures": signatures,
                "repeat_count": repeat_count,
                "status": result.get("status"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


async def _review_with_reviewer_agent(cfg: Config, candidate: str, finding: dict) -> bool:
    reviewer = ReviewerAgent(config=cfg)
    candidate_path = str(finding.get("suggested_test_path") or "")
    result = await reviewer.review_test_candidate(
        candidate,
        finding,
        candidate_path=candidate_path,
    )
    approved = bool(result.get("approved", False))
    reason = str(result.get("reason", "") or "").strip()
    reason_display = reason or REVIEWER_GATE_MISSING_REASON
    weaknesses = list(result.get("weaknesses") or [])[:2]
    candidate_preview = str(result.get("candidate_preview") or "").strip() or "<empty>"
    print(f"[ReviewerAgent] semantic_criteria={REVIEWER_GATE_SEMANTIC_CRITERIA}")
    print(
        "[ReviewerAgent] "
        f"approved={approved} reason={reason_display} attempts={result.get('attempts', 1)} "
        f"target_path={result.get('target_path') or finding.get('target_path', '<unknown>')} "
        f"suggested_test_path={result.get('suggested_test_path') or candidate_path or '<unknown>'} "
        f"finding_index={result.get('finding_index') or finding.get('finding_index', '<unknown>')} "
        f"candidate_preview={candidate_preview}"
    )
    if weaknesses:
        print(f"[ReviewerAgent] weaknesses={weaknesses}")
    elif not approved:
        print("[ReviewerAgent] weaknesses_missing=true")
    if result.get("invalid_reason"):
        print("[ReviewerAgent] invalid_reason=true; boş red gerekçesi fail-closed reddedildi.")
        raw_json = str(result.get("raw_reviewer_json") or "").strip()
        if raw_json:
            print(f"[ReviewerAgent] raw_reviewer_json={raw_json[:1000]}")
    return approved


async def main() -> int:
    cfg = Config()
    agent = CoverageAgent(config=cfg)
    coverage_xml = os.getenv("AUTONOMOUS_LOOP_COVERAGE_XML", "coverage.xml")
    limit = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT", "3") or "3")
    batch_size = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE", "1") or "1")
    max_missing_lines = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_LINES", "25") or "25")
    max_missing_branches = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_BRANCHES", "10") or "10")
    exclude_files = [
        item.strip()
        for item in os.getenv("AUTONOMOUS_LOOP_EXCLUDE_FILES", "").split(",")
        if item.strip()
    ]

    async def reviewer_gate(candidate: str, finding: dict) -> bool:
        static_rejection_reason = _static_candidate_rejection_reason(candidate, finding)
        if static_rejection_reason:
            print(
                "[ReviewerGate] Test önerisi statik kalite filtresinden geçemedi "
                f"(reason={static_rejection_reason}). Reddedildi."
            )
            return False
        approved = await _review_with_reviewer_agent(cfg, str(candidate), finding)
        if not approved:
            print("[ReviewerGate] ReviewerAgent semantik onay vermedi. Öneri uygulanmayacak.")
        return approved

    # run_autonomous_coverage_batch içeride CoverageAgent write_missing_tests aracını çağırır.
    result = await agent.run_autonomous_coverage_batch(
        coverage_xml=coverage_xml,
        coveragerc="pyproject.toml",
        limit=limit,
        batch_size=batch_size,
        append=True,
        reviewer_gate=reviewer_gate,
        max_missing_lines_per_finding=max_missing_lines,
        max_missing_branches_per_finding=max_missing_branches,
        exclude_files=exclude_files,
    )
    result = _update_reviewer_block_state(result)
    print(f"[CoverageAgent] {result.get('summary', 'coverage batch analizi tamamlandı.')}")
    print(
        f"[CoverageAgent] batch_count={result.get('batch_count', 0)} "
        f"total_findings={result.get('total_findings', 0)}"
    )
    for item in result.get("results", []):
        print(
            "[CoverageAgent] "
            f"batch={item.get('batch_index')} finding={item.get('finding_index')} "
            f"status={item.get('status')} target={item.get('target_path')} "
            f"test={item.get('suggested_test_path')}"
        )
    if result.get("status") == "no_gaps_detected":
        print("[CoverageAgent] Coverage açığı bulunamadı.")
        return 0
    if result.get("status") == "blocked_by_reviewer":
        print(
            "[CoverageAgent] status=blocked_by_reviewer reason="
            f"{result.get('blocked_reason')} repeated={result.get('repeated_rejections', [])}"
        )
        print(f"[CoverageAgent] {result.get('manual_action')}")
        return 3
    return 0 if any(item.get("success") for item in result.get("results", [])) else 1


raise SystemExit(asyncio.run(main()))
PY_COVERAGE_AGENT
}
