#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2034  # Helpers update run_tests.sh globals after being sourced.
# Helper functions sourced by run_tests.sh; do not execute directly.

print_frontend_quality_summary() {
  echo ""
  echo "🧭 Frontend kalite kapısı özeti"
  echo "   Lint (npm run lint): $(format_quality_status "${FRONTEND_LINT_EXIT_CODE}" "${FRONTEND_LINT_RAN}")"
  echo "   Typecheck (npm run typecheck): $(format_quality_status "${FRONTEND_TYPECHECK_EXIT_CODE}" "${FRONTEND_TYPECHECK_RAN}")"
  echo "   Coverage (npm run test:coverage): $(format_quality_status "${FRONTEND_COVERAGE_EXIT_CODE}" "${FRONTEND_COVERAGE_RAN}")"
  echo "   Bundle budget (npm run build:budget): $(format_quality_status "${FRONTEND_BUNDLE_BUDGET_EXIT_CODE}" "${FRONTEND_BUNDLE_BUDGET_RAN}" "atlanmış") (FRONTEND_BUNDLE_BUDGET=${FRONTEND_BUNDLE_BUDGET})"
  echo "   Dependency audit (npm run audit:high): $(format_quality_status "${FRONTEND_NPM_AUDIT_EXIT_CODE}" "${FRONTEND_NPM_AUDIT_RAN}")"
  echo "   Playwright (${FRONTEND_E2E_NPM_SCRIPT}): $(format_quality_status "${FRONTEND_E2E_EXIT_CODE}" "${FRONTEND_E2E_RAN}" "atlanmış") (enforce=${FRONTEND_E2E_ENFORCE_RESULT})"
  if [ "${TEST_PROFILE:-local}" = "local" ] && stage_all_selected && [ "${FRONTEND_BUNDLE_BUDGET}" != "1" ]; then
    echo "   ⚠️ Local full bundle budget kapısı kapalı. CI paritesi için: FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=1 bash run_tests.sh --stage all"
  fi
  if [ -f "${FRONTEND_COVERAGE_REPORT_PATH}" ]; then
    echo "   Frontend coverage artefaktı: ${FRONTEND_COVERAGE_REPORT_PATH}"
  else
    echo "   Frontend coverage artefaktı: üretilmedi (${FRONTEND_COVERAGE_REPORT_PATH})"
  fi
  if [ -f "${FRONTEND_PLAYWRIGHT_REPORT_PATH}" ]; then
    echo "   Playwright artefaktı: ${FRONTEND_PLAYWRIGHT_REPORT_PATH}"
  fi
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      echo "### Frontend quality gate"
      echo ""
      echo "| Gate | Command | Result |"
      echo "| --- | --- | --- |"
      echo "| Lint | \`npm run lint\` | $(format_quality_status "${FRONTEND_LINT_EXIT_CODE}" "${FRONTEND_LINT_RAN}" "skipped") |"
      echo "| Typecheck | \`npm run typecheck\` | $(format_quality_status "${FRONTEND_TYPECHECK_EXIT_CODE}" "${FRONTEND_TYPECHECK_RAN}" "skipped") |"
      echo "| Coverage | \`npm run test:coverage\` | $(format_quality_status "${FRONTEND_COVERAGE_EXIT_CODE}" "${FRONTEND_COVERAGE_RAN}" "skipped") |"
      echo "| Bundle budget | \`npm run build:budget\` | $(format_quality_status "${FRONTEND_BUNDLE_BUDGET_EXIT_CODE}" "${FRONTEND_BUNDLE_BUDGET_RAN}" "skipped") |"
      echo "| Dependency audit | \`npm run audit:high\` | $(format_quality_status "${FRONTEND_NPM_AUDIT_EXIT_CODE}" "${FRONTEND_NPM_AUDIT_RAN}" "skipped") |"
      echo "| Playwright smoke | \`npm run ${FRONTEND_E2E_NPM_SCRIPT}\` | $(format_quality_status "${FRONTEND_E2E_EXIT_CODE}" "${FRONTEND_E2E_RAN}" "skipped") |"
      echo ""
      echo "- Coverage artifact: \`${FRONTEND_COVERAGE_REPORT_PATH}\`"
      echo "- Playwright artifact: \`${FRONTEND_PLAYWRIGHT_REPORT_PATH}\`"
    } >> "${GITHUB_STEP_SUMMARY}"
  fi
}

apply_dark_mode_to_frontend_coverage_report() {
  local coverage_dir="$1"
  local dark_css="${coverage_dir}/sidar_dark_mode.css"

  if [ ! -d "${coverage_dir}" ]; then
    return 0
  fi

  cat > "${dark_css}" <<'CSS_DARK'
:root {
  color-scheme: dark;
}

html, body {
  background-color: #0f1117 !important;
  color: #e6edf3 !important;
}

a {
  color: #58a6ff !important;
}

.coverage-summary,
table.coverage-summary td,
table.coverage-summary th,
.wrapper,
.pad1,
.footer {
  background: #0f1117 !important;
  color: #e6edf3 !important;
}

.coverage-summary tbody tr:hover {
  background: #1c2230 !important;
}

.fl,
.cline-any,
.cstat-no,
.cbranch-no,
.cstat-yes,
.cbranch-yes {
  color: #e6edf3 !important;
}
CSS_DARK

  if ! uv run python - "${coverage_dir}" "${dark_css}" <<'PY'
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

coverage_dir = Path(sys.argv[1]).resolve()
dark_css = Path(sys.argv[2]).resolve()
index_files = sorted(coverage_dir.rglob("index.html"))
missing: list[str] = []
link_pattern = re.compile(
    r'(<link\b[^>]*\bhref=["\'][^"\']*base\.css["\'][^>]*>)',
    re.IGNORECASE,
)

for html_path in index_files:
    content = html_path.read_text(encoding="utf-8")
    if "sidar_dark_mode.css" not in content:
        href = os.path.relpath(dark_css, html_path.parent).replace(os.sep, "/")
        dark_link = f'<link rel="stylesheet" href="{href}" />'
        if link_pattern.search(content):
            content = link_pattern.sub(r"\1\n" + dark_link, content, count=1)
        elif "</head>" in content.lower():
            content = re.sub(r"</head>", dark_link + "\n</head>", content, count=1, flags=re.IGNORECASE)
        else:
            content = dark_link + "\n" + content
        html_path.write_text(content, encoding="utf-8")

    if "sidar_dark_mode.css" not in html_path.read_text(encoding="utf-8"):
        missing.append(str(html_path.relative_to(coverage_dir)))

if missing:
    print(
        "Dark mode coverage CSS link could not be injected into: " + ", ".join(missing),
        file=sys.stderr,
    )
    sys.exit(1)
PY
  then
    return 1
  fi
}

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

install_local_frontend_playwright_chromium_cache() {
  if [ "${RUN_FRONTEND_E2E_AUTO_INSTALL}" != "1" ]; then
    return 1
  fi
  if ! command -v npx >/dev/null 2>&1; then
    echo "⚠️ Node Playwright Chromium cache'i otomatik kurulamadı: npx bulunamadı."
    return 1
  fi

  echo "📦 Node Playwright Chromium cache'i bulunamadı; yerel frontend smoke testleri için otomatik kuruluyor..."
  local playwright_install_log
  playwright_install_log="$(mktemp)"
  (
    unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
    local os_release_path="${OS_RELEASE_PATH:-/etc/os-release}"
    local playwright_timeout_ms="${PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT:-120000}"
    if is_playwright_ubuntu_override_recommended "${os_release_path}"; then
      echo "ℹ️ Ubuntu 25+ algılandı; Node Playwright Chromium cache'i en yakın desteklenen Ubuntu OS override ile hazırlanıyor."
      # npx burada yalnızca gerçek browser install komutu olarak geçirilir;
      # Ubuntu bundle probe'u helper içinde sadece Python interpreter komutlarıyla yapılır.
      run_playwright_ubuntu_override_install "${os_release_path}" "${playwright_timeout_ms}" \
        npx --no-install playwright install chromium
    else
      npx --no-install playwright install chromium
    fi
  ) 2>&1 | tee "${playwright_install_log}"
  local install_exit_code=${PIPESTATUS[0]}
  if [ "${install_exit_code}" -ne 0 ]; then
    if grep -Eqi "Domain forbidden|server returned code 403|Download failed" "${playwright_install_log}"; then
      echo "❌ Playwright Chromium indirilemedi; CDN/proxy/firewall 403 engeli algılandı."
      echo "   Manuel yerel hazırlık: cd web_ui_react && npx playwright install chromium"
      echo "   Kurumsal ağda cache/artifact restore edin: ~/.cache/ms-playwright dizinini önceden hazırlayın veya CI cache'ini kullanın."
      echo "   Ardından release kapısı: make production-readiness"
    fi
    rm -f "${playwright_install_log}"
    return "${install_exit_code}"
  fi
  rm -f "${playwright_install_log}"
}

run_frontend_e2e_with_retry() {
  local e2e_exit_code=0
  local frontend_e2e_script="${FRONTEND_E2E_NPM_SCRIPT:-test:e2e:smoke}"

  echo "🎭 Frontend Playwright smoke testleri çalıştırılıyor (${frontend_e2e_script})..."
  if npm run "${frontend_e2e_script}"; then
    return 0
  else
    e2e_exit_code=$?
  fi

  if [ "${FRONTEND_E2E_RETRY_ON_FAIL}" != "1" ]; then
    return "${e2e_exit_code}"
  fi

  echo "⚠️ Frontend Playwright smoke testleri başarısız oldu (çıkış=${e2e_exit_code}); flake elemek için bir kez yeniden deneniyor..."
  if npm run "${frontend_e2e_script}"; then
    echo "✅ Frontend Playwright smoke testleri ikinci denemede geçti. İlk hata flake olarak raporlandı."
    return 0
  else
    e2e_exit_code=$?
  fi

  echo "❌ Frontend Playwright smoke testleri retry sonrasında da başarısız (çıkış=${e2e_exit_code})."
  echo "ℹ️ Aynı smoke testi ikinci denemede de kaldığı için sonuç flake yerine deterministik kabul edilir."
  echo "   Chat WebSocket smoke için öncelikli kontroller: Vite /ws proxy upgrade, mock backend subprotocol negotiation ve StatusBar data-state."
  return "${e2e_exit_code}"
}

resolve_local_frontend_e2e_mode() {
  local requested_frontend_e2e="${RUN_FRONTEND_E2E}"

  if [ "${requested_frontend_e2e}" != "auto" ] && [ "${requested_frontend_e2e}" != "1" ]; then
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

  if [ "${requested_frontend_e2e}" = "1" ]; then
    echo "❌ Frontend Playwright smoke testleri zorunlu ancak Node Playwright Chromium cache'i hazırlanamadı (RUN_FRONTEND_E2E=1)."
    if [ "${RUN_FRONTEND_E2E_AUTO_INSTALL}" != "1" ]; then
      echo "   Otomatik cache kurulumu RUN_FRONTEND_E2E_AUTO_INSTALL=${RUN_FRONTEND_E2E_AUTO_INSTALL} ile kapalı."
    fi
    echo "   Manuel kurulum için: cd web_ui_react && npx playwright install chromium"
    return 1
  fi

  RUN_FRONTEND_E2E=0
  echo "⚠️ Frontend Playwright smoke testleri atlandı: Node Playwright Chromium cache'i hazırlanamadı (RUN_FRONTEND_E2E=auto)."
  if [ "${RUN_FRONTEND_E2E_AUTO_INSTALL}" != "1" ]; then
    echo "   Otomatik cache kurulumu RUN_FRONTEND_E2E_AUTO_INSTALL=${RUN_FRONTEND_E2E_AUTO_INSTALL} ile kapalı."
  fi
  echo "   Manuel kurulum için: cd web_ui_react && npx playwright install chromium"
  echo "   Ardından: RUN_FRONTEND_E2E=1 bash run_tests.sh"
}
