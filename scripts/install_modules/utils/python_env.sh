#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_PYTHON_ENV_SH_LOADED=1

# uv-only Python environment helpers for the phase-based Sidar installer.
# Package resolution and environment synchronization intentionally go through
# uv venv / uv sync; legacy environment and tool-install fallbacks are not used.

install_uv_cli() {
    step "uv CLI Paket Yöneticisi"
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
            # shellcheck source=/dev/null
            # shellcheck disable=SC1090,SC1091
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

create_uv_venv() {
    step "uv venv Ortamı"
    local expected_python_version="3.11"
    local requested_python_version="${PYTHON_VERSION:-$expected_python_version}"
    if [[ -n "${PYTHON_VERSION:-}" && "$requested_python_version" != "$expected_python_version" ]]; then
        warn "PYTHON_VERSION=${requested_python_version} algılandı; runtime için ${expected_python_version} zorunlu."
    fi
    # Global bırakılır: sonraki installer phase/helper fonksiyonları zorunlu
    # runtime sürümünü PYTHON_VERSION üzerinden okur. Local yapılırsa fazlar
    # arasında Python sürümü tekrar override edilip regression oluşabilir.
    PYTHON_VERSION="$expected_python_version"
    VENV_DIR="$SCRIPT_DIR/.venv"
    info "Python sürümü uv ile sabitleniyor ($PYTHON_VERSION)..."
    uv python install "$PYTHON_VERSION"

    if [[ -d "$VENV_DIR" ]]; then
        info "Mevcut uv venv bulundu: $VENV_DIR"
        local detected_python_version=""
        detected_python_version="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
        if [[ -z "$detected_python_version" && -f "$VENV_DIR/pyvenv.cfg" ]]; then
            detected_python_version="$(awk -F'= *' '/^version[[:space:]]*=/{print $2; exit}' "$VENV_DIR/pyvenv.cfg" 2>/dev/null | awk -F. '{print $1"."$2}' || true)"
        fi
        if [[ "$detected_python_version" == "$PYTHON_VERSION" ]]; then
            ok ".venv mevcut sürümle uyumlu: $detected_python_version"
        else
            warn "Mevcut .venv Python sürümü ${detected_python_version:-bilinmiyor}; zorunlu sürüm $PYTHON_VERSION. .venv yeniden oluşturuluyor."
            if [[ -O "$VENV_DIR" ]]; then
                if ! rm -rf "$VENV_DIR"; then
                    fail ".venv silinemedi: $VENV_DIR. Düzeltme: sudo chown -R $(id -u):$(id -g) \"$SCRIPT_DIR\" && rm -rf \"$VENV_DIR\""
                fi
            else
                local venv_backup_dir
                venv_backup_dir="$SCRIPT_DIR/.venv.broken-$(date +%Y%m%d-%H%M%S)"
                warn ".venv mevcut kullanıcıya ait değil. Güvenli yol olarak yedek adla taşımayı deniyorum: $venv_backup_dir"
                if mv "$VENV_DIR" "$venv_backup_dir" 2>/dev/null; then
                    warn "Eski .venv taşındı: $venv_backup_dir"
                elif [[ -t 0 ]] && command -v sudo &>/dev/null; then
                    warn "Taşıma başarısız; etkileşimli modda sudo ile kaldırma onayı istenecek."
                    if sudo rm -rf "$VENV_DIR"; then
                        ok "Sudo ile eski .venv kaldırıldı."
                    else
                        fail ".venv kaldırılamadı. Düzeltme: sudo chown -R $(id -u):$(id -g) \"$SCRIPT_DIR\" && rm -rf \"$VENV_DIR\""
                    fi
                else
                    fail ".venv mevcut kullanıcıya ait değil ve taşınamadı. Düzeltme: sudo chown -R $(id -u):$(id -g) \"$SCRIPT_DIR\" (veya yalnızca .venv) ardından kurulumu tekrar çalıştırın."
                fi
            fi
            uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
            ok "uv venv zorunlu Python $PYTHON_VERSION ile yeniden oluşturuldu."
        fi
    else
        info "Yeni uv venv oluşturuluyor ($PYTHON_VERSION)..."
        uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
        ok "uv venv oluşturuldu."
    fi
    # shellcheck source=/dev/null
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    ok "Ortam aktif: $VENV_DIR"
}

install_python_deps() {
    step "Python Bağımlılıkları Kuruluyor"

    cd "$SCRIPT_DIR" || return 1
    UV_CMD=(uv)

    # Standart kurulum komutu: uv sync --frozen --all-extras — all extra grubu
    # dev dahil tüm extras'ı içerir (pyproject.toml:194).
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

    ensure_portaudio_dev "uv sync --frozen --all-extras"

    info "Standart kurulum komutu: uv sync --frozen --all-extras — all extra grubu dev dahil tüm extras'ı içerir (pyproject.toml:194)."
    if ! "${UV_CMD[@]}" sync "${SYNC_ARGS[@]}"; then
        fail "Standart kurulum komutu başarısız oldu: uv sync --frozen --all-extras. Lock dosyası pyproject ile uyumsuzsa bilinçli olarak --upgrade-lock çalıştırın."
    fi

    if ! "${UV_CMD[@]}" run python -c "import pydantic, pydantic_settings" >/dev/null 2>&1; then
        fail "Zorunlu runtime bağımlılık doğrulaması başarısız: pydantic/pydantic-settings import edilemedi. Standart kurulum komutunu temiz bir ortamda tekrar çalıştırın: uv sync --frozen --all-extras."
    fi

    ok "Zorunlu runtime bağımlılıkları doğrulandı: pydantic + pydantic-settings."
    ok "Python bağımlılıkları kilitli uv.lock üzerinden senkronlandı."
    ensure_env_file_secrets_after_uv_sync
    validate_runtime_env_loading
}

install_pyright_lsp_tool() {
    step "Pyright LSP Aracı"

    local venv_bin="$SCRIPT_DIR/.venv/bin"
    export PATH="$venv_bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if [[ -x "$venv_bin/pyright-langserver" ]]; then
        ok "Pyright LSP hazır: $venv_bin/pyright-langserver"
        return
    fi

    if uv run pyright-langserver --version >/dev/null 2>&1; then
        ok "Pyright LSP uv sync ortamında hazır: $(uv run python -c 'import shutil; print(shutil.which("pyright-langserver") or "uv-run")')"
        return
    fi

    fail "Pyright LSP bulunamadı. Standart kurulum komutunu çalıştırın: uv sync --frozen --all-extras. all extra grubu dev dahil tüm extras'ı içerir (pyproject.toml:194)."
}

select_pytorch_cuda_wheel_tag() {
    local override_tag="${PYTORCH_CUDA_WHEEL_TAG:-}"
    local cuda_version="${CUDA_VERSION:-}"
    local compute_capability="${GPU_COMPUTE_CAPABILITY:-}"
    local gpu_name="${GPU_NAME:-}"
    local compute_major=""
    local cuda_major=""
    local cuda_minor=""

    if [[ -n "$override_tag" ]]; then
        echo "$override_tag"
        return 0
    fi

    compute_major="${compute_capability%%.*}"
    if [[ "$compute_major" =~ ^[0-9]+$ ]] && (( compute_major >= 12 )); then
        # Blackwell / RTX 50xx sınıfı GPU'lar CUDA 12.6+ wheel ister; cu128 tercih edilir.
        echo "cu128"
        return 0
    fi

    if [[ "$gpu_name" =~ (Blackwell|RTX[[:space:]]*50|RTX[[:space:]]*5[0-9]{3}) ]]; then
        echo "cu128"
        return 0
    fi

    cuda_major="${cuda_version%%.*}"
    cuda_minor="${cuda_version#*.}"
    cuda_minor="${cuda_minor%%.*}"
    if [[ "$cuda_major" =~ ^[0-9]+$ && "$cuda_minor" =~ ^[0-9]+$ ]]; then
        if (( cuda_major > 12 || (cuda_major == 12 && cuda_minor >= 8) )); then
            echo "cu128"
            return 0
        fi
        if (( cuda_major == 12 && cuda_minor >= 6 )); then
            echo "cu126"
            return 0
        fi
    fi

    echo "cu124"
}

sync_pytorch_cuda_wheels() {
    local cuda_tag="${1:-}"
    [[ -n "$cuda_tag" ]] || cuda_tag="$(select_pytorch_cuda_wheel_tag)"
    local index_url="${PYTORCH_CUDA_INDEX_URL:-https://download.pytorch.org/whl/${cuda_tag}}"
    local -a sync_args=(
        --frozen
        --all-extras
        --index "$index_url"
        --reinstall-package torch
        --reinstall-package torchvision
        --reinstall-package torchaudio
    )

    info "PyTorch CUDA wheel seçimi uv sync ile uygulanıyor: ${cuda_tag} (${index_url})"
    if ! uv sync "${sync_args[@]}"; then
        fail "PyTorch CUDA bağımlılıkları uv sync ile senkronlanamadı (${cuda_tag})."
    fi
}

verify_torch_cuda() {
    if [[ "$GPU_AVAILABLE" == true ]]; then
        step "PyTorch CUDA Doğrulaması"
        if python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" >/dev/null 2>&1; then
                CUDA_OK=$(python -c "
import torch
avail = torch.cuda.is_available()
ver   = torch.version.cuda or 'N/A'
dev   = torch.cuda.get_device_name(0) if avail else 'N/A'
print(f'available={avail} cuda={ver} device={dev}')
" 2>/dev/null || echo "available=true cuda=N/A device=N/A")
            TORCH_CUDA_VER=$(echo "$CUDA_OK" | grep -oP 'cuda=\K[^ ]+')
            TORCH_GPU_NAME=$(echo "$CUDA_OK" | grep -oP 'device=\K.+')
            ok "PyTorch CUDA aktif: $TORCH_GPU_NAME (CUDA $TORCH_CUDA_VER)"
        else
            warn "PyTorch CUDA bulunamadı. torch CPU sürümü kurulmuş olabilir."
            info "GPU wheel için PyTorch yeniden kuruluyor (GPU compute capability/CUDA sürümüne göre dinamik index seçilecek)..."
            sync_pytorch_cuda_wheels "$(select_pytorch_cuda_wheel_tag)"

            if python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" >/dev/null 2>&1; then
                ok "PyTorch CUDA başarıyla kuruldu ve GPU tanındı."
            else
                fail "PyTorch CUDA kurulumu yine başarısız oldu. Lütfen manuel kontrol edin."
            fi
        fi
    fi
}
