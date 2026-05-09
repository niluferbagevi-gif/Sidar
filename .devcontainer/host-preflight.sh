#!/usr/bin/env bash
set -Eeuo pipefail

TIMEOUT_SECONDS="${SIDAR_DEVCONTAINER_PREFLIGHT_TIMEOUT_SECONDS:-20}"
STRICT_MODE="${SIDAR_DEVCONTAINER_PREFLIGHT_STRICT:-0}"

log() { printf 'ℹ️  %s\n' "$*"; }
ok() { printf '✅ %s\n' "$*"; }
warn() { printf '⚠️  %s\n' "$*"; }
fail() { printf '❌ %s\n' "$*"; }

run_with_timeout() {
  local label="$1"
  shift

  if timeout "${TIMEOUT_SECONDS}" "$@" >/tmp/sidar-devcontainer-preflight.out 2>/tmp/sidar-devcontainer-preflight.err; then
    ok "${label} tamamlandı."
    return 0
  fi

  local status=$?
  if [ "${status}" -eq 124 ]; then
    fail "${label} ${TIMEOUT_SECONDS}s içinde tamamlanmadı. Docker Desktop/WSL entegrasyonu hazır olmayabilir."
  else
    fail "${label} başarısız oldu (exit=${status})."
  fi

  if [ -s /tmp/sidar-devcontainer-preflight.err ]; then
    warn "Hata çıktısı: $(tr '\n' ' ' </tmp/sidar-devcontainer-preflight.err | sed 's/[[:space:]]\+/ /g' | cut -c1-500)"
  fi
  return "${status}"
}

log "Sidar Dev Container host preflight başlıyor."

if [ -n "${WSL_DISTRO_NAME:-}" ]; then
  ok "WSL distro algılandı: ${WSL_DISTRO_NAME}."
else
  log "WSL_DISTRO_NAME boş; Linux host veya Codespaces benzeri ortam olabilir."
fi

preflight_failed=0

if ! command -v docker >/dev/null 2>&1; then
  fail "docker CLI bulunamadı. Docker Desktop WSL entegrasyonunu ve PATH ayarını kontrol edin."
  preflight_failed=1
else
  run_with_timeout "docker version" docker version --format '{{.Server.Version}}' || preflight_failed=1
  run_with_timeout "docker info" docker info --format '{{.ServerVersion}} {{.OperatingSystem}}' || preflight_failed=1
fi

if [ "${preflight_failed}" -ne 0 ]; then
  if [ "${STRICT_MODE}" = "1" ] || [ "${STRICT_MODE}" = "true" ]; then
    fail "Sidar Dev Container host preflight başarısız; strict mod açık olduğu için işlem durduruluyor."
    exit 1
  fi
  warn "Sidar Dev Container host preflight uyarı üretti; strict mod kapalı olduğu için Dev Containers akışı devam edecek."
else
  ok "Sidar Dev Container host preflight başarılı."
fi
