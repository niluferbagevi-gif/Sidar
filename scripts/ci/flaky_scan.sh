#!/usr/bin/env bash

set -euo pipefail

RUNS="${FLAKY_RUNS:-5}"
REPORT_DIR="${FLAKY_REPORT_DIR:-artifacts/flaky}"
mkdir -p "$REPORT_DIR"

SUMMARY_TXT="$REPORT_DIR/summary.txt"
DETAILS_LOG="$REPORT_DIR/details.log"
REPORT_MD="$REPORT_DIR/report.md"

DEFAULT_TEST_CMD='uv run pytest -n auto -q --maxfail=1 tests/quality/test_mutation_guards.py tests/quality/test_llm_quality_gate.py tests/smoke/test_imports.py'
TEST_CMD="${FLAKY_TEST_CMD:-$DEFAULT_TEST_CMD}"

echo "Flaky scan başladı: runs=$RUNS" | tee "$SUMMARY_TXT"
echo "Test komutu: $TEST_CMD" | tee -a "$SUMMARY_TXT"
echo "" > "$DETAILS_LOG"

pass_count=0
fail_count=0

for run_no in $(seq 1 "$RUNS"); do
  run_log="$REPORT_DIR/run_${run_no}.log"
  echo "=== Run $run_no/$RUNS ===" | tee -a "$SUMMARY_TXT"
  if bash -lc "$TEST_CMD" >"$run_log" 2>&1; then
    echo "run_$run_no=PASS" | tee -a "$DETAILS_LOG"
    pass_count=$((pass_count + 1))
  else
    echo "run_$run_no=FAIL" | tee -a "$DETAILS_LOG"
    fail_count=$((fail_count + 1))
  fi
done

{
  echo ""
  echo "Toplam PASS: $pass_count"
  echo "Toplam FAIL: $fail_count"
} | tee -a "$SUMMARY_TXT"

{
  echo "# Nightly Flaky Scan Raporu"
  echo ""
  echo "- Çalıştırma sayısı: **$RUNS**"
  echo "- PASS: **$pass_count**"
  echo "- FAIL: **$fail_count**"
  echo "- Test komutu: \`$TEST_CMD\`"
  echo ""
  if [[ "$fail_count" -gt 0 ]]; then
    echo "## Sonuç"
    echo "Flaky sinyali var: tekrarlar arasında sapma gözlendi."
  else
    echo "## Sonuç"
    echo "Flaky sinyali gözlenmedi: tüm tekrarlar geçti."
  fi
  echo ""
  echo "## Run Özeti"
  cat "$DETAILS_LOG"
} > "$REPORT_MD"

if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi
