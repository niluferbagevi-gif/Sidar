#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

ITERATIONS="${AUTONOMOUS_LOOP_ITERATIONS:-15}"
AUTO_REMEDIATION_MAX_RETRIES="${AUTONOMOUS_LOOP_REMEDIATION_RETRIES:-2}"
AUTONOMOUS_COVERAGE_TARGET="${AUTONOMOUS_LOOP_COVERAGE_TARGET:-100}"
AUTONOMOUS_COVERAGE_JSON="${AUTONOMOUS_LOOP_COVERAGE_JSON:-coverage.json}"
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
  if [ ! -f "coverage.xml" ]; then
    echo "[HEAL] coverage.xml bulunamadı; CoverageAgent adımı atlandı."
    return 0
  fi

  echo "[HEAL] CoverageAgent tetikleniyor (coverage analizi + test önerisi)..."
  uv run python - <<'PY_COVERAGE_AGENT'
import asyncio
import json
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
    prompt = (
        "Aşağıdaki pytest test önerisini anlamsal kalite açısından incele. "
        "Özellikle 'assert True' gibi anlamsız assertion, zayıf doğrulama, "
        "yan etkili/deterministik olmayan kullanım var mı değerlendir. "
        "Sadece JSON döndür: {\"approved\": bool, \"reason\": str}.\n\n"
        f"[COVERAGE_FINDING]\n{json.dumps(finding, ensure_ascii=False)}\n\n"
        f"[TEST_CANDIDATE]\n{candidate[:6000]}"
    )
    try:
        verdict_raw = await reviewer.call_llm(
            [{"role": "user", "content": prompt}],
            system_prompt=ReviewerAgent.SYSTEM_PROMPT,
            temperature=0.0,
            json_mode=True,
        )
        verdict = json.loads(str(verdict_raw or "{}"))
        approved = bool(verdict.get("approved", False))
        reason = str(verdict.get("reason", "")).strip() or "ReviewerAgent gerekçe üretmedi."
        print(f"[ReviewerAgent] approved={approved} reason={reason}")
        return approved
    except Exception as exc:
        print(f"[ReviewerAgent] Semantic review başarısız: {exc}")
        return False


async def main() -> int:
    cfg = Config()
    agent = CoverageAgent(config=cfg)
    payload = {"coverage_xml": "coverage.xml", "coveragerc": ".coveragerc", "limit": 10}
    raw = await agent._tool_analyze_coverage_report(json.dumps(payload, ensure_ascii=False))  # noqa: SLF001
    data = json.loads(raw)
    findings = data.get("findings", [])
    print(f"[CoverageAgent] {data.get('summary', 'coverage analizi tamamlandı.')}")
    if not findings:
        print("[CoverageAgent] Coverage açığı bulunamadı.")
        return 0

    first = findings[0]
    candidate_payload = {
        "coverage_finding": first,
        "coveragerc": data.get("coveragerc", {}),
    }
    generated = await agent._tool_generate_missing_tests(json.dumps(candidate_payload, ensure_ascii=False))  # noqa: SLF001

    if _looks_trivial_test(generated):
        print("[ReviewerGate] Test önerisi anlamsız/trivial görünüyor (örn. assert True). Reddedildi.")
        return 1

    approved = await _review_with_reviewer_agent(cfg, str(generated), first)
    if not approved:
        print("[ReviewerGate] ReviewerAgent semantik onay vermedi. Öneri uygulanmayacak.")
        return 1

    preview = "\n".join(str(generated).splitlines()[:20])
    print("[CoverageAgent] Reviewer onaylı örnek test önerisi (ilk 20 satır):")
    print(preview)
    return 0


raise SystemExit(asyncio.run(main()))
PY_COVERAGE_AGENT
}


for ((i=1; i<=ITERATIONS; i++)); do
  echo ""
  echo "========== Döngü $i/$ITERATIONS =========="

  echo "[1/3] Upload: uv run python github_upload.py"
  uv run python github_upload.py
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
      if [ -f "coverage.xml" ]; then
        uv run python scripts/coverage_hotspots.py --xml coverage.xml --top 20 --root . || true
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