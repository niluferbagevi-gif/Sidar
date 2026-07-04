#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_INSTALL_REMEDIATION_SH_LOADED=1

# Lightweight installer auto-heal / resume controller.
# The goal is intentionally narrow and deterministic: remediate known transient
# installer breakages (uv lock/sync, stale venv/cache, transient network phase
# retry) and then re-exec the installer from the failed phase instead of asking
# the operator to restart from scratch.

sidar_install_auto_heal_enabled() {
    local suppress_raw="${SIDAR_INSTALL_SUPPRESS_AUTO_HEAL:-0}"
    suppress_raw="$(echo "$suppress_raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    case "$suppress_raw" in
        1|true|yes|y|evet|e|on|enable|enabled) return 1 ;;
    esac

    local raw="${SIDAR_INSTALL_AUTO_HEAL:-1}"
    raw="$(echo "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    case "$raw" in
        0|false|no|n|hayir|hayır|h|off|disable|disabled) return 1 ;;
        *) return 0 ;;
    esac
}

wsl_integration_remediation_message() {
    local distro="${1:-${WSL_DISTRO_NAME:-Ubuntu}}"
    cat <<EOF
Docker Desktop WSL Integration için '${distro}' dağıtımında otomatik düzeltme denendi ancak başarısız oldu. Lütfen Docker Desktop > Settings > Resources > WSL Integration bölümünde '${distro}' için explicit toggle'ı açıp Apply & restart yapın. Not: "Enable integration with my default WSL distro" açık olsa bile yalnızca default distro'yu kapsar; default distro değiştiğinde explicit toggle kapalıysa Docker socket mount'u bozulabilir.
EOF
}

sidar_phase_index() {
    case "$1" in
        01_context) echo 10 ;;
        02_repo) echo 20 ;;
        03_runtime) echo 30 ;;
        04_workspace) echo 40 ;;
        05_frontend) echo 50 ;;
        06_models) echo 60 ;;
        06_services) echo 70 ;;
        07_finish) echo 80 ;;
        *) echo 999 ;;
    esac
}

sidar_phase_is_informational() {
    local phase="$1"
    case "$phase" in
        01_context) return 0 ;;
        *) return 1 ;;
    esac
}

sidar_is_non_retryable_failure_code() {
    local exit_code="${1:-0}"
    case "$exit_code" in
        -9|2|124|127) return 0 ;;
        *) return 1 ;;
    esac
}

sidar_is_deterministic_failure_signal() {
    local failed_cmd="${1:-}"
    local reason="${2:-}"
    local signal="${failed_cmd} ${reason}"
    local normalized=""
    normalized="$(printf '%s' "$signal" | tr '[:upper:]' '[:lower:]')"
    # Eksik checksum / supply-chain doğrulama hataları deterministiktir:
    # ortam değişkeni sağlanmadan retry aynı duvara çarpar.
    case "$normalized" in
        *"checksum değeri tanımlı değil"*|*"_install_sha256"*|*"allow_unverified_remote_scripts"*|*"supply-chain"*|*"checksum doğrulaması başarısız"*)
            return 0
            ;;
        *"installer smoke gate başarısız"*|*"install_sidar_version"*"eşleşmiyor"*)
            return 0
            ;;
    esac
    case "$normalized" in
        *"sudo: timed out"*|*"ollama_install"*)
            return 1
            ;;
        *"assert"*|*"smoke test failed"*|*"pytest"*|*"unit test"*|*"test failed"*|*"deterministic"*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

sidar_failure_signature() {
    local phase="${1:-}"
    local failed_cmd="${2:-}"
    local reason="${3:-}"
    local exit_code="${4:-}"
    local normalized=""
    normalized="$(printf '%s' "${phase}|${exit_code}|${failed_cmd}|${reason}" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's#/tmp/[^[:space:]]+#/tmp/<tmp>#g; s#[0-9]{4}-[0-9]{2}-[0-9]{2}t[0-9:]+z#<timestamp>#g; s#[0-9]+(\.[0-9]+)?s#<duration>#g; s#[[:space:]]+# #g')"
    if command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$normalized" | sha256sum | awk '{print $1}'
        return 0
    fi
    if command -v shasum >/dev/null 2>&1; then
        printf '%s' "$normalized" | shasum -a 256 | awk '{print $1}'
        return 0
    fi
    printf '%s' "$normalized" | cksum | awk '{print $1}'
}

sidar_is_non_retryable_failure_signal() {
    local failed_cmd="${1:-}"
    local reason="${2:-}"
    local signal="${failed_cmd} ${reason}"
    local normalized=""
    normalized="$(printf '%s' "$signal" | tr '[:upper:]' '[:lower:]')"
    case "$normalized" in
        *"environmentfilenotfound"*|*"environment.yml"*|*"is_alembic_at_head failed"*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

sidar_non_retryable_failure_guidance() {
    local failed_cmd="${1:-}"
    local reason="${2:-}"
    local signal="${failed_cmd} ${reason}"
    local normalized=""
    normalized="$(printf '%s' "$signal" | tr '[:upper:]' '[:lower:]')"
    case "$normalized" in
        *"environmentfilenotfound"*|*"environment.yml"*)
            cat <<'EOF'
Bu imza eski conda tabanlı kurulumdan kalma olabilir. Güncel Sidar installer akışı uv kullanır; ~/Sidar veya PATH üzerinde stale install_sidar.sh kopyası olup olmadığını kontrol edin ve kurulumu repo kökündeki ./install_sidar.sh ile yeniden başlatın.
EOF
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

sidar_is_installer_smoke_gate_failure() {
    local failed_cmd="${1:-}"
    local reason="${2:-}"
    local signal="${failed_cmd} ${reason}"
    local normalized=""
    normalized="$(printf '%s' "$signal" | tr '[:upper:]' '[:lower:]')"
    case "$normalized" in
        *"installer smoke gate başarısız"*|*"install_sidar_version"*"eşleşmiyor"*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

sidar_is_remote_script_checksum_missing() {
    local failed_cmd="${1:-}"
    local reason="${2:-}"
    local signal="${failed_cmd} ${reason}"
    local normalized=""
    normalized="$(printf '%s' "$signal" | tr '[:upper:]' '[:lower:]')"
    case "$normalized" in
        *"checksum değeri tanımlı değil"*|*"_install_sha256"*|*"supply-chain doğrulamasını korumak"*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

sidar_detect_missing_checksum_var() {
    local failed_cmd="${1:-}"
    local reason="${2:-}"
    local signal="${failed_cmd} ${reason}"
    case "$signal" in
        *"OLLAMA_INSTALL_SHA256"*|*"ollama_install checksum"*|*"ollama_install"*"checksum"*)
            echo "OLLAMA_INSTALL_SHA256"
            return 0
            ;;
        *"UV_INSTALL_SHA256"*|*"uv_install checksum"*|*"uv_install"*"checksum"*)
            echo "UV_INSTALL_SHA256"
            return 0
            ;;
    esac
    echo ""
    return 1
}

sidar_retry_budget_for_failure() {
    local phase="${1:-}"
    local failed_cmd="${2:-}"
    local reason="${3:-}"
    local default_budget="${SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS:-1}"
    [[ "$default_budget" =~ ^[0-9]+$ ]] || default_budget=1

    if sidar_is_deterministic_failure_signal "$failed_cmd" "$reason"; then
        echo "${SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS_DETERMINISTIC:-1}"
        return 0
    fi

    case "$phase" in
        02_repo|03_runtime|05_frontend|06_models|06_services)
            echo "${SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS_TRANSIENT:-3}"
            ;;
        *)
            echo "$default_budget"
            ;;
    esac
}

sidar_should_skip_phase_for_resume() {
    local phase="$1"
    local resume_from="${SIDAR_INSTALL_RESUME_FROM_PHASE:-}"
    [[ -n "$resume_from" ]] || return 1

    local phase_idx=""
    local resume_idx=""
    phase_idx="$(sidar_phase_index "$phase")"
    resume_idx="$(sidar_phase_index "$resume_from")"
    [[ "$phase_idx" =~ ^[0-9]+$ && "$resume_idx" =~ ^[0-9]+$ ]] || return 1
    (( phase_idx < resume_idx ))
}

sidar_run_install_phase() {
    local phase="$1"
    local fn="$2"
    shift 2 || true

    if sidar_should_skip_phase_for_resume "$phase"; then
        info "Resume modu: ${phase} fazı atlanıyor (hedef: ${SIDAR_INSTALL_RESUME_FROM_PHASE})."
        return 0
    fi

    export SIDAR_CURRENT_INSTALL_PHASE="$phase"
    export SIDAR_CURRENT_INSTALL_PHASE_FUNCTION="$fn"
    "$fn" "$@"
    local rc=$?
    unset SIDAR_CURRENT_INSTALL_PHASE
    unset SIDAR_CURRENT_INSTALL_PHASE_FUNCTION
    return "$rc"
}

sidar_remediation_log_dir() {
    local dir="${SCRIPT_DIR}/artifacts/install/remediation"
    mkdir -p "$dir"
    echo "$dir"
}

sidar_write_remediation_report() {
    local phase="$1"
    local reason="$2"
    local action="$3"
    local dir=""
    local report=""
    dir="$(sidar_remediation_log_dir)"
    report="${dir}/$(date +%Y%m%d_%H%M%S)_${phase}.log"
    {
        echo "phase=${phase}"
        echo "reason=${reason}"
        echo "action=${action}"
        echo "attempt=${SIDAR_INSTALL_REMEDIATION_ATTEMPT:-0}"
        echo "resume_from=${phase}"
        echo "log_file=${LOG_FILE:-}"
        if [[ -n "${LOG_FILE:-}" && -f "$LOG_FILE" ]]; then
            echo "--- recent installer log ---"
            tail -n 120 "$LOG_FILE" || true
        fi
    } > "$report"
    info "Auto-heal raporu yazıldı: $report"
}

sidar_fix_pep639_legacy_license_classifier() {
    local pyproject_file="$SCRIPT_DIR/pyproject.toml"
    local match_pattern='License classifiers have been superseded'
    local legacy_classifier='License :: OSI Approved :: MIT License'
    local signal_text="${1:-}"
    local action_ref="${2:-}"

    [[ -f "$pyproject_file" ]] || return 1

    if [[ -z "$signal_text" && -n "${LOG_FILE:-}" && -f "$LOG_FILE" ]]; then
        signal_text="$(tail -n 400 "$LOG_FILE" 2>/dev/null || true)"
    fi

    if [[ "$signal_text" != *"$match_pattern"* ]]; then
        return 1
    fi

    if ! grep -Fq "$legacy_classifier" "$pyproject_file"; then
        info "Auto-heal: PEP 639 deseni algılandı; legacy license classifier zaten kaldırılmış."
        return 0
    fi

    cp "$pyproject_file" "artifacts/install/remediation/pyproject.toml.$(date +%Y%m%d_%H%M%S).bak"
    sed_inplace "/${legacy_classifier//\//\\/}/d" "$pyproject_file"
    warn "Auto-heal: PEP 639 uyumsuzluğu algılandı; legacy license classifier pyproject.toml dosyasından kaldırıldı."
    if [[ -n "$action_ref" ]]; then
        printf -v "$action_ref" '%s+pep639-license-classifier-removed' "${!action_ref}"
    fi
    return 0
}

sidar_remediate_uv_sync_failure() {
    local failure_signal="${1:-}"
    local action="uv-sync-remediation"
    cd "$SCRIPT_DIR" || return 1

    if ! command -v uv &>/dev/null; then
        warn "Auto-heal: uv bulunamadı; uv lock/sync remediation uygulanamadı."
        return 1
    fi

    mkdir -p artifacts/install/remediation

    sidar_fix_pep639_legacy_license_classifier "$failure_signal" action || true

    if [[ -d .venv && ! -f .venv/pyvenv.cfg ]]; then
        warn "Auto-heal: bozuk .venv tespit edildi; yedeklenip yeniden oluşturulacak."
        local venv_backup=""
        venv_backup="artifacts/install/remediation/venv_broken_$(date +%Y%m%d_%H%M%S)"
        mv .venv "$venv_backup"
        action="${action}+venv-backup"
    fi

    if [[ -f uv.lock ]]; then
        if ! uv lock --check >/tmp/sidar_uv_lock_check.log 2>&1; then
            warn "Auto-heal: uv.lock pyproject ile uyumsuz/bozuk görünüyor; yedeklenip uv lock ile yeniden üretilecek."
            cp uv.lock "artifacts/install/remediation/uv.lock.$(date +%Y%m%d_%H%M%S).bak"
            if ! uv lock; then
                warn "Auto-heal: uv lock yeniden üretimi başarısız oldu."
                return 1
            fi
            action="${action}+uv-lock-regenerated"
        fi
    else
        warn "Auto-heal: uv.lock eksik; uv lock ile deterministik lock dosyası üretilecek."
        if ! uv lock; then
            warn "Auto-heal: eksik uv.lock yeniden üretilemedi."
            return 1
        fi
        action="${action}+uv-lock-created"
    fi

    if ! uv cache prune >/tmp/sidar_uv_cache_prune.log 2>&1; then
        warn "Auto-heal: uv cache prune başarısız oldu; sync retry yine de denenecek."
    else
        action="${action}+uv-cache-pruned"
    fi

    sidar_write_remediation_report "${SIDAR_CURRENT_INSTALL_PHASE:-04_workspace}" "uv-sync" "$action"
    return 0
}

sidar_remediate_root_owned_venv() {
    local action="venv-permission-remediation"
    local venv_dir="$SCRIPT_DIR/.venv"
    local venv_backup=""

    [[ -d "$venv_dir" ]] || return 1

    cd "$SCRIPT_DIR" || return 1
    mkdir -p artifacts/install/remediation

    venv_backup="artifacts/install/remediation/venv_permission_blocked_$(date +%Y%m%d_%H%M%S)"
    warn "Auto-heal: izin/sahiplik sorunu tespit edildi; .venv güvenli yedek adına taşınacak: $venv_backup"
    if mv "$venv_dir" "$venv_backup" 2>/dev/null; then
        action="${action}+venv-backed-up"
    else
        warn "Auto-heal: .venv taşınamadı. Olası neden: üst dizinde yazma izni yok veya sahiplik root."
        warn "Düzeltme: sudo chown -R \"$USER:$USER\" \"$SCRIPT_DIR\""
        return 1
    fi

    if ! command -v uv &>/dev/null; then
        warn "Auto-heal: uv bulunamadı; yeni .venv oluşturulamadı."
        return 1
    fi

    if ! uv venv --python "${PYTHON_VERSION}" "$venv_dir"; then
        warn "Auto-heal: .venv yeniden oluşturulamadı."
        return 1
    fi
    action="${action}+venv-recreated"

    sidar_write_remediation_report "${SIDAR_CURRENT_INSTALL_PHASE:-04_workspace}" "venv-permission" "$action"
    return 0
}

sidar_phase_remediation_strategy() {
    local phase="$1"
    local failed_cmd="$2"
    local reason="$3"

    # Tüm fazlarda geçerli: uzak betik checksum metadata eksikse self-heal
    # uygulanamaz; retry aynı duvara çarpar. Fail-fast davran ve operatöre yönlendir.
    if sidar_is_remote_script_checksum_missing "$failed_cmd" "$reason"; then
        local missing_var=""
        missing_var="$(sidar_detect_missing_checksum_var "$failed_cmd" "$reason")"
        local action="no-retry;manual-fix-required"
        [[ -n "$missing_var" ]] && action="${action};missing-var=${missing_var}"
        sidar_write_remediation_report "$phase" "remote-script-checksum-missing" "$action"
        return 1
    fi
    if sidar_is_installer_smoke_gate_failure "$failed_cmd" "$reason"; then
        sidar_write_remediation_report "$phase" "installer-smoke-gate-failure" "no-retry;manual-fix-required"
        return 1
    fi

    case "$phase" in
        03_runtime)
            if [[ "$failed_cmd $reason" == *"ollama_install"* || "$failed_cmd $reason" == *"sudo: timed out"* ]]; then
                if command -v ollama &>/dev/null && ollama -v &>/dev/null; then
                    sidar_write_remediation_report "$phase" "ollama-installed-despite-rc" "treat-as-success;resume-phase"
                    return 0
                fi
                sidar_write_remediation_report "$phase" "ollama-install-retry" "rerun-install-script;refresh-sudo"
                return 0
            fi
            ;;
        04_workspace)
            if [[ "$failed_cmd" == *"rm -rf"* && "$reason" == *"Permission denied"* ]]; then
                sidar_remediate_root_owned_venv
                return $?
            fi
            if [[ "$failed_cmd $reason" == *"uv sync"* || "$failed_cmd $reason" == *"uv.lock"* || "$failed_cmd $reason" == *"install_python_deps"* ]]; then
                sidar_remediate_uv_sync_failure "$failed_cmd $reason"
                return $?
            fi
            ;;
        02_repo|05_frontend|06_models|06_services)
            sidar_write_remediation_report "$phase" "transient-phase-retry" "no-destructive-change;resume-phase"
            return 0
            ;;
    esac

    return 1
}

sidar_emit_remediation_guidance() {
    local phase="$1"
    local failed_cmd="$2"
    local reason="$3"

    if sidar_is_remote_script_checksum_missing "$failed_cmd" "$reason"; then
        local missing_var=""
        local script_url=""
        missing_var="$(sidar_detect_missing_checksum_var "$failed_cmd" "$reason")"
        case "$missing_var" in
            OLLAMA_INSTALL_SHA256) script_url="https://ollama.com/install.sh" ;;
            UV_INSTALL_SHA256) script_url="https://astral.sh/uv/install.sh" ;;
            *) script_url="<ilgili uzak betik URL'i>" ;;
        esac
        warn "Auto-heal: ${phase} fazı uzak betik checksum metadata eksikliği nedeniyle durdu. Bu durum self-heal ile güvenli biçimde onarılamaz (retry aynı duvara çarpar)."
        if ! declare -F remote_script_checksum_hint >/dev/null 2>&1; then
            local remediation_utils_dir=""
            remediation_utils_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
            # shellcheck source=/dev/null
            # shellcheck disable=SC1090
            source "${remediation_utils_dir}/remote_script.sh"
        fi
        if [[ -n "$missing_var" && "$script_url" != "<"* ]]; then
            local script_label="remote_install"
            case "$missing_var" in
                OLLAMA_INSTALL_SHA256) script_label="ollama_install" ;;
                UV_INSTALL_SHA256) script_label="uv_install" ;;
            esac
            while IFS= read -r guidance_line; do
                warn "$guidance_line"
            done < <(remote_script_checksum_hint "$script_url" "$script_label" "$missing_var")
        else
            warn "NEXT STEP → <ilgili>_SHA256=<hash> ./install_sidar.sh  (detay aşağıda)"
            warn "İlgili *_SHA256 değişkenini (UV_INSTALL_SHA256 veya OLLAMA_INSTALL_SHA256) tanımlayın."
        fi
        return 0
    fi
    if sidar_is_installer_smoke_gate_failure "$failed_cmd" "$reason"; then
        warn "Auto-heal: ${phase} fazı installer smoke gate hatası nedeniyle durdu. Bu sinyal deterministiktir; aynı imza retry ile düzelmez."
        warn "NEXT STEP → Smoke gate version preflight logundaki stderr satırlarını inceleyin; INSTALL_SIDAR_VERSION, pyproject.toml version ve source install_sidar.sh erken çıkış nedenini düzeltip ./install_sidar.sh çalıştırın."
        return 0
    fi

    return 1
}

sidar_resume_after_remediation() {
    local phase="$1"
    local next_attempt="${2:-1}"
    local resume_runtime_mode_selected="${APP_RUNTIME_MODE_SELECTED:-}"
    local resume_runtime_mode="${APP_RUNTIME_MODE:-}"
    local resume_gpu_available="${GPU_AVAILABLE:-}"
    local resume_cwd="${SCRIPT_DIR:-${TARGET_DIR:-$PWD}}"
    local resume_failure_signature="${SIDAR_INSTALL_LAST_FAILURE_SIGNATURE:-}"
    local resume_failure_phase="${SIDAR_INSTALL_LAST_FAILURE_PHASE:-}"

    warn "Auto-heal: kurulum ${phase} fazından resume edilecek (attempt=${next_attempt})."
    export SIDAR_INSTALL_RESUME_FROM_PHASE="$phase"
    export SIDAR_INSTALL_REMEDIATION_ATTEMPT="$next_attempt"
    # shellcheck disable=SC2016  # Inner bash expands env-provided cwd and argv after exec.
    exec env \
        SIDAR_INSTALL_RESUME_FROM_PHASE="$phase" \
        SIDAR_INSTALL_REMEDIATION_ATTEMPT="$next_attempt" \
        SIDAR_INSTALL_AUTO_HEAL="${SIDAR_INSTALL_AUTO_HEAL:-1}" \
        SIDAR_INSTALL_RESUME_CWD="$resume_cwd" \
        APP_RUNTIME_MODE_SELECTED="$resume_runtime_mode_selected" \
        APP_RUNTIME_MODE="$resume_runtime_mode" \
        GPU_AVAILABLE="$resume_gpu_available" \
        SIDAR_INSTALL_LAST_FAILURE_SIGNATURE="$resume_failure_signature" \
        SIDAR_INSTALL_LAST_FAILURE_PHASE="$resume_failure_phase" \
        bash -c 'cd "$SIDAR_INSTALL_RESUME_CWD" && exec "$0" "$@"' \
        "$ORIGINAL_SCRIPT_PATH" "${SIDAR_INSTALL_ORIGINAL_ARGS[@]}"
}

sidar_handle_install_failure() {
    local exit_code="${1:-1}"
    local failed_line="${2:-unknown}"
    local failed_cmd="${3:-unknown}"
    local reason="${4:-}"
    local phase="${SIDAR_CURRENT_INSTALL_PHASE:-}"
    local attempt="${SIDAR_INSTALL_REMEDIATION_ATTEMPT:-0}"
    local max_attempts="${SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS:-1}"
    local failure_signature=""

    sidar_install_auto_heal_enabled || return 1
    [[ -n "$phase" ]] || return 1
    if sidar_phase_is_informational "$phase"; then
        warn "Auto-heal: ${phase} bilgilendirme fazı; retry/resume atlanıyor (warn-only)."
        sidar_write_remediation_report "$phase" "informational-phase" "warn-only;no-retry;no-resume"
        return 1
    fi
    [[ "$attempt" =~ ^[0-9]+$ ]] || attempt=0
    max_attempts="$(sidar_retry_budget_for_failure "$phase" "$failed_cmd" "$reason")"
    [[ "$max_attempts" =~ ^[0-9]+$ ]] || max_attempts=1
    failure_signature="$(sidar_failure_signature "$phase" "$failed_cmd" "$reason" "$exit_code")"

    if sidar_is_non_retryable_failure_code "$exit_code"; then
        warn "Auto-heal: ${phase} fazında deterministik hata (rc=${exit_code}) algılandı; retry/resume atlanıyor."
        sidar_write_remediation_report "$phase" "deterministic-failure-rc-${exit_code}" "fail-fast;no-retry;no-resume"
        return 1
    fi
    if sidar_is_non_retryable_failure_signal "$failed_cmd" "$reason"; then
        warn "Auto-heal: ${phase} fazında öğrenilmiş kalıcı hata imzası algılandı; retry/resume atlanıyor."
        local non_retryable_guidance=""
        non_retryable_guidance="$(sidar_non_retryable_failure_guidance "$failed_cmd" "$reason" || true)"
        if [[ -n "$non_retryable_guidance" ]]; then
            warn "Auto-heal: ${non_retryable_guidance}"
        fi
        sidar_write_remediation_report "$phase" "learned-non-retryable-failure" "fail-fast;no-retry;signature=${failure_signature}"
        return 1
    fi
    if [[ "$attempt" -gt 0 && "${SIDAR_INSTALL_LAST_FAILURE_PHASE:-}" == "$phase" && "${SIDAR_INSTALL_LAST_FAILURE_SIGNATURE:-}" == "$failure_signature" ]]; then
        warn "Auto-heal: ${phase} fazında aynı failure imzası tekrarlandı (${failure_signature}); retry erken kesiliyor."
        sidar_write_remediation_report "$phase" "repeated-failure-signature" "fail-fast;no-retry;signature=${failure_signature}"
        return 1
    fi
    export SIDAR_INSTALL_LAST_FAILURE_SIGNATURE="$failure_signature"
    export SIDAR_INSTALL_LAST_FAILURE_PHASE="$phase"

    if sidar_is_deterministic_failure_signal "$failed_cmd" "$reason"; then
        warn "Auto-heal: ${phase} fazında deterministik failure sinyali algılandı; retry bütçesi ${max_attempts} ile sınırlandı."
    fi

    if (( attempt >= max_attempts )); then
        warn "Auto-heal: ${phase} fazı için retry limiti aşıldı (${attempt}/${max_attempts})."
        sidar_write_remediation_report "$phase" "retry-budget-exhausted" "no-resume;max-attempts=${max_attempts}"
        return 1
    fi

    warn "Auto-heal: ${phase} fazında hata analiz ediliyor (line=${failed_line}, rc=${exit_code}, cmd=${failed_cmd})."
    if sidar_phase_remediation_strategy "$phase" "$failed_cmd" "$reason"; then
        sidar_resume_after_remediation "$phase" $((attempt + 1))
    fi
    if sidar_emit_remediation_guidance "$phase" "$failed_cmd" "$reason"; then
        sidar_write_remediation_report "$phase" "operator-guidance-emitted" "manual-fix-required;no-resume"
        return 1
    fi
    warn "Auto-heal: ${phase} fazı için uygulanabilir bir self-heal stratejisi bulunamadı; kök neden manuel çözülmeli."
    sidar_write_remediation_report "$phase" "no-remediation-strategy" "manual-fix-required;no-resume"

    return 1
}
