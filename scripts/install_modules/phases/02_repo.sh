#!/usr/bin/env bash

sidar_phase_apply_coverage_dark_mode_assets() {
    local css_source="${SCRIPT_DIR}/assets/dark_mode.css"
    local report_dir=""
    local -a coverage_report_dirs=(
        "${SCRIPT_DIR}/htmlcov"
        "${SCRIPT_DIR}/artifacts/htmlcov"
    )

    if [[ ! -f "$css_source" ]]; then
        warn "Coverage dark mode CSS bulunamadı: ${css_source}"
        return 0
    fi

    for report_dir in "${coverage_report_dirs[@]}"; do
        mkdir -p "${report_dir}/assets"
        install -m 0644 "$css_source" "${report_dir}/assets/dark_mode.css"
    done

    ok "Coverage dark mode CSS rapor klasörlerine uygulandı."
}

sidar_phase_bootstrap_repo_system() {
    # Kritik sıra:
    # 1) Sistem bağımlılıkları (git/curl vb.)
    # 2) Repo senkronizasyonu (git clone/pull)
    # 3) Ön koşul doğrulaması (uv/Python/FFmpeg/Docker/Ollama)
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR" || return
    sidar_phase_apply_coverage_dark_mode_assets
}
