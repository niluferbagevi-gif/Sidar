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

sidar_ollama_positive_int_or_default() {
    local raw="${1:-}"
    local default_value="${2:-}"
    if [[ "$raw" =~ ^[0-9]+$ ]] && (( raw > 0 )); then
        printf '%s\n' "$raw"
    else
        printf '%s\n' "$default_value"
    fi
}

sidar_ollama_read_runtime_setting() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    local primary_key="${2:-}"
    local fallback_key="${3:-}"
    local default_value="${4:-}"
    local raw=""

    if [[ -n "$primary_key" ]]; then
        raw="${!primary_key:-}"
        if [[ -z "$raw" && -f "$env_file" ]]; then
            raw=$(read_env_value_from_file "$primary_key" "$env_file")
        fi
    fi
    if [[ -z "$raw" && -n "$fallback_key" ]]; then
        raw="${!fallback_key:-}"
        if [[ -z "$raw" && -f "$env_file" ]]; then
            raw=$(read_env_value_from_file "$fallback_key" "$env_file")
        fi
    fi

    sidar_ollama_positive_int_or_default "$raw" "$default_value"
}

sidar_ollama_runtime_num_ctx() {
    sidar_ollama_read_runtime_setting "${1:-$SCRIPT_DIR/.env}" "OLLAMA_NUM_CTX" "OLLAMA_CODING_NUM_CTX" "$SIDAR_OLLAMA_DEFAULT_NUM_CTX"
}

sidar_ollama_runtime_num_batch() {
    sidar_ollama_read_runtime_setting "${1:-$SCRIPT_DIR/.env}" "OLLAMA_NUM_BATCH" "" "$SIDAR_OLLAMA_DEFAULT_NUM_BATCH"
}

sidar_ollama_export_runtime_defaults() {
    local env_file="${1:-$SCRIPT_DIR/.env}"
    OLLAMA_NUM_CTX="$(sidar_ollama_runtime_num_ctx "$env_file")"
    OLLAMA_NUM_BATCH="$(sidar_ollama_runtime_num_batch "$env_file")"
    export OLLAMA_NUM_CTX
    export OLLAMA_NUM_BATCH
    info "Ollama runtime context varsayılanları: OLLAMA_NUM_CTX=${OLLAMA_NUM_CTX}, OLLAMA_NUM_BATCH=${OLLAMA_NUM_BATCH}."
}

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

download_ollama_models() {
    step "Ollama Modelleri Hazırlanıyor"
    local estimated_size_gb="~14.8 GB"
    local temp_ollama_pid=""
    local ollama_tags_url=""
    local tags_payload=""
    local existing_model_count=0
    local env_file="$SCRIPT_DIR/.env"
    local missing_required_models=""
    local resolved_models_csv=""
    local should_prompt_for_download=true
    local -a models_to_pull=()
    local -a models=()
    _count_ollama_models_from_tags() {
        local payload="$1"
        if command -v python3 &>/dev/null; then
            python3 - "$payload" <<'PY' 2>/dev/null || echo "0"
import json
import sys
raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    data = json.loads(raw)
except Exception:
    print("0")
    raise SystemExit(0)
models = data.get("models")
if isinstance(models, list):
    print(str(sum(1 for m in models if isinstance(m, dict) and m.get("name"))))
else:
    print("0")
PY
        else
            printf "%s" "$payload" | grep -o '"name"[[:space:]]*:' | wc -l | tr -d '[:space:]'
        fi
    }
    _model_exists_in_tags() {
        local payload="$1"
        local model_name="$2"
        if [[ -z "$payload" || -z "$model_name" ]]; then
            return 1
        fi
        if command -v python3 &>/dev/null; then
            python3 - "$payload" "$model_name" <<'PY' >/dev/null 2>&1
import json
import sys

raw = sys.argv[1] if len(sys.argv) > 1 else ""
target = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
if not target:
    raise SystemExit(1)
try:
    data = json.loads(raw)
except Exception:
    raise SystemExit(1)
models = data.get("models")
if not isinstance(models, list):
    raise SystemExit(1)
names = {m.get("name") for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)}
if target in names:
    raise SystemExit(0)
# Kullanıcı modeli etiketsiz verdiyse Ollama'da sık görülen :latest eşleşmesini de kabul et.
if ":" not in target and f"{target}:latest" in names:
    raise SystemExit(0)
raise SystemExit(1)
PY
            return $?
        fi

        if printf "%s" "$payload" | grep -q "\"name\"[[:space:]]*:[[:space:]]*\"${model_name}\""; then
            return 0
        fi
        if [[ "$model_name" != *:* ]] && printf "%s" "$payload" | grep -q "\"name\"[[:space:]]*:[[:space:]]*\"${model_name}:latest\""; then
            return 0
        fi
        return 1
    }
    # shellcheck disable=SC2317  # trap RETURN ile dolaylı çağrılır.
    cleanup_temp_ollama() {
        if [[ -n "${temp_ollama_pid:-}" ]] && kill -0 "${temp_ollama_pid:-}" >/dev/null 2>&1; then
            info "Geçici ollama serve süreci sonlandırılıyor (PID: ${temp_ollama_pid:-})..."
            kill "${temp_ollama_pid:-}" >/dev/null 2>&1 || true
            # Sürecin tamamen kapanmasını bekle; böylece 11434 portu Docker Ollama
            # servisi başlamadan önce işletim sistemi tarafından serbest bırakılır.
            local _i
            for _i in {1..10}; do
                kill -0 "${temp_ollama_pid:-}" >/dev/null 2>&1 || break
                sleep 1
            done
        fi
    }
    trap cleanup_temp_ollama RETURN

    if [[ "$WSL2" == true && "$WSLCONFIG_CHANGED" == true ]]; then
        warn "WSL2 .wslconfig bu kurulumda güncellendi; yeni memory/swap limitleri henüz etkin değil."
        info "Model indirme işlemleri güvenlik için ertelendi. Önce Windows PowerShell'de şunu çalıştırın:"
        echo "  wsl --shutdown"
        info "Ardından dağıtımı yeniden açıp modelleri indirmek için tekrar çalıştırın: ./install_sidar.sh --download-models"
        return
    fi

    if [[ "$SKIP_MODELS" == true ]]; then
        info "--skip-models bayrağı verildi, model indirmeleri atlanıyor."
        return
    fi

    OLLAMA_VERSION_URL=$(resolve_ollama_version_url "$SCRIPT_DIR/.env")
    OLLAMA_BASE_URL="${OLLAMA_VERSION_URL%/api/version}"
    ollama_tags_url="${OLLAMA_BASE_URL}/api/tags"
    sidar_ollama_export_runtime_defaults "$env_file"

    if [[ ! -f "$env_file" ]]; then
        warn ".env bulunamadı, varsayılan modeller indirilemedi."
        return
    fi

    TEXT_MOD=$(read_env_value_from_file "TEXT_MODEL" "$env_file")
    CODE_MOD=$(read_env_value_from_file "CODING_MODEL" "$env_file")
    VISION_MOD=$(read_env_value_from_file "VISION_MODEL" "$env_file")
    MULTIMODAL=$(read_env_value_from_file "ENABLE_MULTIMODAL" "$env_file")

    if [[ -z "$TEXT_MOD" ]]; then
        TEXT_MOD="llama3.1:8b"
        warn "TEXT_MODEL boş/geçersiz görünüyor, varsayılan kullanılacak: $TEXT_MOD"
    fi
    if [[ -z "$CODE_MOD" ]]; then
        CODE_MOD="qwen2.5-coder:7b"
        warn "CODING_MODEL boş/geçersiz görünüyor, varsayılan kullanılacak: $CODE_MOD"
    fi
    models=("$TEXT_MOD" "$CODE_MOD" "nomic-embed-text")
    if [[ "${MULTIMODAL,,}" == "true" && -n "$VISION_MOD" ]]; then
        models+=("$VISION_MOD")
    fi

    # Etkileşimli "indirilsin mi?" sorusundan önce mevcut model adlarını doğrula.
    # Sadece sayıya göre değil, projede gereken model adlarına göre karar ver.
    if command -v ollama &>/dev/null; then
        tags_payload=$(curl -sf "$ollama_tags_url" 2>/dev/null || true)
        if [[ -n "$tags_payload" ]]; then
            existing_model_count=$(_count_ollama_models_from_tags "$tags_payload")
            for model in "${models[@]}"; do
                [[ -n "$model" ]] || continue
                if _model_exists_in_tags "$tags_payload" "$model"; then
                    continue
                fi
                models_to_pull+=("$model")
            done

            if (( ${#models_to_pull[@]} == 0 )); then
                ok "Ollama üzerinde ${existing_model_count} model mevcut ve gerekli modeller zaten yüklü (${ollama_tags_url})."
                run_coding_model_smoke_prompt "$CODE_MOD" "$OLLAMA_BASE_URL"
                return
            fi

            if [[ "$DOWNLOAD_MODELS" != true ]]; then
                missing_required_models=$(IFS=', '; echo "${models_to_pull[*]}")
                warn "Ollama'da model(ler) eksik: ${missing_required_models}. Sadece eksik modeller indirilecek."
                should_prompt_for_download=false
            fi
        fi
    fi

    if [[ "$DOWNLOAD_MODELS" != true && "$should_prompt_for_download" == true ]]; then
        if [[ "$NO_INTERACTION" == true ]]; then
            info "--ci/--no-interaction etkin ve --download-models verilmedi: model indirmeleri atlanıyor (${estimated_size_gb})."
            info "Model indirmek için: ./install_sidar.sh --download-models"
            return
        fi
        reply=$(prompt_yes_no_with_timeout_default_yes "Modeller indirilecek (${estimated_size_gb}). Devam edilsin mi? [E/h] ")
        case "${reply:-E}" in
            [HhNn]*)
                info "Model indirmesi kullanıcı tercihiyle atlandı."
                return
                ;;
        esac
    fi

    if ! command -v ollama &>/dev/null; then
        warn "Ollama bulunamadı, model indirme atlanıyor."
        return
    fi

    if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
        info "Ollama API erişilemedi (${OLLAMA_VERSION_URL})."
        if is_local_ollama_url "$OLLAMA_BASE_URL"; then
            info "Yerel Ollama servisi başlatma deneniyor..."
            if command -v systemctl &>/dev/null && command -v sudo &>/dev/null; then
                sudo systemctl enable --now ollama >/dev/null 2>&1 || true
            fi
            # systemd yoksa veya servis ayağa kalkmadıysa son çare olarak geçici süreç başlat.
            if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
                info "systemd ile Ollama doğrulanamadı, geçici 'ollama serve' süreci başlatılıyor..."
                env OLLAMA_NUM_CTX="$OLLAMA_NUM_CTX" OLLAMA_NUM_BATCH="$OLLAMA_NUM_BATCH" ollama serve >/dev/null 2>&1 &
                temp_ollama_pid=$!
            fi
            for _ in {1..12}; do
                if curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
                    break
                fi
                sleep 5
            done
        else
            warn "Uzak Ollama endpoint'i tespit edildi (${OLLAMA_BASE_URL}). Otomatik servis başlatma atlandı."
        fi
    fi

    if ! curl -sf "$OLLAMA_VERSION_URL" &>/dev/null; then
        warn "Ollama servisi doğrulanamadı (${OLLAMA_VERSION_URL}), model indirme atlanıyor."
        return
    fi

    if (( ${#models_to_pull[@]} == 0 )); then
        models_to_pull=("${models[@]}")
    fi

    resolved_models_csv=$(IFS=', '; echo "${models_to_pull[*]}")
    info "İndirilecek model listesi: ${resolved_models_csv}"
    info "Not: Ollama katmanlı blob indirdiği için yüzde veya hız göstergesi kısa süreli gerileyebilir/dalgalanabilir; bu tek başına hata değildir."

    for model in "${models_to_pull[@]}"; do
        if [[ -n "$model" ]]; then
            info "-> $model indiriliyor (bu işlem zaman alabilir)..."
            local pull_success=false
            local pull_log=""
            pull_log="$(mktemp -t sidar_ollama_pull.XXXXXX)"
            for attempt in 1 2 3; do
                if ollama pull "$model" > >(tee -a "$pull_log") 2> >(tee -a "$pull_log" >&2); then
                    pull_success=true
                    break
                fi
                warn "Model indirme denemesi başarısız (${model}) [${attempt}/3]."
                if [[ "$attempt" -lt 3 ]]; then
                    local backoff=$((attempt * 5))
                    info "${backoff}s sonra yeniden denenecek..."
                    sleep "$backoff"
                fi
            done

            if [[ "$pull_success" != true ]]; then
                warn "Son ollama pull çıktısı (${model}, son 20 satır):"
                tail -n 20 "$pull_log" >&2 || true
                info "Manuel indirme: OLLAMA_HOST='${OLLAMA_BASE_URL}' ollama pull '${model}'"
                info "Manuel doğrulama: curl -sf '${ollama_tags_url}' | grep -F '\"name\":\"${model}\"'"
                rm -f "$pull_log"
                fail "Model indirilemedi: ${model} (3 deneme sonrası başarısız)."
            fi
            rm -f "$pull_log"
        fi
    done

    run_coding_model_smoke_prompt "$CODE_MOD" "$OLLAMA_BASE_URL"
    ok "Gerekli tüm modeller başarıyla hazırlandı ve doğrulandı."
}
