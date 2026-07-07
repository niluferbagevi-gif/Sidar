#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_OLLAMA_MODELS_SH_LOADED=1

# Functional install helpers for the phase-based Sidar installer.
# These definitions intentionally override the legacy monolithic fallbacks in
# install_sidar.sh when sourced by the relevant phase module.

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

sidar_ollama_count_models_from_tags() {
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

sidar_ollama_model_exists_in_tags() {
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
            existing_model_count=$(sidar_ollama_count_models_from_tags "$tags_payload")
            for model in "${models[@]}"; do
                [[ -n "$model" ]] || continue
                if sidar_ollama_model_exists_in_tags "$tags_payload" "$model"; then
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
