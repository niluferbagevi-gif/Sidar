#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck shell=bash
# Post-bootstrap runtime helpers sourced by the install_sidar.sh facade.

run_with_progress_hint() {
    local label="$1"
    shift
    local -a cmd=("$@")

    "${cmd[@]}" &
    local cmd_pid=$!
    local pct=5

    while kill -0 "$cmd_pid" 2>/dev/null; do
        local filled=$((pct / 4))
        local empty=$((25 - filled))
        local bar_filled
        local bar_empty
        printf -v bar_filled '%*s' "$filled" ''
        printf -v bar_empty '%*s' "$empty" ''
        bar_filled="${bar_filled// /█}"
        bar_empty="${bar_empty// /░}"
        echo -e "${BLUE}[${bar_filled}${bar_empty}] ${pct}% ${label}${NC}" >&2

        pct=$((pct + 5))
        if (( pct > 95 )); then
            pct=95
        fi
        sleep 4
    done

    wait "$cmd_pid"
    local cmd_rc=$?
    if [[ "$cmd_rc" -eq 0 ]]; then
        echo -e "${GREEN}[█████████████████████████] 100% ${label}${NC}" >&2
    fi
    return "$cmd_rc"
}

SIDAR_PROMPT_TIMEOUT="${SIDAR_PROMPT_TIMEOUT:-180}"

prompt_yes_no_with_timeout_default_yes() {
    local prompt="$1"
    local timeout_seconds="${2:-$SIDAR_PROMPT_TIMEOUT}"
    local reply=""

    clear_stdin_buffer
    if read -r -t "$timeout_seconds" -p "$prompt" reply 2>/dev/tty; then
        :
    else
        warn "$(sidar_t timeout_yes "$timeout_seconds")"
        reply="E"
    fi

    echo "$reply"
}

prompt_yes_no_with_timeout_default_no() {
    local prompt="$1"
    local timeout_seconds="${2:-$SIDAR_PROMPT_TIMEOUT}"
    local reply=""

    clear_stdin_buffer
    if read -r -t "$timeout_seconds" -p "$prompt" reply 2>/dev/tty; then
        :
    else
        warn "$(sidar_t timeout_no "$timeout_seconds")"
        reply="H"
    fi

    echo "$reply"
}

cleanup_temp_install_modules_if_needed() {
    local exit_code="${1:-0}"
    local keep_temp_raw="${SIDAR_KEEP_TEMP_MODULES:-0}"
    keep_temp_raw="$(echo "$keep_temp_raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    if [[ "${KEEP_TEMP_MODULES:-false}" == "true" || "$keep_temp_raw" == "1" || "$keep_temp_raw" == "true" || "$keep_temp_raw" == "yes" ]]; then
        [[ -n "${INSTALL_HELPERS_TEMP_DIR:-}" && -d "$INSTALL_HELPERS_TEMP_DIR" ]] && info "Geçici modül dizini korunuyor (debug): $INSTALL_HELPERS_TEMP_DIR"
        return 0
    fi

    if [[ "$exit_code" -ne 0 ]]; then
        [[ -n "${INSTALL_HELPERS_TEMP_DIR:-}" && -d "$INSTALL_HELPERS_TEMP_DIR" ]] && warn "Kurulum hata ile sonlandı (exit=${exit_code}); debug için geçici modül dizini korunuyor: $INSTALL_HELPERS_TEMP_DIR"
        warn "İsterseniz sonraki çalıştırmada --keep-temp-modules veya SIDAR_KEEP_TEMP_MODULES=1 kullanabilirsiniz."
        return 0
    fi

    if [[ -n "${INSTALL_HELPERS_TEMP_DIR:-}" && -d "$INSTALL_HELPERS_TEMP_DIR" ]]; then
        rm -rf "$INSTALL_HELPERS_TEMP_DIR"
        info "Geçici modül dizini temizlendi: $INSTALL_HELPERS_TEMP_DIR"
    fi
}

relocate_log_file_if_needed() {
    [[ -n "${TARGET_DIR:-}" ]] || return 0
    local target_log_dir="${TARGET_DIR}/logs"
    local source_log_dir="$LOG_DIR"

    if [[ -f "$LOG_FILE" && "$LOG_DIR" != "$target_log_dir" ]]; then
        mkdir -p "$target_log_dir"
        mv "$LOG_FILE" "$target_log_dir/"
        LOG_DIR="$target_log_dir"
        LOG_FILE="$target_log_dir/$(basename "$LOG_FILE")"
        info "Kurulum log dosyası ${LOG_FILE} konumuna taşındı."

        if [[ -d "$source_log_dir" ]]; then
            rmdir "$source_log_dir" 2>/dev/null || true
        fi
    fi
}
