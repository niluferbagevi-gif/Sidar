#!/usr/bin/env bash
set -u

ITERATIONS="${AUTONOMOUS_LOOP_ITERATIONS:-15}"

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
    echo "[HATA] Test adımı başarısız oldu (exit code: $test_exit). Döngü durduruluyor."
    exit "$test_exit"
  fi

  echo "[OK] Döngü $i başarıyla tamamlandı."
done

echo ""
echo "[BİTTİ] Upload -> Test -> Kontrol döngüsü $ITERATIONS kez başarıyla tamamlandı."
