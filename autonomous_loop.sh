#!/usr/bin/env bash
set -u

ITERATIONS="${AUTONOMOUS_LOOP_ITERATIONS:-15}"
AUTO_REMEDIATION_MAX_RETRIES="${AUTONOMOUS_LOOP_REMEDIATION_RETRIES:-2}"

if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [ "$ITERATIONS" -lt 1 ]; then
  echo "[HATA] AUTONOMOUS_LOOP_ITERATIONS pozitif bir tamsayı olmalı. Verilen: $ITERATIONS"
  exit 2
fi

if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "[INFO] Otonom döngü başlıyor. Toplam tekrar: $ITERATIONS"

run_coverage_agent() {
  if [ ! -f "coverage.xml" ]; then
    echo "[HEAL] coverage.xml bulunamadı; CoverageAgent adımı atlandı."
    return 0
  fi

  echo "[HEAL] CoverageAgent tetikleniyor (coverage analizi + test önerisi)..."
  python - <<'PY_COVERAGE_AGENT'
import asyncio
import json

from agent.roles.coverage_agent import CoverageAgent
from config import Config


async def main() -> int:
    agent = CoverageAgent(config=Config())
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
    preview = "\n".join(str(generated).splitlines()[:20])
    print("[CoverageAgent] Örnek test önerisi (ilk 20 satır):")
    print(preview)
    return 0


raise SystemExit(asyncio.run(main()))
PY_COVERAGE_AGENT
}


for ((i=1; i<=ITERATIONS; i++)); do
  echo ""
  echo "========== Döngü $i/$ITERATIONS =========="

  echo "[1/3] Upload: python github_upload.py"
  python github_upload.py
  upload_exit=$?
  if [ "$upload_exit" -ne 0 ]; then
    echo "[HATA] Upload adımı başarısız oldu (exit code: $upload_exit). Döngü durduruluyor."
    exit "$upload_exit"
  fi

  echo "[2/3] Test: ./run_tests.sh"
  ./run_tests.sh
  test_exit=$?

  echo "[3/3] Kontrol: Test çıkış kodu = $test_exit"
  if [ "$test_exit" -ne 0 ]; then
    echo "[UYARI] Test adımı başarısız oldu (exit code: $test_exit). Otonom düzeltme döngüsü başlatılıyor..."

    healed=0
    for ((retry=1; retry<=AUTO_REMEDIATION_MAX_RETRIES; retry++)); do
      echo "[HEAL] Deneme $retry/$AUTO_REMEDIATION_MAX_RETRIES: coverage analizi ve otonom öneri"
      run_coverage_agent || true
      if [ -f "coverage.xml" ]; then
        python scripts/coverage_hotspots.py --xml coverage.xml --top 20 --root . || true
      fi

      if [ -f "artifacts/mypy_errors.log" ]; then
        echo "[HEAL] Local self-heal tetikleniyor (scripts/auto_heal.py)."
        python scripts/auto_heal.py --log artifacts/mypy_errors.log --source mypy --hitl-approve yes || true
      else
        echo "[HEAL] artifacts/mypy_errors.log bulunamadı; auto_heal adımı atlandı."
      fi

      echo "[HEAL] Testler tekrar çalıştırılıyor..."
      ./run_tests.sh
      test_exit=$?
      if [ "$test_exit" -eq 0 ]; then
        healed=1
        echo "[OK] Otonom düzeltme başarılı oldu."
        break
      fi
    done

    if [ "$healed" -ne 1 ]; then
      echo "[HATA] Otonom düzeltme denemeleri tükendi. Döngü durduruluyor (exit code: $test_exit)."
      exit "$test_exit"
    fi
  fi

  echo "[OK] Döngü $i başarıyla tamamlandı."
done

echo ""
echo "[BİTTİ] Upload -> Test -> Kontrol döngüsü $ITERATIONS kez başarıyla tamamlandı."
