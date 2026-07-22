#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2034  # Helpers update run_tests.sh globals after being sourced.
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
