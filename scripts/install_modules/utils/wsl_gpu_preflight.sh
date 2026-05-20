#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_WSL_GPU_PREFLIGHT_SH_LOADED=1

# Early WSL2 + NVIDIA/RTX health gate.  This runs before package installation so
# driver passthrough problems are reported before the installer spends time on
# uv, Docker, Ollama models, or frontend assets.

sidar_wsl_gpu_preflight_mode() {
    local mode="${SIDAR_WSL_GPU_PREFLIGHT:-strict}"
    mode="$(echo "$mode" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    case "$mode" in
        strict|fail|1|true|yes|y|evet|e) echo "strict" ;;
        warn|warning|soft) echo "warn" ;;
        off|skip|0|false|no|n|hayir|hayır|h) echo "off" ;;
        *) echo "strict" ;;
    esac
}

sidar_find_nvidia_smi() {
    if command -v nvidia-smi &>/dev/null; then
        command -v nvidia-smi
        return 0
    fi
    if command -v nvidia-smi.exe &>/dev/null; then
        command -v nvidia-smi.exe
        return 0
    fi
    if [[ -x /usr/lib/wsl/lib/nvidia-smi ]]; then
        echo "/usr/lib/wsl/lib/nvidia-smi"
        return 0
    fi
    return 1
}

sidar_report_wsl_gpu_problem() {
    local severity="$1"
    shift
    case "$severity" in
        fail) warn "WSL2 GPU pre-flight: $*" ;;
        *) warn "WSL2 GPU pre-flight uyarısı: $*" ;;
    esac
}

run_wsl2_gpu_preflight() {
    step "WSL2 / NVIDIA GPU Pre-Flight Kontrolü"

    local mode=""
    mode="$(sidar_wsl_gpu_preflight_mode)"

    if [[ "$mode" == "off" ]]; then
        warn "WSL2 GPU pre-flight kontrolü SIDAR_WSL_GPU_PREFLIGHT=off ile atlandı."
        return 0
    fi

    if [[ "${WSL2:-false}" != true ]]; then
        info "WSL2 tespit edilmedi; NVIDIA WSL2 passthrough pre-flight kontrolü atlandı."
        return 0
    fi

    if [[ "${FORCE_CPU:-false}" == true ]]; then
        warn "--cpu etkin: WSL2 GPU pre-flight rapor modunda atlandı; kurulum CPU profiliyle devam edecek."
        return 0
    fi

    local failures=0
    local smi_cmd=""
    local smi_list=""
    local gpu_name=""
    local driver_version=""
    local vram_mb=""
    local compute_capability=""
    local cuda_version=""
    local ollama_version_url=""

    if ! smi_cmd="$(sidar_find_nvidia_smi)"; then
        sidar_report_wsl_gpu_problem fail "nvidia-smi bulunamadı. Windows NVIDIA sürücüsünü WSL2 destekli güncelleyin ve WSL'i 'wsl --shutdown' ile yeniden başlatın."
        failures=$((failures + 1))
    else
        info "nvidia-smi yolu: $smi_cmd"
        if ! smi_list="$($smi_cmd -L 2>&1)" || [[ -z "$smi_list" ]]; then
            sidar_report_wsl_gpu_problem fail "nvidia-smi GPU listeleyemedi: ${smi_list:-boş çıktı}. WSL2 GPU passthrough hazır değil."
            failures=$((failures + 1))
        else
            ok "WSL2 NVIDIA passthrough aktif: $(echo "$smi_list" | head -n1)"

            gpu_name="$($smi_cmd --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 || true)"
            driver_version="$($smi_cmd --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 || true)"
            vram_mb="$($smi_cmd --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n1 | tr -d ' ,' || true)"
            compute_capability="$($smi_cmd --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]' || true)"
            cuda_version="$($smi_cmd 2>/dev/null | sed -n 's/.*CUDA Version: \([0-9.]*\).*/\1/p' | head -n1 || true)"

            [[ -n "$gpu_name" ]] && ok "GPU: $gpu_name"
            [[ -n "$driver_version" ]] && ok "Windows NVIDIA sürücüsü: $driver_version"
            [[ -n "$cuda_version" ]] && ok "WSL2 CUDA passthrough sürümü: $cuda_version"
            [[ -n "$compute_capability" ]] && ok "Compute capability: $compute_capability"
            if [[ "$vram_mb" =~ ^[0-9]+$ ]]; then
                ok "VRAM: ${vram_mb} MiB"
                if (( vram_mb < 8192 )); then
                    sidar_report_wsl_gpu_problem warn "Yerel Ollama/qwen2.5-coder:7b için önerilen VRAM en az 8192 MiB; mevcut ${vram_mb} MiB. Daha küçük model veya CPU modu gerekebilir."
                fi
            fi

            if [[ -n "$gpu_name" && ! "$gpu_name" =~ (RTX|Blackwell|Ada|Ampere|NVIDIA) ]]; then
                sidar_report_wsl_gpu_problem warn "GPU adı RTX/NVIDIA LLM hızlandırma profiline benzemiyor: $gpu_name"
            fi
        fi
    fi

    if [[ -e /dev/dxg ]]; then
        ok "WSL2 GPU cihazı hazır: /dev/dxg"
    else
        sidar_report_wsl_gpu_problem fail "/dev/dxg bulunamadı. WSL2 GPU compute köprüsü etkin değil; Windows GPU sürücüsü/WSL kernel entegrasyonunu kontrol edin."
        failures=$((failures + 1))
    fi

    if [[ -e /usr/lib/wsl/lib/libcuda.so || -e /usr/lib/wsl/lib/libcuda.so.1 ]] || ldconfig -p 2>/dev/null | grep -q 'libcuda.so'; then
        ok "libcuda WSL2 içinde görünür durumda."
    else
        sidar_report_wsl_gpu_problem fail "libcuda.so WSL2 içinde bulunamadı. NVIDIA Windows sürücüsü WSL2'ye aktarılmamış görünüyor."
        failures=$((failures + 1))
    fi

    SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME="${SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME:-false}"
    SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG="${SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG:-}"

    if command -v docker &>/dev/null; then
        local docker_runtimes_json=""
        if ! docker_runtimes_json="$(docker info --format '{{json .Runtimes}}' 2>/dev/null)"; then
            info "Docker daemon şu an erişilebilir değil; NVIDIA runtime pre-flight kontrolü atlandı (runtime fazında tekrar doğrulanacak)."
        elif echo "$docker_runtimes_json" | grep -q 'nvidia'; then
            ok "Docker NVIDIA runtime kayıtlı."
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME="false"
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG=""
        else
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME="true"
            SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG="Docker NVIDIA runtime henüz kayıtlı görünmüyor; setup_nvidia_docker fazı bunu kurmayı/etkinleştirmeyi deneyecek."
            info "$SIDAR_DEFERRED_WARN_DOCKER_NVIDIA_RUNTIME_MSG"
        fi
    else
        info "Docker CLI henüz yok; Docker GPU runtime kontrolü sistem bağımlılıkları fazına bırakıldı."
    fi

    if command -v ollama &>/dev/null; then
        ok "Ollama CLI hazır: $(ollama -v 2>/dev/null | head -n1 || echo ollama)"
        ollama_version_url="$(resolve_ollama_version_url "$SCRIPT_DIR/.env")"
        if command -v curl &>/dev/null && curl -sf "$ollama_version_url" >/dev/null 2>&1; then
            ok "Ollama API WSL2 pre-flight sırasında yanıt veriyor (${ollama_version_url})."
        else
            sidar_report_wsl_gpu_problem warn "Ollama CLI var ancak API şu an yanıt vermiyor; model indirme fazı yerel servisi başlatmayı deneyecek."
        fi
    else
        info "Ollama CLI henüz kurulu değil; donanım pre-flight tamamlanınca ön koşul fazında kurulacak."
    fi

    if (( failures > 0 )); then
        if [[ "$mode" == "warn" ]]; then
            warn "WSL2 GPU pre-flight ${failures} kritik bulgu üretti ancak SIDAR_WSL_GPU_PREFLIGHT=warn nedeniyle kurulum devam ediyor."
            return 0
        fi
        fail "WSL2 GPU pre-flight başarısız (${failures} kritik bulgu). Düzeltip yeniden çalıştırın veya bilinçli CPU kurulumu için --cpu / SIDAR_WSL_GPU_PREFLIGHT=warn kullanın."
    fi

    ok "WSL2 / NVIDIA / Ollama donanım pre-flight kontrolü geçti."
}
