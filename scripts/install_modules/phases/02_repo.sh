#!/usr/bin/env bash

sidar_phase_apply_coverage_dark_mode_assets() {
    local source_css="$SCRIPT_DIR/assets/dark_mode.css"
    local web_ui_css="$SCRIPT_DIR/web_ui/style.css"
    local -a coverage_asset_dirs=(
        "$SCRIPT_DIR/htmlcov/assets"
        "$SCRIPT_DIR/artifacts/htmlcov/assets"
    )
    local -a coverage_html_dirs=(
        "$SCRIPT_DIR/htmlcov"
        "$SCRIPT_DIR/artifacts/htmlcov"
    )
    local assets_dir=""
    local html_dir=""

    if [[ ! -f "$source_css" ]]; then
        warn "Coverage dark-mode CSS bulunamadı: $source_css"
        return 0
    fi

    if [[ -f "$web_ui_css" ]]; then
        cp -f "$source_css" "$web_ui_css"
        info "Dark-mode CSS web_ui/style.css üzerine port edildi."
    else
        warn "web_ui/style.css bulunamadı, frontend dark-mode port adımı atlandı."
    fi

    for assets_dir in "${coverage_asset_dirs[@]}"; do
        mkdir -p "$assets_dir"
        cp -f "$source_css" "$assets_dir/dark_mode.css"
    done

    for html_dir in "${coverage_html_dirs[@]}"; do
        [[ -d "$html_dir" ]] || continue
        find "$html_dir" -type f -name '*.html' -exec sed -i 's/light-mode/dark-mode/g' {} +
    done

    ok "Coverage dark-mode varlıkları hazırlandı ve mevcut HTML raporları dark-mode'a geçirildi."
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
