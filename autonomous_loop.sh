#!/usr/bin/env bash
set -u

ITERATIONS="${AUTONOMOUS_LOOP_ITERATIONS:-15}"
AUTO_REMEDIATION_MAX_RETRIES="${AUTONOMOUS_LOOP_REMEDIATION_RETRIES:-2}"
RECOVERY_WAIT_SECONDS="${AUTONOMOUS_LOOP_RECOVERY_WAIT_SECONDS:-15}"

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
if ! [[ "$RECOVERY_WAIT_SECONDS" =~ ^[0-9]+$ ]]; then
  RECOVERY_WAIT_SECONDS=15
fi

wait_for_recovery_updates() {
  local before_state="$1"
  local waited=0

  while [ "$waited" -lt "$RECOVERY_WAIT_SECONDS" ]; do
    local current_state
    current_state="$(git status --porcelain 2>/dev/null || true)"
    if [ "$current_state" != "$before_state" ]; then
      echo "[RECOVERY] Çalışma alanında değişiklik algılandı; testler yeniden başlatılıyor."
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done

  echo "[RECOVERY] ${RECOVERY_WAIT_SECONDS}s içinde yeni değişiklik algılanmadı; testler mevcut durumla yeniden çalıştırılacak."
  return 0
}

run_recovery_block() {
  local before_state
  before_state="$(git status --porcelain 2>/dev/null || true)"
  echo "[RECOVERY] Coverage hotspot analizi başlatılıyor..."
  if [ -f "coverage.xml" ]; then
    if uv run python scripts/coverage_hotspots.py --xml coverage.xml --top 20 --root .; then
      wait_for_recovery_updates "$before_state"
    else
      echo "[RECOVERY] coverage_hotspots.py başarısız oldu; bekleme adımı atlandı."
    fi
  else
    echo "[RECOVERY] coverage.xml bulunamadı; hotspot adımı atlandı."
  fi

  echo "[RECOVERY] Otonom self-heal adımı kontrol ediliyor..."
  echo "[RECOVERY] Mypy auto-heal run_tests.sh içinde yönetiliyor; bu katmanda tekrar edilmiyor."
}

echo "[INFO] Otonom döngü başlıyor. Toplam tekrar: $ITERATIONS"

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
