#!/usr/bin/env bash
set -u

ITERATIONS="${AUTONOMOUS_LOOP_ITERATIONS:-15}"
RECOVERY_ATTEMPTS="${AUTONOMOUS_LOOP_RECOVERY_ATTEMPTS:-1}"

if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [ "$ITERATIONS" -lt 1 ]; then
  echo "[HATA] AUTONOMOUS_LOOP_ITERATIONS pozitif bir tamsayı olmalı. Verilen: $ITERATIONS"
  exit 2
fi

if ! [[ "$RECOVERY_ATTEMPTS" =~ ^[0-9]+$ ]]; then
  echo "[HATA] AUTONOMOUS_LOOP_RECOVERY_ATTEMPTS sıfır veya pozitif bir tamsayı olmalı. Verilen: $RECOVERY_ATTEMPTS"
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
  if [ "$test_exit" -ne 0 ] && [ "$RECOVERY_ATTEMPTS" -gt 0 ]; then
    echo "[UYARI] Test/Coverage başarısız (exit: $test_exit). Otonom iyileştirme denenecek."
    for ((attempt=1; attempt<=RECOVERY_ATTEMPTS; attempt++)); do
      echo "[RECOVERY ${attempt}/${RECOVERY_ATTEMPTS}] Coverage hotspot analizi"
      python scripts/coverage_hotspots.py --xml coverage.xml --top 10 --root . || \
        echo "[UYARI] coverage_hotspots analizi yapılamadı (coverage.xml henüz yok olabilir)."

      if [ -f "tests/pytest.log" ]; then
        echo "[RECOVERY ${attempt}/${RECOVERY_ATTEMPTS}] Auto-heal: scripts.auto_heal (source=coverage)"
        python -m scripts.auto_heal --log tests/pytest.log --source coverage || \
          echo "[UYARI] scripts.auto_heal başarısız oldu; bir sonraki adıma geçiliyor."
      else
        echo "[UYARI] tests/pytest.log bulunamadı; auto-heal adımı atlandı."
      fi

      echo "[RECOVERY ${attempt}/${RECOVERY_ATTEMPTS}] Testler yeniden çalıştırılıyor..."
      ./run_tests.sh
      retry_exit=$?
      if [ "$retry_exit" -eq 0 ]; then
        test_exit=0
        echo "[OK] Otonom recovery başarılı; test/coverage tekrarında geçildi."
        break
      fi
      test_exit=$retry_exit
    done
  fi

  if [ "$test_exit" -ne 0 ]; then
    echo "[HATA] Test adımı recovery sonrası da başarısız (exit code: $test_exit). Döngü durduruluyor."
    exit "$test_exit"
  fi

  echo "[OK] Döngü $i başarıyla tamamlandı."
done

echo ""
echo "[BİTTİ] Upload -> Test -> Kontrol döngüsü $ITERATIONS kez başarıyla tamamlandı."
