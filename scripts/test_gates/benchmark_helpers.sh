#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2034,SC2153  # Helpers consume/update run_tests.sh globals after sourcing.
# Helper functions sourced by run_tests.sh; do not execute directly.

resolve_benchmark_compare_target() {
  local requested_name="${1:-baseline}"
  local latest_file=""

  BENCHMARK_COMPARE_SELECTOR=""
  BENCHMARK_COMPARE_FILE=""

  if [ ! -d ".benchmarks" ]; then
    return 1
  fi

  if [ "${requested_name}" = "latest" ]; then
    latest_file="$(find .benchmarks -type f -name "*.json" -print 2>/dev/null | sort -V | tail -n 1)"
  else
    latest_file="$(find .benchmarks -type f -name "*_${requested_name}.json" -print 2>/dev/null | sort -V | tail -n 1)"
  fi

  if [ -z "${latest_file}" ]; then
    return 1
  fi

  # pytest-benchmark alias çözümlemesi bazı nested .benchmarks
  # yerleşimlerinde etiketi (örn. "baseline") dosyaya eşleyemeyebiliyor.
  # Bu nedenle karşılaştırma hedefini deterministik olarak bulduğumuz JSON
  # dosyasının tam path'iyle geçiriyoruz.
  BENCHMARK_COMPARE_FILE="${latest_file}"
  BENCHMARK_COMPARE_SELECTOR="${latest_file}"
  return 0
}

# Bir benchmark baseline JSON dosyasının değişiklik zamanından bu yana geçen
# gün sayısını stdout'a yazar. GNU (`stat -c`) ve BSD (`stat -f`) stat
# varyantlarını dener. Dosya yoksa veya mtime okunamazsa 1 döner.
benchmark_baseline_age_days() {
  local baseline_file="${1:-}"
  local mtime now

  if [ -z "${baseline_file}" ] || [ ! -f "${baseline_file}" ]; then
    return 1
  fi

  mtime="$(stat -c %Y "${baseline_file}" 2>/dev/null)" \
    || mtime="$(stat -f %m "${baseline_file}" 2>/dev/null)" \
    || return 1
  now="$(date +%s)"

  echo $(( (now - mtime) / 86400 ))
  return 0
}

run_benchmark_quality_gate() {
# 2) Kritik yol performans baseline testleri (pytest-benchmark)
if [ "${RUN_BENCHMARKS}" = "0" ]; then
  BENCHMARK_COMPARE_STATUS="skipped"
  echo "⚠️ Benchmark testleri RUN_BENCHMARKS=0 ile atlandı."
  if gpu_hardware_available || [ "${USE_GPU:-0}" = "1" ]; then
    echo "⚠️ GPU/hızlandırıcı algılandı; performans regresyonlarını erken yakalamak için benchmark fazını kapatmayın."
    echo "ℹ️ Öneri (lokal GPU): RUN_BENCHMARKS=required bash run_tests.sh"
  fi
  echo "⚠️ Performans regresyonlarının erken tespiti için CI/local pipeline'larda benchmark fazını düzenli çalıştırın."
  echo "ℹ️ Öneri (lokal): RUN_BENCHMARKS=required bash run_tests.sh"
  echo "ℹ️ Öneri (hedefli): uv run pytest -q ${PERFORMANCE_TEST_DIR} --benchmark-json=${BENCHMARK_JSON_OUTPUT}"
elif [ -d "${PERFORMANCE_TEST_DIR}" ]; then
  BENCHMARK_COMPARE_STATUS="not_requested"
  if ! ensure_uv_available || ! ensure_benchmark_tool_dependencies; then
    echo "❌ Benchmark önkoşulları hazırlanamadı."
    echo "   Bağımlılık kurulumu tamamlandıktan sonra yerel ilk baseline için: make benchmark-seed"
    BENCHMARK_EXIT_CODE=1
  fi
  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ]; then
    echo "📊 Aşama 2: Performans benchmark testleri tek çekirdek üzerinde koşturuluyor..."
  else
    echo "⚠️ Benchmark komutu önkoşul hatası nedeniyle çalıştırılmayacak."
  fi
  benchmark_dotenv_file="${DOTENV_FILE:-.env.test}"
  mkdir -p "$(dirname "${BENCHMARK_JSON_OUTPUT}")"
  benchmark_cmd=(
    env "DOTENV_FILE=${benchmark_dotenv_file}" uv run python -m pytest -c pyproject.toml -v "${PERFORMANCE_TEST_DIR}" -n 0 --no-cov
    --benchmark-save="${BENCHMARK_BASELINE_NAME}"
    --benchmark-json="${BENCHMARK_JSON_OUTPUT}"
    --benchmark-warmup="${BENCHMARK_WARMUP}"
    --benchmark-warmup-iterations="${BENCHMARK_WARMUP_ITERATIONS}"
  )
  if [ "${BENCHMARK_DISABLE_GC}" = "1" ]; then
    benchmark_cmd+=(--benchmark-disable-gc)
  fi

  benchmark_compare_target_found=0
  if [ "${BENCHMARK_ENABLE_COMPARE}" = "1" ]; then
    if resolve_benchmark_compare_target "${BENCHMARK_COMPARE_NAME}"; then
      benchmark_compare_target_found=1
      benchmark_cmd+=(--benchmark-compare="${BENCHMARK_COMPARE_SELECTOR}")
      benchmark_baseline_age_days_value="$(benchmark_baseline_age_days "${BENCHMARK_COMPARE_FILE}" 2>/dev/null || true)"
      if [ -n "${benchmark_baseline_age_days_value}" ] \
        && [ "${benchmark_baseline_age_days_value}" -ge "${BENCHMARK_BASELINE_MAX_AGE_DAYS}" ]; then
        if [ "${BENCHMARK_ENFORCE_COMPARE}" = "1" ]; then
          BENCHMARK_COMPARE_STATUS="stale_required"
          BENCHMARK_EXIT_CODE=1
          echo "❌ Benchmark baseline ${benchmark_baseline_age_days_value} gündür yenilenmedi (eşik: ${BENCHMARK_BASELINE_MAX_AGE_DAYS} gün): ${BENCHMARK_COMPARE_FILE}"
          echo "ℹ️ Sıkı karşılaştırma bayat baseline ile devam edemez; 'make benchmark-seed' ile yenileyin."
        else
          echo "⚠️ Benchmark baseline ${benchmark_baseline_age_days_value} gündür yenilenmedi (eşik: ${BENCHMARK_BASELINE_MAX_AGE_DAYS} gün): ${BENCHMARK_COMPARE_FILE}"
          echo "ℹ️ Bayat bir baseline'a karşı rapor karşılaştırması yanıltıcı olabilir; 'make benchmark-seed' ile yenileyin."
        fi
      fi
      if [ "${BENCHMARK_ENFORCE_COMPARE}" = "1" ]; then
        if [ "${BENCHMARK_COMPARE_STATUS}" != "stale_required" ]; then
          BENCHMARK_COMPARE_STATUS="compared_enforced"
          echo "📈 Benchmark karşılaştırma kapısı etkin (--benchmark-compare=${BENCHMARK_COMPARE_SELECTOR}; baseline=${BENCHMARK_COMPARE_FILE}; regresyon_eşiği=${BENCHMARK_COMPARE_FAIL})."
          benchmark_cmd+=(--benchmark-compare-fail="${BENCHMARK_COMPARE_FAIL}")
        fi
      else
        BENCHMARK_COMPARE_STATUS="compared_report_only"
        echo "⚠️ Benchmark karşılaştırması rapor modunda (--benchmark-compare=${BENCHMARK_COMPARE_SELECTOR}; baseline=${BENCHMARK_COMPARE_FILE})."
        echo "ℹ️ Varsayılan sıkı kapıyı geçici rapor moduna almak için BENCHMARK_ENFORCE_COMPARE=0 kullanın."
      fi
    else
      BENCHMARK_COMPARE_STATUS="missing_baseline"
      echo "⚠️ Benchmark karşılaştırması atlandı: '.benchmarks' altında '${BENCHMARK_COMPARE_NAME}' etiketiyle eşleşen kayıt bulunamadı."
      echo "ℹ️ İlk benchmark koşusu --benchmark-save=${BENCHMARK_BASELINE_NAME} ile baseline kaydedecek; sonraki koşularda otomatik karşılaştırma yapılacak."
      echo "ℹ️ İlk makine/bootstrap istisnası: BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh"
      echo "ℹ️ Sıkı karşılaştırma: BENCHMARK_COMPARE_REQUIRED=1 BENCHMARK_ENFORCE_COMPARE=1 RUN_BENCHMARKS=required ./run_tests.sh"
      echo "ℹ️ CI, .benchmarks baseline'ını repo commit'i yerine GitHub Actions cache/artifact üzerinden seed/restore eder."
      if [ "${BENCHMARK_COMPARE_REQUIRED}" = "1" ]; then
        if [ "${IS_CI_ENV}" -eq 1 ]; then
          BENCHMARK_COMPARE_STATUS="missing_required"
          echo "❌ BENCHMARK_COMPARE_REQUIRED=1 iken karşılaştırma için baseline bulunamadı."
          echo "ℹ️ CI bootstrap için cache/artifact baseline restore edin veya seed job'ında BENCHMARK_COMPARE_REQUIRED=0 kullanın."
          BENCHMARK_EXIT_CODE=1
        elif production_readiness_gate_active; then
          BENCHMARK_COMPARE_STATUS="missing_required"
          echo "❌ Local production-readiness için benchmark baseline bulunamadı."
          echo "➡️ Önerilen tek aksiyon: make benchmark-seed && make production-readiness"
          echo "   İlk komut .benchmarks baseline'ını üretir; ikinci komut release/merge kapısını karşılaştırmalı yeniden koşar."
          BENCHMARK_EXIT_CODE=1
        else
          echo "⚠️ Yerel bootstrap: BENCHMARK_COMPARE_REQUIRED=1 olsa da baseline bulunamadığı için ilk benchmark koşusu karşılaştırmasız çalıştırılacak."
          echo "ℹ️ Bu koşu --benchmark-save=${BENCHMARK_BASELINE_NAME} ile baseline seed eder; sonraki yerel koşular tekrar sıkı karşılaştırmaya döner."
        fi
      fi
    fi
  else
    BENCHMARK_COMPARE_STATUS="disabled"
    echo "ℹ️ Benchmark karşılaştırması devre dışı (BENCHMARK_ENABLE_COMPARE=0)."
  fi

  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ]; then
    echo "➡️ Çalıştırılan komut: ${benchmark_cmd[*]}"
    run_checked "${benchmark_cmd[@]}"
    BENCHMARK_EXIT_CODE=$?
  fi

  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ] && [ -f "${BENCHMARK_JSON_OUTPUT}" ]; then
    echo "✅ Benchmark JSON raporu oluşturuldu: ${BENCHMARK_JSON_OUTPUT}"
    if [ "${BENCHMARK_ENABLE_COMPARE}" = "1" ] && [ "${benchmark_compare_target_found}" = "0" ]; then
      if resolve_benchmark_compare_target "${BENCHMARK_COMPARE_NAME}"; then
        BENCHMARK_COMPARE_STATUS="seeded_not_compared"
        echo "✅ Benchmark baseline kaydı hazır: ${BENCHMARK_COMPARE_FILE}"
        echo "ℹ️ Sonraki benchmark koşusunda --benchmark-compare=${BENCHMARK_COMPARE_SELECTOR} otomatik kullanılacak."
      else
        BENCHMARK_COMPARE_STATUS="seed_missing"
        echo "⚠️ Benchmark JSON üretildi ancak .benchmarks altında '${BENCHMARK_COMPARE_NAME}' baseline kaydı doğrulanamadı."
      fi
    fi
  elif [ "${BENCHMARK_EXIT_CODE}" -eq 0 ]; then
    echo "⚠️ Benchmark testleri geçti ancak JSON raporu bulunamadı: ${BENCHMARK_JSON_OUTPUT}"
    BENCHMARK_EXIT_CODE=1
  fi

  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ] && [ "${BENCHMARK_TREND_COMPARE}" = "1" ]; then
    if [ -f "coverage.xml" ] && [ -f "${BENCHMARK_JSON_OUTPUT}" ]; then
      echo "📉 Benchmark trend + coverage.xml karşılaştırması çalıştırılıyor..."
      if ! python scripts/ci/check_benchmark_coverage_trend.py \
        --benchmark-json "${BENCHMARK_JSON_OUTPUT}" \
        --coverage-xml coverage.xml \
        --history-json "${BENCHMARK_TREND_HISTORY}" \
        --window "${BENCHMARK_TREND_WINDOW}" \
        --max-regression-pct "${BENCHMARK_TREND_MAX_REGRESSION_PCT}"; then
        echo "❌ Benchmark trend karşılaştırması kalite kapısından kaldı."
        BENCHMARK_EXIT_CODE=1
      fi
    else
      echo "⚠️ Benchmark trend karşılaştırması atlandı: coverage.xml veya benchmark JSON bulunamadı."
      BENCHMARK_EXIT_CODE=1
    fi
  fi
else
  BENCHMARK_COMPARE_STATUS="benchmark_dir_missing"
  echo "⚠️ Benchmark testi atlandı: ${PERFORMANCE_TEST_DIR} bulunamadı."
  if [ "${RUN_BENCHMARKS}" = "required" ]; then
    echo "❌ RUN_BENCHMARKS=required iken benchmark dizini bulunamadı."
    BENCHMARK_EXIT_CODE=1
  fi
fi

}
