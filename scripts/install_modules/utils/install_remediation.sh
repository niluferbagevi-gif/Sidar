#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_INSTALL_REMEDIATION_SH_LOADED=1

# Lightweight installer auto-heal / resume controller.
# The goal is intentionally narrow and deterministic: remediate known transient
# installer breakages (uv lock/sync, stale venv/cache, transient network phase
# retry) and then re-exec the installer from the failed phase instead of asking
# the operator to restart from scratch.

sidar_install_auto_heal_enabled() {
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
Docker Desktop > Settings > Resources > WSL Integration bölümünde '${distro}' için explicit toggle'ı açıp Apply & restart yapın. Not: "Enable integration with my default WSL distro" açık olsa bile yalnızca default distro'yu kapsar; default distro değiştiğinde explicit toggle kapalıysa Docker socket mount'u bozulabilir.
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

sidar_remediate_uv_sync_failure() {
    local action="uv-sync-remediation"
    cd "$SCRIPT_DIR" || return 1

    if ! command -v uv &>/dev/null; then
        warn "Auto-heal: uv bulunamadı; uv lock/sync remediation uygulanamadı."
        return 1
    fi

    mkdir -p artifacts/install/remediation

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

sidar_phase_remediation_strategy() {
    local phase="$1"
    local failed_cmd="$2"
    local reason="$3"

    case "$phase" in
        04_workspace)
            if [[ "$failed_cmd $reason" == *"uv sync"* || "$failed_cmd $reason" == *"uv.lock"* || "$failed_cmd $reason" == *"install_python_deps"* ]]; then
                sidar_remediate_uv_sync_failure
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

sidar_resume_after_remediation() {
    local phase="$1"
    local next_attempt="${2:-1}"
    local resume_runtime_mode_selected="${APP_RUNTIME_MODE_SELECTED:-}"
    local resume_runtime_mode="${APP_RUNTIME_MODE:-}"
    local resume_gpu_available="${GPU_AVAILABLE:-}"
    local resume_cwd="${SCRIPT_DIR:-${TARGET_DIR:-$PWD}}"

    warn "Auto-heal: kurulum ${phase} fazından resume edilecek (attempt=${next_attempt})."
    export SIDAR_INSTALL_RESUME_FROM_PHASE="$phase"
    export SIDAR_INSTALL_REMEDIATION_ATTEMPT="$next_attempt"
    exec env \
        SIDAR_INSTALL_RESUME_FROM_PHASE="$phase" \
        SIDAR_INSTALL_REMEDIATION_ATTEMPT="$next_attempt" \
        SIDAR_INSTALL_AUTO_HEAL="${SIDAR_INSTALL_AUTO_HEAL:-1}" \
        SIDAR_INSTALL_RESUME_CWD="$resume_cwd" \
        APP_RUNTIME_MODE_SELECTED="$resume_runtime_mode_selected" \
        APP_RUNTIME_MODE="$resume_runtime_mode" \
        GPU_AVAILABLE="$resume_gpu_available" \
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

    [[ -n "$phase" ]] || return 1
    if sidar_phase_is_informational "$phase"; then
        warn "Auto-heal: ${phase} bilgilendirme fazı; retry/resume atlanıyor (warn-only)."
        sidar_write_remediation_report "$phase" "informational-phase" "warn-only;no-retry;no-resume"
        return 1
    fi
    sidar_install_auto_heal_enabled || return 1
    [[ "$attempt" =~ ^[0-9]+$ ]] || attempt=0
    [[ "$max_attempts" =~ ^[0-9]+$ ]] || max_attempts=1
    if (( attempt >= max_attempts )); then
        warn "Auto-heal: ${phase} fazı için retry limiti aşıldı (${attempt}/${max_attempts})."
        return 1
    fi

    warn "Auto-heal: ${phase} fazında hata analiz ediliyor (line=${failed_line}, rc=${exit_code}, cmd=${failed_cmd})."
    if sidar_phase_remediation_strategy "$phase" "$failed_cmd" "$reason"; then
        sidar_resume_after_remediation "$phase" $((attempt + 1))
    fi

    return 1
}
