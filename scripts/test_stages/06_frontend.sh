# shellcheck shell=bash
# shellcheck disable=SC2034
# This file is sourced by run_tests.sh and expects its functions/variables in scope.
if [ -z "${SIDAR_RUN_TESTS_CONTEXT:-}" ]; then
  echo "❌ scripts/test_stages faz dosyaları doğrudan çalıştırılmaz; repo kökünden bash run_tests.sh kullanın."
  exit 2
fi

FRONTEND_PLAYWRIGHT_SENTINEL="${FRONTEND_PLAYWRIGHT_SENTINEL:-.playwright-installed}"
FRONTEND_PLAYWRIGHT_PACKAGE_LOCK="${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK:-package-lock.json}"

frontend_playwright_package_lock_fingerprint() {
  [[ -f "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}" ]] || return 1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}" | awk '{print $1}'
  else
    cksum "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}" | awk '{print $1 ":" $2}'
  fi
}

frontend_playwright_sentinel_cache_ready() {
  local executable_path=""
  local recorded_lock_fingerprint=""
  local current_lock_fingerprint=""
  [[ -f "${FRONTEND_PLAYWRIGHT_SENTINEL}" ]] || return 1
  {
    IFS= read -r executable_path || true
    IFS= read -r recorded_lock_fingerprint || true
  } < "${FRONTEND_PLAYWRIGHT_SENTINEL}"
  current_lock_fingerprint="$(frontend_playwright_package_lock_fingerprint || true)"
  if [[ -n "${executable_path}" \
    && -f "${executable_path}" \
    && -n "${recorded_lock_fingerprint}" \
    && "${recorded_lock_fingerprint}" == "${current_lock_fingerprint}" ]]; then
    return 0
  fi

  rm -f "${FRONTEND_PLAYWRIGHT_SENTINEL}"
  return 1
}

frontend_playwright_chromium_cache_ready() {
  local executable_path=""
  executable_path="$(node - <<'NODE_PLAYWRIGHT_CACHE_CHECK' 2>/dev/null
const fs = require("node:fs");
const { chromium } = require("@playwright/test");
const executablePath = chromium.executablePath();
if (!fs.existsSync(executablePath)) process.exit(1);
process.stdout.write(executablePath);
NODE_PLAYWRIGHT_CACHE_CHECK
)" || return 1
  local lock_fingerprint=""
  [[ -n "${executable_path}" && -f "${executable_path}" ]] || return 1
  lock_fingerprint="$(frontend_playwright_package_lock_fingerprint)" || return 1
  printf '%s\n%s\n' "${executable_path}" "${lock_fingerprint}" > "${FRONTEND_PLAYWRIGHT_SENTINEL}" || true
}

PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER="${PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER:-${SCRIPT_DIR:-$(pwd)}/scripts/install_modules/utils/playwright_ubuntu_override.sh}"
# shellcheck source=scripts/install_modules/utils/playwright_ubuntu_override.sh
source "${PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER}"

install_local_frontend_playwright_chromium_cache() {
  if [ "${RUN_FRONTEND_E2E_AUTO_INSTALL}" != "1" ]; then
    return 1
  fi
  if ! command -v npx >/dev/null 2>&1; then
    echo "⚠️ Node Playwright Chromium cache'i otomatik kurulamadı: npx bulunamadı."
    return 1
  fi

  echo "📦 Node Playwright Chromium cache'i bulunamadı; yerel frontend smoke testleri için otomatik kuruluyor..."
  (
    unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
    local os_release_path="${OS_RELEASE_PATH:-/etc/os-release}"
    local playwright_timeout_ms="${PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT:-120000}"
    if is_playwright_ubuntu_override_recommended "${os_release_path}"; then
      echo "ℹ️ Ubuntu 25+ algılandı; Node Playwright Chromium cache'i ubuntu24.04-x64 OS override ile hazırlanıyor."
      run_playwright_ubuntu_override_install "${os_release_path}" "${playwright_timeout_ms}" \
        npx --no-install playwright install chromium
    else
      npx --no-install playwright install chromium
    fi
  )
}

run_frontend_e2e_with_retry() {
  local e2e_exit_code=0

  echo "🎭 Frontend Playwright smoke testleri çalıştırılıyor..."
  if npm run test:e2e; then
    return 0
  else
    e2e_exit_code=$?
  fi

  if [ "${FRONTEND_E2E_RETRY_ON_FAIL}" != "1" ]; then
    return "${e2e_exit_code}"
  fi

  echo "⚠️ Frontend Playwright smoke testleri başarısız oldu (çıkış=${e2e_exit_code}); flake elemek için bir kez yeniden deneniyor..."
  if npm run test:e2e; then
    echo "✅ Frontend Playwright smoke testleri ikinci denemede geçti. İlk hata flake olarak raporlandı."
    return 0
  else
    e2e_exit_code=$?
  fi

  echo "❌ Frontend Playwright smoke testleri retry sonrasında da başarısız (çıkış=${e2e_exit_code})."
  return "${e2e_exit_code}"
}

resolve_local_frontend_e2e_mode() {
  if [ "${RUN_FRONTEND_E2E}" != "auto" ]; then
    return 0
  fi

  if frontend_playwright_sentinel_cache_ready; then
    RUN_FRONTEND_E2E=1
    echo "✅ Node Playwright Chromium sentinel cache'i hazır; yerel frontend smoke testleri otomatik etkinleştirildi."
    return 0
  fi

  if frontend_playwright_chromium_cache_ready; then
    RUN_FRONTEND_E2E=1
    echo "✅ Node Playwright Chromium cache'i hazır; sentinel güncellendi ve yerel frontend smoke testleri otomatik etkinleştirildi."
    return 0
  fi

  if install_local_frontend_playwright_chromium_cache && frontend_playwright_chromium_cache_ready; then
    RUN_FRONTEND_E2E=1
    echo "✅ Node Playwright Chromium cache'i otomatik kuruldu; yerel frontend smoke testleri etkinleştirildi."
    return 0
  fi

  RUN_FRONTEND_E2E=0
  echo "⚠️ Frontend Playwright smoke testleri atlandı: Node Playwright Chromium cache'i hazırlanamadı (RUN_FRONTEND_E2E=auto)."
  if [ "${RUN_FRONTEND_E2E_AUTO_INSTALL}" != "1" ]; then
    echo "   Otomatik cache kurulumu RUN_FRONTEND_E2E_AUTO_INSTALL=${RUN_FRONTEND_E2E_AUTO_INSTALL} ile kapalı."
  fi
  echo "   Manuel kurulum için: cd web_ui_react && npx playwright install chromium"
  echo "   Ardından: RUN_FRONTEND_E2E=1 bash run_tests.sh"
}


# 6) Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
if [ -d "web_ui_react" ] && [ -f "web_ui_react/package.json" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    FRONTEND_EXIT_CODE=1
  else
    echo "🚀 Frontend (React) Testleri Başlıyor..."
    if pushd web_ui_react > /dev/null; then
      # Yerel ortamda yavaşlığı önlemek için CI değişkenine göre davran.
      if [ "${CI:-0}" = "true" ] || [ "${CI:-0}" = "1" ]; then
        echo "ℹ️ CI ortamı tespit edildi, 'npm ci' çalıştırılıyor..."
        npm ci
      else
        echo "ℹ️ Yerel ortam tespit edildi, 'npm install' çalıştırılıyor..."
        npm install
      fi
      local_npm_ci_exit=$?
      if [ "${local_npm_ci_exit}" -ne 0 ]; then
        FRONTEND_EXIT_CODE=${local_npm_ci_exit}
      else
        resolve_local_frontend_e2e_mode
        npm run test:coverage
        FRONTEND_EXIT_CODE=$?
        if [ "${FRONTEND_EXIT_CODE}" -eq 0 ]; then
          if [ "${RUN_FRONTEND_E2E}" = "1" ]; then
            run_frontend_e2e_with_retry
            FRONTEND_E2E_EXIT_CODE=$?
          else
            echo "ℹ️ Frontend Playwright smoke testleri atlandı (RUN_FRONTEND_E2E=${RUN_FRONTEND_E2E})."
          fi
        fi
      fi

      if [ -f "coverage/base.css" ]; then
        echo "Frontend test raporuna kalıcı karanlık tema (dark mode) uygulanıyor..."
        if ! apply_dark_mode_to_frontend_coverage_report "$PWD/coverage"; then
          echo "❌ Frontend coverage dark mode link doğrulaması başarısız oldu."
          FRONTEND_EXIT_CODE=1
        fi
      fi

      # coverage/lcov-report/index.html CI araçları (ör. SonarQube) için korunur,
      # ancak tarayıcıda mükerrer rapor açılmasını önlemek için sadece ana HTML raporu açılır.
      open_artifact "$PWD/coverage/index.html"

      popd > /dev/null || true
    else
      FRONTEND_EXIT_CODE=1
    fi
  fi
elif [ -d "web_ui_react" ]; then
  echo "⚠️ Frontend testleri atlandı: web_ui_react/package.json bulunamadı."
fi

echo "======================================================"

