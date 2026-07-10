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

wsl_powershell_read() {
    local ps_command="$1"
    powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; \$OutputEncoding=[System.Text.Encoding]::UTF8; $ps_command" 2>/dev/null \
        | tr -d '\r' | tail -n1
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
            if declare -F detect_cuda_driver_capability >/dev/null 2>&1; then
                cuda_version=$(detect_cuda_driver_capability "$smi_cmd")
            else
                cuda_version="$($smi_cmd 2>/dev/null | sed -n 's/.*CUDA Version: \([0-9.]*\).*/\1/p' | head -n1 || true)"
            fi

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

sidar_windows_json_sanitize() {
    python3 -c '
import sys

raw = sys.stdin.buffer.read()
if not raw:
    raise SystemExit(0)

if raw.startswith(b"\xff\xfe"):
    text = raw.decode("utf-16le", errors="replace")
elif raw.startswith(b"\xfe\xff"):
    text = raw.decode("utf-16be", errors="replace")
elif raw.startswith(b"\xef\xbb\xbf"):
    text = raw.decode("utf-8-sig", errors="replace")
elif b"\x00" in raw:
    text = raw.decode("utf-16le", errors="replace")
else:
    text = raw.decode("utf-8", errors="replace")

sys.stdout.write(text.replace("\r", ""))
'
}

sidar_read_docker_settings_json() {
    wsl_powershell_read "\$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { Get-Content \$p -Raw }" \
        | sidar_windows_json_sanitize
}

sidar_resolve_wsl_integration_fields() {
    local docker_settings_json="" enable_default="" integrated_csv=""
    docker_settings_json="$(sidar_read_docker_settings_json || true)"

    if [[ -n "$docker_settings_json" ]]; then
        if command -v jq &>/dev/null; then
            enable_default="$(printf '%s' "$docker_settings_json" | jq -r '.EnableIntegrationWithDefaultWslDistro // .enableIntegrationWithDefaultWslDistro // .wslEngineEnabled // .integration.wslEngineEnabled // empty' 2>/dev/null || true)"
            integrated_csv="$(printf '%s' "$docker_settings_json" | jq -r '
                (
                    .IntegratedWslDistros
                    // .integratedWslDistros
                    // .wsl.distros
                    // .integration.wslDistros
                    // []
                )
                | (if type=="array" then map(tostring) else [(.|keys[])] end)
                | join(",")
            ' 2>/dev/null || true)"
        elif command -v python3 &>/dev/null; then
            local _parsed_json
            _parsed_json="$(DOCKER_SETTINGS_JSON="$docker_settings_json" python3 - <<'PYJSON' 2>/dev/null || true
import json
import os

raw = os.environ.get("DOCKER_SETTINGS_JSON", "")
if not raw:
    raise SystemExit(0)

try:
    cfg = json.loads(raw)
except Exception:
    raise SystemExit(0)

enable = cfg.get("EnableIntegrationWithDefaultWslDistro")
if enable is None:
    enable = cfg.get("enableIntegrationWithDefaultWslDistro")
if enable is None:
    enable = cfg.get("wslEngineEnabled")
if enable is None and isinstance(cfg.get("integration"), dict):
    enable = cfg["integration"].get("wslEngineEnabled")

distros = cfg.get("IntegratedWslDistros")
if distros is None:
    distros = cfg.get("integratedWslDistros")
if distros is None and isinstance(cfg.get("wsl"), dict):
    distros = cfg["wsl"].get("distros")
if distros is None and isinstance(cfg.get("integration"), dict):
    distros = cfg["integration"].get("wslDistros")

if isinstance(distros, dict):
    names = [str(k) for k in distros.keys() if str(k)]
elif isinstance(distros, list):
    names = [str(v) for v in distros if str(v)]
else:
    names = []

print("" if enable is None else str(enable))
print(",".join(names))
PYJSON
)"
            if [[ -n "$_parsed_json" ]]; then
                enable_default="$(printf '%s\n' "$_parsed_json" | sed -n '1p')"
                integrated_csv="$(printf '%s\n' "$_parsed_json" | sed -n '2p')"
            fi
        fi
    else
        enable_default="$(wsl_powershell_read "\$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \$v=\$cfg.EnableIntegrationWithDefaultWslDistro; if (\$null -eq \$v) { \$v=\$cfg.enableIntegrationWithDefaultWslDistro }; if (\$null -eq \$v) { \$v=\$cfg.wslEngineEnabled }; if (\$null -eq \$v -and \$null -ne \$cfg.integration) { \$v=\$cfg.integration.wslEngineEnabled }; if (\$null -eq \$v) { '' } else { [string]\$v } }" || true)"
        integrated_csv="$(wsl_powershell_read "\$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \$list=\$null; if (\$cfg.IntegratedWslDistros) { \$list=@(\$cfg.IntegratedWslDistros) } elseif (\$cfg.integratedWslDistros) { \$list=@(\$cfg.integratedWslDistros) } elseif (\$null -ne \$cfg.wsl -and \$null -ne \$cfg.wsl.distros) { if (\$cfg.wsl.distros -is [System.Array]) { \$list=@(\$cfg.wsl.distros) } else { \$list=@(\$cfg.wsl.distros.PSObject.Properties | Select-Object -ExpandProperty Name) } } elseif (\$null -ne \$cfg.integration -and \$null -ne \$cfg.integration.wslDistros) { if (\$cfg.integration.wslDistros -is [System.Array]) { \$list=@(\$cfg.integration.wslDistros) } else { \$list=@(\$cfg.integration.wslDistros.PSObject.Properties | Select-Object -ExpandProperty Name) } }; if (\$list) { \$list | ForEach-Object { [string]\$_ } | Where-Object { \$_ } | Select-Object -Unique | Join-String -Separator ',' } }" || true)"
    fi

    printf 'enable_default=%s\n' "$enable_default"
    printf 'integrated_csv=%s\n' "$integrated_csv"
}

docker_desktop_wsl_integration_preflight() {
    step "Docker Desktop WSL Integration Durum Raporu"
    export WSL_INTEGRATION_PREFLIGHT_REPORTED=true
    export WSL_INTEGRATION_AUTOFIX_ELIGIBLE=false
    local _had_errexit=false
    [[ $- == *e* ]] && _had_errexit=true
    set +e

    if [[ "${WSL2:-false}" != true ]]; then
        info "WSL2 tespit edilmedi; Docker Desktop WSL Integration raporu atlandı."
        [[ "$_had_errexit" == true ]] && set -e
        return 0
    fi

    if ! command -v powershell.exe &>/dev/null; then
        warn "powershell.exe bulunamadı; Docker Desktop WSL Integration durumu doğrulanamadı."
        [[ "$_had_errexit" == true ]] && set -e
        return 0
    fi

    local current_distro="" default_distro="" enable_default="" integrated_csv="" integrated_norm=""
    local preflight_source_of_truth="${WSL_INTEGRATION_PREFLIGHT_SOURCE_OF_TRUTH:-runtime}"
    local in_integrated=false default_covers=false
    current_distro="${WSL_DISTRO_NAME:-}"
    if [[ "$preflight_source_of_truth" == "mock" ]]; then
        default_distro="${WSL_DEFAULT_DISTRO_NAME:-$current_distro}"
        info "WSL preflight source-of-truth=mock etkin: distro tespiti WSL_* env değişkenlerinden zorlanıyor."
    elif [[ -z "$current_distro" ]]; then
        current_distro="$(
            wsl.exe -l 2>/dev/null \
                | iconv -f UTF-16LE -t UTF-8 2>/dev/null \
                | tr -d '\0\r' \
                | awk '/\*/ { for (i=1;i<=NF;i++) if ($i!="*" && $i!~/^docker-desktop(-data)?$/) { print $i; exit } }' \
                || true
        )"
        if [[ -z "$current_distro" ]]; then
            current_distro="$(wsl.exe -l -q 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF && $0 !~ /^docker-desktop(-data)?$/ {print; exit}' || true)"
        fi
    fi
    [[ -n "$current_distro" ]] || current_distro="(bilinmiyor)"

    if [[ "$preflight_source_of_truth" != "mock" ]]; then
        default_distro="$(
            wsl.exe -l 2>/dev/null \
                | iconv -f UTF-16LE -t UTF-8 2>/dev/null \
                | tr -d '\0\r' \
                | awk '/\*/ { for (i=1;i<=NF;i++) if ($i!="*" && $i!~/^docker-desktop(-data)?$/) { print $i; exit } }' \
                || true
        )"
        if [[ -z "$default_distro" ]]; then
            default_distro="$(wsl.exe -l -q 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF && $0 !~ /^docker-desktop(-data)?$/ {print; exit}' || true)"
        fi
    fi
    local resolved_line
    while IFS= read -r resolved_line; do
        case "$resolved_line" in
            enable_default=*) enable_default="${resolved_line#enable_default=}" ;;
            integrated_csv=*) integrated_csv="${resolved_line#integrated_csv=}" ;;
        esac
    done < <(sidar_resolve_wsl_integration_fields)

    if [[ -z "$enable_default" && -z "$integrated_csv" ]]; then
        warn "Docker settings.json okunamadı veya tanınmayan şemada; runtime durumuna güveniliyor."
        export WSL_INTEGRATION_AUTOFIX_ELIGIBLE=false
        [[ "$_had_errexit" == true ]] && set -e
        return 0
    fi

    integrated_norm=",${integrated_csv// /},"
    [[ "$integrated_norm" == *",$current_distro,"* ]] && in_integrated=true
    if [[ "${enable_default,,}" == "true" && -n "$default_distro" && "$default_distro" == "$current_distro" ]]; then
        default_covers=true
    fi

    info "WSL Integration raporu: distro='${current_distro}', default='${default_distro:-bilinmiyor}', default-toggle='${enable_default:-bilinmiyor}', explicit-list='${integrated_csv:-boş}'."

    if [[ "$in_integrated" == true ]]; then
        ok "Docker Desktop WSL Integration: '${current_distro}' explicit toggle açık."
    elif [[ "$default_covers" == true ]]; then
        if [[ "${WSL_INTEGRATION_HARDEN_EXPLICIT:-true}" == "true" ]]; then
            info "Docker Desktop default-distro toggle '${current_distro}' dağıtımını şu an kapsıyor. Gereksiz restart/autofix riskini azaltmak için preflight yalnızca uygunluk işaretlemesi yapacak; explicit hardening Docker daemon kontrol aşamasına bırakıldı."
            export WSL_INTEGRATION_AUTOFIX_ELIGIBLE=true
        else
            warn "Docker Desktop WSL Integration: explicit toggle kapalı, default-distro toggle ile kapsanıyor. Default distro değişirse kırılabilir. (WSL_INTEGRATION_HARDEN_EXPLICIT=true ile otomatik düzeltilebilir.)"
        fi
    else
        export WSL_INTEGRATION_AUTOFIX_ELIGIBLE=true
        warn "Docker Desktop WSL Integration: '${current_distro}' kapsanmıyor görünüyor. Docker Desktop > Settings > Resources > WSL Integration altında explicit toggle açılmalı."
        if docker info >/dev/null 2>&1 || [[ -S /var/run/docker.sock ]]; then
            ok "Docker daemon zaten yanıt veriyor; settings.json okunamasa da WSL Integration runtime düzeyinde çalışıyor. Preflight autofix atlandı."
            export WSL_INTEGRATION_AUTOFIX_ELIGIBLE=false
            [[ "$_had_errexit" == true ]] && set -e
            return 0
        fi
        if declare -F apply_wsl_integration_autofix >/dev/null 2>&1; then
            info "Preflight aşamasında erken autofix denemesi başlatılıyor: '${current_distro}'."
            if apply_wsl_integration_autofix "$current_distro"; then
                export _DOCKER_DESKTOP_AUTOFIX_RESTARTED_AT
                _DOCKER_DESKTOP_AUTOFIX_RESTARTED_AT="$(date +%s)"
                ok "Preflight autofix: Docker Desktop WSL Integration '${current_distro}' için etkinleştirildi."
            else
                if [[ "${WSL_INTEGRATION_RESTART_REQUIRED:-false}" == "true" || -f "${TMPDIR:-/tmp}/sidar_wsl_integration_restart_required" ]]; then
                    fail "Docker Desktop WSL Integration ayarı yazıldı; socket mount'un yeni oturuma enjekte edilmesi için Windows PowerShell'de 'wsl --shutdown' çalıştırın, Ubuntu'yu yeniden açın ve install_sidar.sh komutunu tekrar başlatın."
                fi
                warn "Preflight autofix tamamlanamadı; Docker daemon kontrol aşamasında tekrar denenecek."
            fi
        else
            info "Preflight autofix yardımcı fonksiyonu bu bağlamda yüklü değil; düzeltme Docker daemon kontrol aşamasına devredildi."
        fi
    fi

    [[ "$_had_errexit" == true ]] && set -e
}
