#!/usr/bin/env bash
set -Eeuo pipefail

# ── 6. Playwright tarayıcı motorları ─────────────────────────────────────────
should_install_playwright_browsers() {
    case "$PLAYWRIGHT_BROWSERS_MODE" in
        always) return 0 ;;
        never) return 1 ;;
    esac

    local env_file="$SCRIPT_DIR/.env"
    local sidar_env="development"
    if [[ -f "$env_file" ]]; then
        sidar_env="$(read_env_value_from_file "SIDAR_ENV" "$env_file")"
    fi
    sidar_env=$(echo "${sidar_env:-development}" | tr '[:upper:]' '[:lower:]' | tr -d '"'\''[:space:]')

    case "$sidar_env" in
        development|dev|local|test) return 0 ;;
        *) return 1 ;;
    esac
}

install_playwright_browsers() {
    step "Playwright Tarayıcı Motorları"

    if ! should_install_playwright_browsers; then
        info "Playwright tarayıcı kurulumu atlandı (mode=${PLAYWRIGHT_BROWSERS_MODE}, SIDAR_ENV tabanlı otomatik politika)."
        return
    fi

    PY_CMD=(python)

    if "${PY_CMD[@]}" -c "import playwright" >/dev/null 2>&1; then
        local pw_timeout_ms="${PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT:-120000}"
        local _pw_install_log; _pw_install_log=$(mktemp)
        local _pw_os_release_path="${OS_RELEASE_PATH:-/etc/os-release}"
        local _pw_install_completed=false
        local _pw_python_spec
        local _pw_apt_noise_regex='is already the newest version|0 upgraded.*0 newly.*not upgraded|Reading package|Building dependency|Reading state|Solving dependencies|^$'
        local _pw_browser_noise_regex="BEWARE: your OS is not officially supported|Cannot install dependencies for ubuntu[0-9]+\.04-x64|${_pw_apt_noise_regex}"
        local _pw_ubuntu_version=""
        if [[ -r "$_pw_os_release_path" ]]; then
            _pw_ubuntu_version="$(awk -F= '/^VERSION_ID=/{gsub(/"/, "", $2); print $2; exit}' "$_pw_os_release_path")"
        fi
        _pw_python_spec="$(resolve_playwright_python_spec "${SCRIPT_DIR}/pyproject.toml")"

        _try_playwright_install() {
            local _mode="${1:-binary}"
            if [[ "$_mode" == "with-deps" ]]; then
                env PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="$pw_timeout_ms" \
                    "${PY_CMD[@]}" -m playwright install --with-deps chromium >"$_pw_install_log" 2>&1
            else
                env PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="$pw_timeout_ms" \
                    "${PY_CMD[@]}" -m playwright install chromium >"$_pw_install_log" 2>&1
            fi
        }

        _try_playwright_ubuntu_override_install() {
            run_playwright_ubuntu_override_install "$_pw_os_release_path" "$pw_timeout_ms" \
                "${PY_CMD[@]}" -m playwright install chromium >"$_pw_install_log" 2>&1
        }

        _try_playwright_install_deps() {
            "${PY_CMD[@]}" -m playwright install-deps chromium >"$_pw_install_log" 2>&1
        }

        _ensure_playwright_override_dependencies() {
            info "Playwright OS override sonrası Chromium sistem bağımlılıkları doğrulanıyor..."
            if playwright_linux_dependencies_ready; then
                ok "Playwright Chromium sistem bağımlılıkları apt ön taramasında hazır görünüyor."
                return 0
            fi
            if is_playwright_ubuntu_override_recommended "$_pw_os_release_path"; then
                local _pw_missing_deps=""
                _pw_missing_deps="$(playwright_missing_ubuntu_dependencies | paste -sd ' ' - 2>/dev/null || true)"
                warn "Playwright Ubuntu ${_pw_ubuntu_version:-25+} apt ön taraması eksik Chromium bağımlılıkları buldu: ${_pw_missing_deps:-bilinmiyor}. Sabit Sidar dependency listesi install-deps uyarıları basılmadan önce deneniyor..."
                if install_playwright_linux_dependencies_fallback; then
                    ok "Playwright Chromium sistem bağımlılıkları apt ön tarama fallback ile kuruldu."
                    return 0
                fi
                warn "Playwright apt ön tarama fallback bağımlılıkları tamamlayamadı; Playwright install-deps doğrulaması denenecek."
            fi
            if _try_playwright_install_deps; then
                grep -vE "$_pw_browser_noise_regex" \
                    "$_pw_install_log" || true
                if playwright_linux_dependencies_ready; then
                    ok "Playwright Chromium sistem bağımlılıkları install-deps ile doğrulandı."
                    return 0
                fi
                warn "Playwright install-deps başarılı döndü ancak kritik Chromium bağımlılıkları doğrulanamadı; sabit apt fallback uygulanacak."
            fi

            grep -vE "$_pw_browser_noise_regex" "$_pw_install_log" >&2 || true
            if ! is_playwright_ubuntu_override_recommended "$_pw_os_release_path"; then
                warn "Playwright install-deps başarısız oldu; sabit apt fallback yalnızca Ubuntu 25+ override hostlarında uygulanır."
                return 1
            fi

            warn "Playwright install-deps başarısız oldu; Ubuntu ${_pw_ubuntu_version:-25+} için sabit Chromium apt bağımlılık listesi deneniyor..."
            if install_playwright_linux_dependencies_fallback; then
                ok "Playwright Chromium sistem bağımlılıkları sabit apt fallback ile kuruldu."
                return 0
            fi

            warn "Playwright Chromium sistem bağımlılıkları kurulamadı; browser binary mevcut olsa da headless çalışma doğrulanmadı."
            return 1
        }

        _playwright_python_upgrade_required() {
            "${PY_CMD[@]}" - "$_pw_python_spec" <<'PY_PLAYWRIGHT_VERSION' >/dev/null 2>&1
from importlib.metadata import PackageNotFoundError, version
import sys

from packaging.specifiers import SpecifierSet

try:
    installed_version = version("playwright")
except PackageNotFoundError:
    raise SystemExit(0)
raise SystemExit(0 if installed_version not in SpecifierSet(sys.argv[1].removeprefix("playwright")) else 1)
PY_PLAYWRIGHT_VERSION
        }

        _try_playwright_last_resort_override() {
            if _try_playwright_ubuntu_override_install; then
                grep -vE "$_pw_browser_noise_regex" \
                    "$_pw_install_log" || true
                if _ensure_playwright_override_dependencies; then
                    ok "Playwright kurulumu OS override fallback ile tamamlandı (chromium + deps)."
                else
                    warn "Playwright OS override fallback binary indirmesi tamamlandı ancak sistem bağımlılıkları eksik kaldı."
                fi
            else
                cat "$_pw_install_log" >&2
                warn "Playwright kurulumu tüm fallback seviyelerinde başarısız oldu. Önce: uv add --dev \"${_pw_python_spec}\" sonra: uv run python -m playwright install chromium"
            fi
        }

        if is_playwright_ubuntu_override_recommended "$_pw_os_release_path" &&
            ! playwright_host_platform_is_officially_supported "$_pw_os_release_path" "${PY_CMD[@]}"; then
            info "Ubuntu ${_pw_ubuntu_version:-25+} yüklü Playwright resmi destek matrisinin dışında; en yakın desteklenen Ubuntu OS override kurulumu doğrudan deneniyor..."
            if _try_playwright_ubuntu_override_install; then
                grep -vE "$_pw_browser_noise_regex" \
                    "$_pw_install_log" || true
                if _ensure_playwright_override_dependencies; then
                    ok "Playwright kurulumu proaktif OS override ile tamamlandı (chromium + deps)."
                    _pw_install_completed=true
                else
                    warn "Playwright proaktif OS override binary indirmesi tamamlandı ancak sistem bağımlılıkları eksik kaldı. Standart fallback zinciri deneniyor..."
                fi
            else
                cat "$_pw_install_log" >&2
                warn "Playwright proaktif OS override kurulumu başarısız oldu. Standart fallback zinciri deneniyor..."
            fi
        fi

        if [[ "$_pw_install_completed" != true ]]; then
            info "Playwright headless optimizasyonu: yalnızca Chromium (--with-deps) kuruluyor (timeout=${pw_timeout_ms}ms)..."
            if _try_playwright_install with-deps; then
                grep -vE "$_pw_apt_noise_regex" \
                    "$_pw_install_log" || true
                ok "Playwright kurulumu tamamlandı (chromium, --with-deps)."
            else
                cat "$_pw_install_log" >&2
                warn "Playwright --with-deps komutu başarısız oldu. Çıktı metninden bağımsız fallback: yalnızca Chromium binary kurulumu deneniyor..."
                if _try_playwright_install binary; then
                    grep -vE "$_pw_apt_noise_regex" \
                        "$_pw_install_log" || true
                    ok "Playwright kurulumu fallback ile tamamlandı (chromium, deps yok)."
                else
                    cat "$_pw_install_log" >&2
                    if _playwright_python_upgrade_required; then
                        warn "Playwright binary fallback başarısız ve kurulu paket ${_pw_python_spec} şartını sağlamıyor. Upgrade fallback deneniyor..."
                        if uv add --dev "$_pw_python_spec"; then
                            if _try_playwright_install binary; then
                                grep -vE "$_pw_apt_noise_regex" \
                                    "$_pw_install_log" || true
                                ok "Playwright kurulumu upgrade fallback ile tamamlandı (chromium, deps yok)."
                            elif is_playwright_ubuntu_override_recommended "$_pw_os_release_path"; then
                                cat "$_pw_install_log" >&2
                                warn "Playwright upgrade fallback sonrası kurulum yine başarısız. Ubuntu override fallback deneniyor..."
                                _try_playwright_last_resort_override
                            else
                                cat "$_pw_install_log" >&2
                                warn "Playwright upgrade fallback sonrası kurulum yine başarısız. Manuel deneyin: uv run python -m playwright install chromium"
                            fi
                        else
                            warn "Playwright upgrade fallback (uv add --dev \"${_pw_python_spec}\") başarısız oldu. Sonra manuel kurulum deneyin: uv run python -m playwright install chromium"
                        fi
                    else
                        info "Kurulu Playwright paketi ${_pw_python_spec} şartını zaten sağlıyor; gereksiz uv add upgrade fallback atlanıyor. Son çare OS override fallback deneniyor..."
                        _try_playwright_last_resort_override
                    fi
                fi
            fi
        fi

        rm -f "$_pw_install_log"
    else
        info "playwright paketi bu profilde kurulmadı — tarayıcı motor kurulumu atlandı."
    fi
}
