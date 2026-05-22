#!/usr/bin/env bash

sidar_phase_apply_coverage_dark_mode_assets() {
    local source_css="$SCRIPT_DIR/assets/dark_mode.css"
    local -a coverage_asset_dirs=(
        "$SCRIPT_DIR/htmlcov/assets"
        "$SCRIPT_DIR/artifacts/htmlcov/assets"
    )

    if [[ ! -f "$source_css" ]]; then
        warn "Coverage dark-mode CSS bulunamadı: $source_css"
        return 0
    fi

    for assets_dir in "${coverage_asset_dirs[@]}"; do
        mkdir -p "$assets_dir"
        cp -f "$source_css" "$assets_dir/dark_mode.css"
    done

    ok "Coverage dark-mode CSS hazırlandı (htmlcov/assets, artifacts/htmlcov/assets)."
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
