#!/usr/bin/env bash
# Sidar installer module: env_utils.sh
# shellcheck shell=bash

setup_python_env() {
    step "uv venv Ortamı"
    VENV_DIR="$SCRIPT_DIR/.venv"
    if [[ -d "$VENV_DIR" ]]; then
        info "Mevcut uv venv bulundu: $VENV_DIR"
    else
        info "Yeni uv venv oluşturuluyor ($PYTHON_VERSION)..."
        uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
        ok "uv venv oluşturuldu."
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    ok "Ortam aktif: $VENV_DIR"
}

# ── 4. uv kurulumu / güncelleme ──────────────────────────────────────────────

setup_uv() {
    step "uv Paket Yöneticisi"
    export UV_PROGRESS_BAR=on
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        local uv_install_script=""
        if [[ "$OFFLINE_MODE" == true ]]; then
            info "uv bulunamadı — çevrimdışı paketlerden kurulacak."
            uv_install_script="$(resolve_offline_package_file "uv/install.sh" || true)"
            [[ -z "$uv_install_script" ]] && uv_install_script="$(resolve_offline_package_file "uv_install.sh" || true)"
            [[ -z "$uv_install_script" ]] && uv_install_script="$(resolve_offline_package_file "install_uv.sh" || true)"
            [[ -n "$uv_install_script" ]] || fail "Çevrimdışı mod: offline_packages altında uv kurulum betiği bulunamadı (uv/install.sh, uv_install.sh, install_uv.sh)."
        else
            info "uv bulunamadı — resmi kurulum betiği ile indiriliyor..."
            DOWNLOADED_SCRIPT_FILE=""
            download_verified_script \
                "https://astral.sh/uv/install.sh" \
                "${UV_INSTALL_SHA256:-}" \
                "uv_install"
            validate_downloaded_script_file "$DOWNLOADED_SCRIPT_FILE" "uv_install"
            uv_install_script="$DOWNLOADED_SCRIPT_FILE"
        fi

        sh "$uv_install_script"
        [[ "$uv_install_script" == "${DOWNLOADED_SCRIPT_FILE:-}" ]] && rm -f "$DOWNLOADED_SCRIPT_FILE"
        if [[ -f "$HOME/.cargo/env" ]]; then
            # shellcheck disable=SC1090
            source "$HOME/.cargo/env"
        fi
        # Yeni kurulumlarda terminal yeniden başlatılmadan uv bulunabilsin
        export PATH="$HOME/.local/bin:$PATH"
    fi

    if ! command -v uv &>/dev/null; then
        fail "uv kurulumu başarısız oldu. Lütfen PATH ayarlarını ve kurulum çıktısını kontrol edin."
    fi
    ok "uv $(uv --version | cut -d' ' -f2)"
}

# ── 5. Python bağımlılıklarını kur ───────────────────────────────────────────

install_python_deps() {
    step "Python Bağımlılıkları Kuruluyor"

    cd "$SCRIPT_DIR"
    UV_CMD=(uv)

    local -a SYNC_ARGS=(--frozen --all-extras)

    if [[ ! -f "$SCRIPT_DIR/uv.lock" ]]; then
        fail "uv.lock bulunamadı. Deterministik kurulum için önce geliştirici ortamında 'uv lock' çalıştırıp lock dosyasını repoya commit edin."
    fi

    if [[ "$UPGRADE_LOCK" == true ]]; then
        info "--upgrade-lock verildi; uv.lock bilinçli olarak güncelleniyor (uv lock --upgrade)."
        if ! env -u UV_EXTRA -u UV_ALL_EXTRAS -u UV_NO_EXTRA "${UV_CMD[@]}" lock --upgrade; then
            fail "uv lock --upgrade başarısız oldu; uv.lock güncellenemedi."
        fi
    else
        info "uv.lock korunuyor; kurulum lock dosyasını değiştirmeden yapılacak. Güncelleme için --upgrade-lock kullanın."
    fi

    info "Bağımlılıklar kilitli profilden senkronlanıyor: uv sync --frozen --all-extras. Dev araçları self-healing için standarttır."
    if ! "${UV_CMD[@]}" sync "${SYNC_ARGS[@]}"; then
        fail "uv sync --frozen --all-extras başarısız oldu. Lock dosyası pyproject ile uyumsuzsa bilinçli olarak --upgrade-lock çalıştırın."
    fi

    ok "Python bağımlılıkları kilitli uv.lock üzerinden senkronlandı."
    ensure_env_file_secrets_after_uv_sync
    validate_runtime_env_loading
}

# ── 5.1 Pyright LSP aracını kur/doğrula ─────────────────────────────────────

install_pyright_lsp_tool() {
    step "Pyright LSP Aracı"

    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command -v pyright-langserver &>/dev/null; then
        ok "Pyright LSP hazır: $(command -v pyright-langserver)"
        return
    fi

    if [[ "$OFFLINE_MODE" == true ]]; then
        warn "Çevrimdışı modda pyright-langserver bulunamadı; LSP diagnostics için çevrimiçi ortamda 'uv tool install pyright' çalıştırın veya offline tool cache sağlayın."
        return
    fi

    info "Pyright LSP kuruluyor: uv tool install pyright"
    if ! uv tool install pyright; then
        warn "uv tool install pyright başarısız oldu; ajan LSP diagnostics özelliği için manuel kurulum gerekir."
        return
    fi

    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if command -v pyright-langserver &>/dev/null; then
        ok "Pyright LSP kuruldu: $(command -v pyright-langserver)"
    else
        warn "Pyright kuruldu ancak pyright-langserver PATH üzerinde bulunamadı; ~/.local/bin PATH ayarını kontrol edin."
    fi
}

# ── 6. Playwright tarayıcı motorları ─────────────────────────────────────────

