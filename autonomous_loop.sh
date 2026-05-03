#!/usr/bin/env bash
set -u

ITERATIONS="${AUTONOMOUS_LOOP_ITERATIONS:-15}"
AUTO_REMEDIATION_MAX_RETRIES="${AUTONOMOUS_LOOP_REMEDIATION_RETRIES:-2}"

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

if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

run_recovery_block() {
  echo "[RECOVERY] Coverage hotspot analizi başlatılıyor..."
  if [ -f "coverage.xml" ]; then
    python scripts/coverage_hotspots.py --xml coverage.xml --top 20 --root . || true
  else
    echo "[RECOVERY] coverage.xml bulunamadı; hotspot adımı atlandı."
  fi

  echo "[RECOVERY] Otonom self-heal adımı kontrol ediliyor..."
  if [ -f "artifacts/mypy_errors.log" ]; then
    python scripts/auto_heal.py --log artifacts/mypy_errors.log --source mypy --hitl-approve yes || true
  else
    echo "[RECOVERY] artifacts/mypy_errors.log bulunamadı; auto_heal adımı atlandı."
  fi
}

echo "[INFO] Otonom döngü başlıyor. Toplam tekrar: $ITERATIONS"

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
    echo "[UYARI] Test adımı başarısız oldu. Recovery bloğu devreye alınıyor..."

    healed=0
    for ((retry=1; retry<=AUTO_REMEDIATION_MAX_RETRIES; retry++)); do
      echo "[RECOVERY] Deneme $retry/$AUTO_REMEDIATION_MAX_RETRIES"
      run_recovery_block

      echo "[RECOVERY] Testler yeniden çalıştırılıyor..."
      ./run_tests.sh
      test_exit=$?

      if [ "$test_exit" -eq 0 ]; then
        healed=1
        echo "[OK] Recovery başarılı oldu."
        break
      fi
    done

    if [ "$healed" -ne 1 ]; then
      echo "[HATA] Recovery denemeleri başarısız oldu (exit code: $test_exit). Döngü durduruluyor."
      exit "$test_exit"
    fi
  fi

  echo "[OK] Döngü $i başarıyla tamamlandı."
done

echo ""
echo "[BİTTİ] Upload -> Test -> Kontrol döngüsü $ITERATIONS kez başarıyla tamamlandı."
