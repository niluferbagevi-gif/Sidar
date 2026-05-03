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
      echo "[HEAL] Deneme $retry/$AUTO_REMEDIATION_MAX_RETRIES: coverage hotspot analizi"
      if [ -f "coverage.xml" ]; then
        python scripts/coverage_hotspots.py --xml coverage.xml --top 20 --root . || true
      else
        echo "[HEAL] coverage.xml bulunamadı; hotspot analizi atlandı."
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