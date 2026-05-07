#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

ITERATIONS="${AUTONOMOUS_LOOP_ITERATIONS:-15}"
AUTO_REMEDIATION_MAX_RETRIES="${AUTONOMOUS_LOOP_REMEDIATION_RETRIES:-2}"
AUTONOMOUS_COVERAGE_TARGET="${AUTONOMOUS_LOOP_COVERAGE_TARGET:-100}"
AUTONOMOUS_COVERAGE_JSON="${AUTONOMOUS_LOOP_COVERAGE_JSON:-coverage.json}"
AUTONOMOUS_COVERAGE_XML="${AUTONOMOUS_LOOP_COVERAGE_XML:-coverage.xml}"
AUTONOMOUS_COVERAGE_AGENT_LIMIT="${AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT:-10}"
AUTONOMOUS_COVERAGE_AGENT_BATCH_SIZE="${AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE:-1}"
if ! [[ "$AUTO_REMEDIATION_MAX_RETRIES" =~ ^[0-9]+$ ]] || [ "$AUTO_REMEDIATION_MAX_RETRIES" -lt 1 ]; then
  AUTO_REMEDIATION_MAX_RETRIES=2
fi
if [ "$AUTO_REMEDIATION_MAX_RETRIES" -gt 2 ]; then
  echo "[UYARI] Sonsuz döngü riskini sınırlamak için AUTO_REMEDIATION_MAX_RETRIES=2 olarak sınırlandı."
  AUTO_REMEDIATION_MAX_RETRIES=2
fi

if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [ "$ITERATIONS" -lt 1 ]; then
  echo "[HATA] AUTONOMOUS_LOOP_ITERATIONS pozitif bir tamsayı olmalı. Verilen: $ITERATIONS"
  exit 2
fi

if ! [[ "$AUTONOMOUS_COVERAGE_TARGET" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "[HATA] AUTONOMOUS_LOOP_COVERAGE_TARGET sayısal bir yüzde olmalı. Verilen: $AUTONOMOUS_COVERAGE_TARGET"
  exit 2
fi

if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "[INFO] Otonom döngü başlıyor. Toplam tekrar: $ITERATIONS"
echo "[INFO] CI/CD ve hızlı yerel testler run_tests.sh/.coveragerc eşiğini korur; otonom döngü hedefi: %${AUTONOMOUS_COVERAGE_TARGET}."
echo "[INFO] Otonom coverage metriği '${AUTONOMOUS_COVERAGE_JSON}' üzerinden okunacak."

read_coverage_percent() {
  local coverage_json="${1:-coverage.json}"

  if [ ! -f "${coverage_json}" ]; then
    echo "[UYARI] ${coverage_json} bulunamadı; coverage hedefi değerlendirilemiyor." >&2
    return 2
  fi

  python - "${coverage_json}" <<'PY_COVERAGE_PERCENT'
import json
import sys
from pathlib import Path

coverage_path = Path(sys.argv[1])
try:
    payload = json.loads(coverage_path.read_text(encoding="utf-8"))
    percent = payload["totals"]["percent_covered"]
except Exception as exc:  # noqa: BLE001 - shell kullanıcılarına net hata vermek için geniş yakalanır.
    print(f"[UYARI] {coverage_path} okunamadı veya totals.percent_covered içermiyor: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

try:
    print(f"{float(percent):.2f}")
except (TypeError, ValueError) as exc:
    print(f"[UYARI] {coverage_path} içindeki percent_covered sayısal değil: {percent!r}", file=sys.stderr)
    raise SystemExit(2) from exc
PY_COVERAGE_PERCENT
}

coverage_target_reached() {
  local current_percent="$1"
  local target_percent="$2"

  python - "${current_percent}" "${target_percent}" <<'PY_COVERAGE_COMPARE'
from decimal import Decimal, InvalidOperation
import sys

try:
    current = Decimal(sys.argv[1])
    target = Decimal(sys.argv[2])
except (InvalidOperation, IndexError) as exc:
    print(f"[UYARI] Coverage karşılaştırması için geçersiz değer: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

if current >= target:
    raise SystemExit(0)
raise SystemExit(1)
PY_COVERAGE_COMPARE
}

check_autonomous_quality_gate() {
  local test_exit="$1"
  local current_percent
  local coverage_status

  if [ "${test_exit}" -ne 0 ]; then
    echo "[UYARI] Test adımı başarısız oldu (exit code: ${test_exit})."
    return 1
  fi

  current_percent="$(read_coverage_percent "${AUTONOMOUS_COVERAGE_JSON}")"
  coverage_status=$?
  if [ "${coverage_status}" -ne 0 ]; then
    echo "[UYARI] Testler geçti fakat otonom coverage metriği okunamadı; iyileştirme döngüsü tetiklenecek."
    return 2
  fi

  if coverage_target_reached "${current_percent}" "${AUTONOMOUS_COVERAGE_TARGET}"; then
    echo "[OK] Otonom coverage hedefi sağlandı: %${current_percent} >= %${AUTONOMOUS_COVERAGE_TARGET}."
    return 0
  fi

  echo "[UYARI] Testler geçti, ancak otonom coverage hedefi henüz sağlanmadı: %${current_percent} < %${AUTONOMOUS_COVERAGE_TARGET}."
  return 3
}

run_coverage_agent() {
  if [ ! -f "${AUTONOMOUS_COVERAGE_XML}" ]; then
    echo "[HEAL] ${AUTONOMOUS_COVERAGE_XML} bulunamadı; CoverageAgent adımı atlandı."
    return 0
  fi

  echo "[HEAL] CoverageAgent tetikleniyor (coverage analizi + test önerisi)..."
  AUTONOMOUS_LOOP_COVERAGE_XML="${AUTONOMOUS_COVERAGE_XML}" \
  AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT="${AUTONOMOUS_COVERAGE_AGENT_LIMIT}" \
  AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE="${AUTONOMOUS_COVERAGE_AGENT_BATCH_SIZE}" \
    uv run python - <<'PY_COVERAGE_AGENT'
import asyncio
import os
import re

from agent.roles.coverage_agent import CoverageAgent
from agent.roles.reviewer_agent import ReviewerAgent
from config import Config


def _looks_trivial_test(code: str) -> bool:
    txt = str(code or "")
    if not txt.strip():
        return True
    if re.search(r"assert\s+True\b", txt):
        return True
    if "def test_" in txt and "assert " not in txt and "pytest.raises" not in txt:
        return True
    return False


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
    weaknesses = result.get("weaknesses") or []
    candidate_preview = str(result.get("candidate_preview") or "").strip() or "<empty>"
    print(
        "[ReviewerAgent] "
        f"approved={approved} reason={reason or '<empty>'} attempts={result.get('attempts', 1)} "
        f"target_path={result.get('target_path') or finding.get('target_path', '<unknown>')} "
        f"suggested_test_path={result.get('suggested_test_path') or candidate_path or '<unknown>'} "
        f"finding_index={result.get('finding_index') or finding.get('finding_index', '<unknown>')} "
        f"candidate_preview={candidate_preview}"
    )
    if weaknesses:
        print(f"[ReviewerAgent] weaknesses={list(weaknesses)[:2]}")
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
    limit = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT", "10") or "10")
    batch_size = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE", "1") or "1")

    async def reviewer_gate(candidate: str, finding: dict) -> bool:
        if _looks_trivial_test(candidate):
            print("[ReviewerGate] Test önerisi anlamsız/trivial görünüyor (örn. assert True). Reddedildi.")
            return False
        approved = await _review_with_reviewer_agent(cfg, str(candidate), finding)
        if not approved:
            print("[ReviewerGate] ReviewerAgent semantik onay vermedi. Öneri uygulanmayacak.")
        return approved

    # run_autonomous_coverage_batch içeride CoverageAgent write_missing_tests aracını çağırır.
    result = await agent.run_autonomous_coverage_batch(
        coverage_xml=coverage_xml,
        coveragerc=".coveragerc",
        limit=limit,
        batch_size=batch_size,
        append=True,
        reviewer_gate=reviewer_gate,
    )
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
    return 0 if any(item.get("success") for item in result.get("results", [])) else 1


raise SystemExit(asyncio.run(main()))
PY_COVERAGE_AGENT
}

run_post_coverage_static_heal() {
  local ruff_exit
  local mypy_exit

  echo "[HEAL] CoverageAgent sonrası hızlı statik kontrol: uv run ruff check ."
  uv run ruff check .
  ruff_exit=$?
  if [ "${ruff_exit}" -ne 0 ]; then
    echo "[HEAL] ruff check sorun bildirdi (exit code: ${ruff_exit}); run_tests.sh öncesi akış devam edecek."
  fi

  mkdir -p artifacts
  echo "[HEAL] CoverageAgent sonrası hızlı mypy kontrolü: uv run mypy ."
  uv run mypy . > artifacts/mypy_errors.log 2>&1
  mypy_exit=$?
  if [ "${mypy_exit}" -eq 0 ]; then
    echo "Success: no issues found" > artifacts/mypy_errors.log
    echo "[HEAL] Hızlı mypy kontrolü temiz."
    return 0
  fi

  echo "[HEAL] Hızlı mypy kontrolü hata buldu; scripts/auto_heal.py tetikleniyor."
  uv run python scripts/auto_heal.py --log artifacts/mypy_errors.log --source mypy --hitl-approve yes || true
}

run_github_upload() {
  uv run python github_upload.py
}

run_preflight_quality_gate() {
  local test_exit
  local gate_exit
  local upload_exit
  local current_percent
  local coverage_status

  echo ""
  echo "========== Ön Kontrol =========="
  if [ -f "${AUTONOMOUS_COVERAGE_JSON}" ] && [ -f "${AUTONOMOUS_COVERAGE_XML}" ]; then
    echo "[PREFLIGHT 1/3] Mevcut coverage artefaktları bulundu: ${AUTONOMOUS_COVERAGE_JSON}, ${AUTONOMOUS_COVERAGE_XML}"
    current_percent="$(read_coverage_percent "${AUTONOMOUS_COVERAGE_JSON}")"
    coverage_status=$?
    if [ "${coverage_status}" -eq 0 ] && coverage_target_reached "${current_percent}" "${AUTONOMOUS_COVERAGE_TARGET}"; then
      echo "[PREFLIGHT 2/3] Mevcut coverage hedefi sağlıyor: %${current_percent} >= %${AUTONOMOUS_COVERAGE_TARGET}."
    else
      echo "[PREFLIGHT 2/3] Mevcut coverage hedef altında veya okunamadı; testleri çalıştırmadan önce CoverageAgent tetiklenecek."
      run_coverage_agent || true
      run_post_coverage_static_heal || true
    fi
  else
    echo "[PREFLIGHT 1/3] Coverage artefaktı eksik (${AUTONOMOUS_COVERAGE_JSON}/${AUTONOMOUS_COVERAGE_XML}); önce ./run_tests.sh ile üretilecek."
  fi

  echo "[PREFLIGHT 2/3] Test: ./run_tests.sh"
  ./run_tests.sh
  test_exit=$?

  echo "[PREFLIGHT 3/3] Kontrol: Test çıkış kodu = $test_exit; coverage hedefi = %${AUTONOMOUS_COVERAGE_TARGET}"
  check_autonomous_quality_gate "$test_exit"
  gate_exit=$?

  if [ "$gate_exit" -ne 0 ]; then
    echo "[PREFLIGHT] Kalite kapısı sağlanmadı (durum: $gate_exit); ${ITERATIONS} döngülük otonom onarım akışı başlatılacak."
    return 1
  fi

  echo "[PREFLIGHT] Kod zaten sağlıklı; gereksiz otonom onarım döngüsü atlanıyor."
  echo "[PREFLIGHT] Upload: uv run python github_upload.py"
  run_github_upload
  upload_exit=$?
  if [ "$upload_exit" -ne 0 ]; then
    echo "[HATA] Ön kontrol sonrası upload adımı başarısız oldu (exit code: $upload_exit)."
    exit "$upload_exit"
  fi

  echo "[BİTTİ] Ön kontrol başarıyla geçti; upload tamamlandı, otonom döngü çalıştırılmadı."
  exit 0
}


run_preflight_quality_gate

for ((i=1; i<=ITERATIONS; i++)); do
  echo ""
  echo "========== Döngü $i/$ITERATIONS =========="

  echo "[1/3] Upload: uv run python github_upload.py"
  run_github_upload
  upload_exit=$?
  if [ "$upload_exit" -ne 0 ]; then
    echo "[HATA] Upload adımı başarısız oldu (exit code: $upload_exit). Döngü durduruluyor."
    exit "$upload_exit"
  fi

  echo "[2/3] Test: ./run_tests.sh"
  ./run_tests.sh
  test_exit=$?

  echo "[3/3] Kontrol: Test çıkış kodu = $test_exit; coverage hedefi = %${AUTONOMOUS_COVERAGE_TARGET}"
  check_autonomous_quality_gate "$test_exit"
  gate_exit=$?
  if [ "$gate_exit" -ne 0 ]; then
    echo "[UYARI] Otonom kalite kapısı sağlanmadı (durum: $gate_exit). Otonom düzeltme/coverage iyileştirme döngüsü başlatılıyor..."

    healed=0
    for ((retry=1; retry<=AUTO_REMEDIATION_MAX_RETRIES; retry++)); do
      echo "[HEAL] Deneme $retry/$AUTO_REMEDIATION_MAX_RETRIES: coverage analizi ve otonom öneri"
      run_coverage_agent || true
      run_post_coverage_static_heal || true
      if [ -f "${AUTONOMOUS_COVERAGE_XML}" ]; then
        uv run python scripts/coverage_hotspots.py --xml "${AUTONOMOUS_COVERAGE_XML}" --top 20 --root . || true
      fi

      if [ -f "artifacts/mypy_errors.log" ]; then
        if grep -qi "Success: no issues found" "artifacts/mypy_errors.log"; then
          echo "[HEAL] Mypy log'u temiz; auto_heal adımı atlandı."
        else
          echo "[HEAL] Local self-heal tetikleniyor (scripts/auto_heal.py)."
          uv run python scripts/auto_heal.py --log artifacts/mypy_errors.log --source mypy --hitl-approve yes || true
        fi
      else
        echo "[HEAL] artifacts/mypy_errors.log bulunamadı; auto_heal adımı atlandı."
      fi

      echo "[HEAL] Testler tekrar çalıştırılıyor..."
      ./run_tests.sh
      test_exit=$?
      check_autonomous_quality_gate "$test_exit"
      gate_exit=$?
      if [ "$gate_exit" -eq 0 ]; then
        healed=1
        echo "[OK] Otonom düzeltme/coverage iyileştirme başarılı oldu."
        break
      fi
    done

    if [ "$healed" -ne 1 ]; then
      if [ "$test_exit" -ne 0 ]; then
        final_exit="$test_exit"
      else
        final_exit=1
      fi
      echo "[HATA] Otonom düzeltme denemeleri tükendi. Döngü durduruluyor (test exit: $test_exit, gate: $gate_exit)."
      exit "$final_exit"
    fi
  fi

  echo "[OK] Döngü $i başarıyla tamamlandı."
done

echo ""
echo "[BİTTİ] Upload -> Test -> Kontrol döngüsü $ITERATIONS kez başarıyla tamamlandı."