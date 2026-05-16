#!/usr/bin/env bash
# Sidar installer module: gpu_utils.sh
# shellcheck shell=bash

detect_gpu() {
    step "GPU Tespiti"
    GPU_AVAILABLE=false
    CUDA_VERSION=""

    if [[ "$FORCE_CPU" == true ]]; then
        warn "--cpu bayrağı: GPU kullanımı devre dışı bırakıldı."
        return
    fi

    local SMI_CMD=""
    local smi_ping_out=""
    local query_out=""
    if command -v nvidia-smi &>/dev/null; then
        SMI_CMD="nvidia-smi"
    elif command -v nvidia-smi.exe &>/dev/null; then
        SMI_CMD="nvidia-smi.exe"
    fi

    if [[ -n "$SMI_CMD" ]]; then
        smi_ping_out=$("$SMI_CMD" -L 2>/dev/null | head -1 || true)
    fi

    if [[ -n "$SMI_CMD" ]] && [[ -n "$smi_ping_out" ]]; then
        query_out=$("$SMI_CMD" --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)
        GPU_NAME="${query_out:-Bilinmiyor}"

        query_out=$("$SMI_CMD" --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || true)
        VRAM_MB=$(echo "${query_out:-0}" | tr -d ' ,' )
        if [[ -z "$VRAM_MB" ]]; then
            VRAM_MB="0"
        fi

        CUDA_VERSION=$("$SMI_CMD" 2>/dev/null | grep -oP 'CUDA Version: \K[\d.]+' | head -1 || true)
        DRIVER_VER=$("$SMI_CMD" --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || true)

        GPU_AVAILABLE=true
        if [[ "${RUN_GPU_STRESS:-0}" != "1" ]]; then
            export RUN_GPU_STRESS=1
            info "GPU tespit edildiği için RUN_GPU_STRESS=1 otomatik etkinleştirildi."
        fi
        ok "GPU     : $GPU_NAME"
        ok "VRAM    : ${VRAM_MB} MiB"
        ok "Sürücü  : $DRIVER_VER"
        ok "CUDA    : $CUDA_VERSION"

        if [[ "$WSL2" == true ]]; then
            info "WSL2 üzerinde CUDA, Windows NVIDIA sürücüsü (libcuda.so) üzerinden erişilir."
        fi
    else
        if command -v rocm-smi &>/dev/null || lspci 2>/dev/null | grep -qi "AMD/ATI"; then
            warn "AMD GPU tespit edildi. Bu kurulum akışı NVIDIA/CUDA odaklıdır; Docker için CPU profili kullanılacak."
        fi
        if [[ "$(uname -s)" == "Darwin" ]] && [[ "$(uname -m)" == "arm64" ]]; then
            warn "Apple Silicon (arm64) tespit edildi. CUDA/NVIDIA akışı devre dışı; CPU profili kullanılacak."
        fi
        warn "NVIDIA GPU bulunamadı veya nvidia-smi erişilemez — CPU modunda kurulum yapılacak."
    fi
}

# ── NVIDIA Container Toolkit Kurulumu ──────────────────────────────────────────

setup_nvidia_docker() {
    if [[ "$GPU_AVAILABLE" == true ]] && command -v docker &>/dev/null; then
        step "Docker GPU Desteği (nvidia-container-toolkit)"
        if ! command -v nvidia-ctk &>/dev/null; then
            warn "nvidia-container-toolkit bulunamadı. Kurulum başlatılıyor (sudo şifreniz istenebilir)..."

            # NVIDIA repolarını ekle ve kur
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg --yes
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
              sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
              sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

            sudo apt-get update
            sudo apt-get install -y nvidia-container-toolkit

            # Docker'ı NVIDIA runtime kullanacak şekilde yapılandır
            sudo nvidia-ctk runtime configure --runtime=docker

            # Docker daemon'ı çalışma tipine duyarlı şekilde yeniden başlat
            info "Docker servisi yeniden başlatılıyor..."
            if command -v systemctl &>/dev/null && systemctl cat docker &>/dev/null; then
                if systemctl is-active --quiet docker; then
                    sudo systemctl restart docker
                    ok "Docker servisi systemd üzerinden yeniden başlatıldı."
                else
                    warn "Docker systemd ünitesi mevcut ama aktif değil. Docker Desktop/WSL entegrasyonu kullanılıyor olabilir."
                    info "nvidia-container-toolkit değişiklikleri için gerekirse Windows üzerinden Docker Desktop'ı yeniden başlatın."
                fi
            elif command -v service &>/dev/null && service docker status >/dev/null 2>&1; then
                sudo service docker restart
                ok "Docker servisi SysV/service üzerinden yeniden başlatıldı."
            else
                warn "Docker systemd veya service üzerinden yönetilmiyor (Docker Desktop kullanılıyor olabilir)."
                info "nvidia-container-toolkit'in aktif olması için Windows üzerinden Docker Desktop'ı yeniden başlatmanız gerekebilir."
            fi
            ok "nvidia-container-toolkit kuruldu ve Docker yapılandırıldı."
        else
            ok "nvidia-container-toolkit zaten kurulu."
        fi
    fi
}


