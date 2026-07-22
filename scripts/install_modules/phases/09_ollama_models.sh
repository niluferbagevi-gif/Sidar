#!/usr/bin/env bash
set -Eeuo pipefail
# Sidar installer phase: Ollama model runtime defaults and provisioning helpers.

normalize_ollama_base_url() {
    local raw="${1:-}"
    local normalized="$raw"

    normalized="${normalized%/}"
    normalized="${normalized%/api}"
    if [[ -z "$normalized" ]]; then
        echo "http://localhost:11434"
        return
    fi
    if [[ "$normalized" != http://* && "$normalized" != https://* ]]; then
        normalized="http://$normalized"
    fi
    echo "$normalized"
}

resolve_ollama_base_url() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local detected="${OLLAMA_BASE_URL:-}"

    if [[ -z "$detected" ]]; then
        detected="${OLLAMA_HOST:-}"
    fi
    if [[ -z "$detected" && -f "$env_file" ]]; then
        detected=$(read_env_value_from_file "OLLAMA_BASE_URL" "$env_file")
    fi
    if [[ -z "$detected" && -f "$env_file" ]]; then
        detected=$(read_env_value_from_file "OLLAMA_HOST" "$env_file")
    fi

    normalize_ollama_base_url "$detected"
}

resolve_ollama_version_url() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local base_url
    base_url=$(resolve_ollama_base_url "$env_file")
    echo "${base_url}/api/version"
}

is_local_ollama_url() {
    local url="$1"
    [[ "$url" == http://localhost:* || "$url" == https://localhost:* || "$url" == http://127.0.0.1:* || "$url" == https://127.0.0.1:* ]]
}

wait_for_ollama_api_ready() {
    local version_url="$1"
    local max_wait_seconds="${2:-10}"
    local poll_interval_seconds="${3:-1}"
    local elapsed=0

    while (( elapsed < max_wait_seconds )); do
        if curl -sf "$version_url" &>/dev/null; then
            return 0
        fi
        sleep "$poll_interval_seconds"
        elapsed=$((elapsed + poll_interval_seconds))
    done

    return 1
}

check_host_ollama_healthy() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local version_url=""
    version_url=$(resolve_ollama_version_url "$env_file")
    curl -sf "$version_url" >/dev/null 2>&1
}

log_host_ollama_runtime_diagnostics() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local base_url=""
    local host=""

    base_url=$(resolve_ollama_base_url "$env_file")
    host="${base_url#http://}"
    host="${host#https://}"
    host="${host%%/*}"
    host="${host%%:*}"

    info "Host Ollama çalışma tanısı toplanıyor (GPU kullanımı opsiyonel kontrol)."
    local ollama_ps_reports_gpu=false

    if command -v ollama &>/dev/null; then
        if ollama ps >/tmp/sidar_ollama_ps.log 2>&1; then
            info "Host Ollama modelleri (ollama ps):"
            sed 's/^/       /' /tmp/sidar_ollama_ps.log
            if awk 'NR==1 {for (i=1;i<=NF;i++) if ($i=="PROCESSOR") c=i; next} c && toupper($c) ~ /GPU/ {found=1} END {exit !found}' /tmp/sidar_ollama_ps.log; then
                ollama_ps_reports_gpu=true
                info "ollama ps PROCESSOR sütunu GPU gösteriyor; host Ollama GPU üzerinde çalışıyor."
            fi
        else
            warn "ollama ps komutu çalıştırılamadı; host Ollama GPU durumu CLI üzerinden doğrulanamadı."
        fi
    else
        warn "ollama CLI bulunamadı; host Ollama GPU kullanımı için ollama ps çıktısı alınamadı."
    fi

    if [[ -z "$host" || "$host" == "localhost" || "$host" == "127.0.0.1" ]]; then
        local smi_cmd=""
        if command -v nvidia-smi &>/dev/null; then
            smi_cmd="nvidia-smi"
        elif command -v nvidia-smi.exe &>/dev/null; then
            smi_cmd="nvidia-smi.exe"
        fi

        if [[ "$WSL2" == true ]]; then
            info "WSL2: ollama ps doğrulaması yeterli; nvidia-smi compute-apps sorgusu atlandı."
        elif [[ "$ollama_ps_reports_gpu" == true ]]; then
            info "GPU kullanımı ollama ps ile doğrulandı; nvidia-smi compute-apps sorgusu atlandı."
        elif [[ -n "$smi_cmd" ]]; then
            if "$smi_cmd" --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader,nounits >/tmp/sidar_ollama_gpu_apps.log 2>&1; then
                if awk -F, 'tolower($2) ~ /ollama/ {found=1} END {exit !found}' /tmp/sidar_ollama_gpu_apps.log; then
                    info "nvidia-smi üzerinde Ollama süreçleri (PID, süreç, VRAM MiB):"
                    awk -F, 'tolower($2) ~ /ollama/ {gsub(/^ +| +$/, "", $1); gsub(/^ +| +$/, "", $2); gsub(/^ +| +$/, "", $3); printf "       %s, %s, %s MiB\n", $1, $2, $3}' /tmp/sidar_ollama_gpu_apps.log
                else
                    warn "nvidia-smi çalıştı ancak Ollama süreci görünmedi; host Ollama CPU modunda olabilir."
                fi
            else
                warn "nvidia-smi compute-apps sorgusu başarısız; host Ollama GPU süreci doğrulanamadı."
            fi
        else
            info "nvidia-smi bulunamadı; host Ollama GPU süreci doğrulaması atlandı."
        fi
    else
        info "Host Ollama uzak bir adreste (${base_url}); yerel nvidia-smi ile GPU süreci doğrulaması atlandı."
    fi
}


# ── 11. Ollama modelleri ─────────────────────────────────────────────────────

SIDAR_OLLAMA_DEFAULT_NUM_CTX="${SIDAR_OLLAMA_DEFAULT_NUM_CTX:-8192}"
SIDAR_OLLAMA_DEFAULT_NUM_BATCH="${SIDAR_OLLAMA_DEFAULT_NUM_BATCH:-2048}"

# Runtime-setting yardımcıları (sidar_ollama_positive_int_or_default,
# sidar_ollama_read_runtime_setting, sidar_ollama_runtime_num_ctx,
# sidar_ollama_runtime_num_batch, sidar_ollama_export_runtime_defaults)
# scripts/install_modules/utils/ollama_models.sh içinden yüklenir. Bu modül
# utils/ollama_models.sh'ten SONRA source edildiğinden burada yeniden
# tanımlamak, utils'teki (telemetri kaydı içeren ve bats ile test edilen)
# tanımları sessizce gölgeler; utils'i tek doğruluk kaynağı olarak koruyun.

run_coding_model_smoke_prompt() {
    local model_name="${1:-}"
    local ollama_base_url="${2:-}"
    local response_file=""
    local response_text=""
    local env_file="$SCRIPT_DIR/.env"
    local ollama_num_ctx=""
    local ollama_num_batch=""
    local payload_file=""

    [[ -n "$model_name" ]] || model_name="qwen2.5-coder:7b"
    [[ -n "$ollama_base_url" ]] || ollama_base_url="http://localhost:11434"
    response_file=$(mktemp)
    payload_file=$(mktemp)
    ollama_num_ctx=$(sidar_ollama_runtime_num_ctx "$env_file")
    ollama_num_batch=$(sidar_ollama_runtime_num_batch "$env_file")

    python3 - "$payload_file" "$model_name" "$ollama_num_ctx" "$ollama_num_batch" <<'PYSMOKEPAYLOAD'
import json
import sys

path, model, num_ctx, num_batch = sys.argv[1:5]
payload = {
    "model": model,
    "prompt": 'Return exactly this JSON and nothing else: {"sidar_smoke": true}',
    "stream": False,
    "format": "json",
    "options": {"num_ctx": int(num_ctx), "num_batch": int(num_batch)},
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PYSMOKEPAYLOAD

    info "Coding model JSON smoke testi çalışıyor (${model_name}, num_ctx=${ollama_num_ctx}, num_batch=${ollama_num_batch})..."
    if ! curl -fsS --max-time 75 \
        -H 'Content-Type: application/json' \
        --data-binary "@${payload_file}" \
        "${ollama_base_url%/}/api/generate" > "$response_file"; then
        rm -f "$response_file" "$payload_file"
        fail "Coding model JSON smoke testi başarısız: Ollama generate çağrısı yanıt vermedi (${model_name})."
    fi
    rm -f "$payload_file"

    response_text=$(python3 - "$response_file" <<'PYSMOKE' 2>/dev/null || true
import json
import sys
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
print(payload.get("response", ""))
PYSMOKE
)
    rm -f "$response_file"

    if ! python3 - "$response_text" <<'PYJSON' >/dev/null 2>&1
import json
import sys
parsed = json.loads(sys.argv[1])
raise SystemExit(0 if parsed.get("sidar_smoke") is True else 1)
PYJSON
    then
        fail "Coding model JSON smoke testi başarısız: model geçerli JSON çıktı üretmedi. Yanıt: ${response_text:0:200}"
    fi

    ok "Coding model JSON smoke testi başarılı (${model_name})."
}


# download_ollama_models() scripts/install_modules/utils/ollama_models.sh
# içinden yüklenir (pull telemetrisi + bats ile test edilen
# sidar_ollama_count_models_from_tags/sidar_ollama_model_exists_in_tags
# eşleştirme yardımcılarını kullanan tek doğruluk kaynağı). Burada yeniden
# tanımlamayın; utils sürümünü sessizce gölgeler ve telemetri artefaktının
# hiç üretilmemesine yol açar.
