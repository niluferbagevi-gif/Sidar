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

# _sidar_ollama_smoke_attempt() sabit bir num_ctx/num_batch çifti ile TEK bir
# smoke isteği yollar. Çağıran `$(...)` ile çalıştırdığından (alt kabuk) bir
# global değişkene yazmak yerine, sonucu STDOUT'a iki satır olarak basar:
# birinci satır HTTP durum kodu, ikinci satır yanıt gövdesinin yazıldığı
# geçici dosyanın yolu (çağıran temizlemekten sorumludur). `-f` yerine `-w
# '%{http_code}'` kullanır ki 500 gibi HTTP hataları curl'ü "başarısız"
# yapıp gövdeyi kaybetmesin; asıl VRAM OOM teşhisi bu gövdeye bakarak yapılır.
#
# curl's own failure (network error, non-2xx swallowed by our own past `-f`
# use, ...) must never propagate as a hard shell error here: this function
# is meant to fail *soft* into the "000"/non-200 handling below. Bash's ERR
# trap (install_sidar.sh sets `set -Eeuo pipefail` + `trap ... ERR`) fires
# for a failing command's execution independently of that outcome ever
# reaching this function's own (always-zero, via printf) exit status - the
# fix is entirely at the CALL SITE: every caller of this function (and of
# the other uv/curl-shelling helpers below) MUST invoke it from an
# if/&&/||-guarded context (e.g. `out=$(fn) || true`), never bare. See the
# call sites in run_coding_model_smoke_prompt().
_sidar_ollama_smoke_attempt() {
    local model_name="$1"
    local ollama_base_url="$2"
    local num_ctx="$3"
    local num_batch="$4"
    local payload_file response_file http_status curl_exit

    payload_file=$(mktemp)
    response_file=$(mktemp)

    python3 - "$payload_file" "$model_name" "$num_ctx" "$num_batch" <<'PYSMOKEPAYLOAD'
import json
import sys

path, model, num_ctx, num_batch = sys.argv[1:5]
# core/llm/ollama.py's real chat() call only sets num_ctx/num_batch when
# they resolve to a positive value (0/negative means "let Ollama use its
# own default" - see config_llm.OLLAMA_BATCH_POLICY.auto_batch_for_context).
# Mirror that here so the smoke test sends the exact same options shape.
options = {}
num_ctx_int = int(num_ctx)
num_batch_int = int(num_batch)
if num_ctx_int > 0:
    options["num_ctx"] = num_ctx_int
if num_batch_int > 0:
    options["num_batch"] = num_batch_int
payload = {
    "model": model,
    "prompt": 'Return exactly this JSON and nothing else: {"sidar_smoke": true}',
    "stream": False,
    "format": "json",
    "options": options,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PYSMOKEPAYLOAD

    http_status=$(curl -sS --max-time 75 -o "$response_file" -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        --data-binary "@${payload_file}" \
        "${ollama_base_url%/}/api/generate" 2>/dev/null)
    curl_exit=$?
    rm -f "$payload_file"

    if [[ -z "$http_status" || "$curl_exit" -ne 0 ]]; then
        http_status="000"
    fi
    printf '%s\n%s\n' "$http_status" "$response_file"
}

# _sidar_ollama_body_contains_oom_marker() core/llm_client.py'nin
# _OOM_MARKERS listesini (Python istemcisindeki OOM tespitinin tek doğruluk
# kaynağı) $1'deki Ollama yanıt gövdesine karşı kontrol eder.
#
# Review bulgusu (d): OOM tespiti core/llm_client.py::_is_oom_error() içinde
# zaten çözülmüş bir problemken, kurulum betiği kendi ayrı, driftlenebilir
# bir anahtar kelime listesi tutuyordu ve curl -f eski hâliyle Ollama'nın
# döndürdüğü asıl hata metnini (`{"error": "..."}`) sessizce atıyordu, bu
# yüzden bu kontrolü hiç yapamıyordu. `_sidar_ollama_smoke_attempt` artık
# gövdeyi -o ile diske yazıyor (curl -f kullanmıyor); bu fonksiyon o gövdeyi
# Python'un `_text_contains_oom_marker()`'ına soruyor.
#
# Çıkış kodu: 0 = eşleşme var, 1 = kesin eşleşme yok. uv/python
# yoksa/import başarısız olursa (2), tek doğruluk kaynağından bağımsız, dar
# bir bash anahtar kelime kontrolüne düşülür — kurulum bu adımda asla
# kilitlenmemeli.
#
# Bu fonksiyon yalnızca korumalı bir bağlamdan (if/&&/|| koşulu) çağrılmalı
# - bkz. _sidar_ollama_smoke_attempt üstündeki not; aynı ERR trap/`set -e`
# gerekçesi burada da geçerli.
_sidar_ollama_body_contains_oom_marker() {
    local response_file="$1"
    local py_exit
    local body=""

    [[ -f "$response_file" ]] || return 1

    (cd "$SCRIPT_DIR" && uv run python - "$response_file" <<'PY_OOM_MARKER_CHECK' 2>/dev/null
import sys

try:
    from core.llm_client import _text_contains_oom_marker

    with open(sys.argv[1], encoding="utf-8", errors="replace") as handle:
        text = handle.read()
except Exception:
    raise SystemExit(2)
raise SystemExit(0 if _text_contains_oom_marker(text) else 1)
PY_OOM_MARKER_CHECK
    )
    py_exit=$?

    case "$py_exit" in
        0) return 0 ;;
        1) return 1 ;;
    esac

    body="$(tr '[:upper:]' '[:lower:]' < "$response_file" 2>/dev/null || true)"
    # "cuda" is intentionally the broad catch-all here (it already covers
    # "cuda out of memory", "cudamalloc failed", etc. as substrings, so
    # listing those separately would be dead/unreachable alternation per the
    # static analyzer's pattern-overlap check).
    case "$body" in
        *"out of memory"*|*"cuda"*|*"insufficient memory"*|*"more system memory"*|*"failed to allocate"*|*"not enough memory"*)
            return 0
            ;;
    esac
    return 1
}

# _sidar_ollama_smoke_looks_like_vram_pressure() bir smoke denemesinin GPU
# VRAM baskısı (OOM) yüzünden başarısız olmuş olabileceğini tahmin eder; bu
# yalnızca "ikinci, daha düşük context'li deneme mantıklı mı" sorusuna karar
# vermek için kullanılır, kesin teşhis değildir.
#
# HTTP 500 tek başına yeterli sayılır: core/llm_client.py'nin kendi
# _is_retryable_exception() yorumu Ollama'nın VRAM OOM'unu tipik olarak
# gövdesiz/opak bir 500 olarak döndürdüğünü belgeliyor (ör. yalnızca
# `{"error": "an error was encountered while running the model"}`) — bu
# yüzden 500'de gövde eşleşmesi şart koşulmuyor. 502/503 (proxy/gateway) ve
# 000 (bağlantı koptu) Ollama'ya özgü bir OOM sinyali değil; bunlar için
# gövdede açık bir OOM işareti aranıyor.
_sidar_ollama_smoke_looks_like_vram_pressure() {
    local http_status="$1"
    local response_file="$2"

    case "$http_status" in
        500)
            return 0
            ;;
        502|503|000)
            _sidar_ollama_body_contains_oom_marker "$response_file"
            ;;
        *)
            return 1
            ;;
    esac
}

# _sidar_ollama_oom_remediation_hint() core/llm_client.py'nin
# OOM_REMEDIATION_HINT sabitini STDOUT'a basar — kurulum zamanı ve runtime
# OOM tavsiyesi aynı metni göstersin diye (review bulgusu (d)). uv/python
# yoksa veya import başarısız olursa boş çıktı ile başarısız döner; çağıran
# kendi install-time tavsiyesine düşer.
#
# Yalnızca korumalı bir bağlamdan çağrılmalı (bkz. _sidar_ollama_smoke_attempt
# üstündeki not).
_sidar_ollama_oom_remediation_hint() {
    (cd "$SCRIPT_DIR" && uv run python - <<'PY_OOM_HINT' 2>/dev/null
import io
import os
import sys

os.environ.setdefault("SIDAR_CONFIG_QUIET", "true")
_real_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    from core.llm_client import OOM_REMEDIATION_HINT
except Exception:
    sys.stdout = _real_stdout
    raise SystemExit(1)
sys.stdout = _real_stdout
print(OOM_REMEDIATION_HINT)
PY_OOM_HINT
    )
}

# _sidar_ollama_extract_error_snippet() Ollama'nın yanıt gövdesinden okunabilir
# bir hata metni çıkarır: JSON ise `error` alanını, değilse ham metni (ilk 300
# karakter) döndürür. Sadece stdlib kullandığından `uv run python` yerine düz
# `python3` yeterli (bu dosyadaki diğer JSON ayrıştırma bloklarıyla tutarlı).
_sidar_ollama_extract_error_snippet() {
    local response_file="$1"
    [[ -f "$response_file" ]] || return 0
    python3 - "$response_file" <<'PY_ERROR_SNIPPET' 2>/dev/null
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as handle:
        raw = handle.read()
except OSError:
    raw = ""
text = raw.strip()
if text:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    else:
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
            text = parsed["error"]
print(text[:300])
PY_ERROR_SNIPPET
}

run_coding_model_smoke_prompt() {
    local model_name="${1:-}"
    local ollama_base_url="${2:-}"
    local response_file=""
    local response_text=""
    local env_file="$SCRIPT_DIR/.env"
    local ollama_num_ctx=""
    local ollama_num_batch=""
    local reduced_num_ctx=""
    local http_status=""
    local attempt_output=""
    local smoke_floor_ctx=2048
    local was_vram_pressure=false
    local error_snippet=""
    local oom_hint=""
    local fail_message=""

    [[ -n "$model_name" ]] || model_name="qwen2.5-coder:7b"
    [[ -n "$ollama_base_url" ]] || ollama_base_url="http://localhost:11434"
    ollama_num_ctx=$(sidar_ollama_runtime_num_ctx "$env_file")
    ollama_num_batch=$(sidar_ollama_runtime_num_batch "$env_file")

    info "Coding model JSON smoke testi çalışıyor (${model_name}, num_ctx=${ollama_num_ctx}, num_batch=${ollama_num_batch})..."
    # `|| true`: see the note above _sidar_ollama_smoke_attempt - a bare
    # `var=$(fn)` would let a failing curl inside fn trip the installer's
    # global ERR trap even though this is meant to fail soft into the
    # non-200 handling below.
    attempt_output=$(_sidar_ollama_smoke_attempt "$model_name" "$ollama_base_url" "$ollama_num_ctx" "$ollama_num_batch") || true
    http_status="${attempt_output%%$'\n'*}"
    response_file="${attempt_output#*$'\n'}"

    # Sınırdaki (~8 GiB) VRAM'li kartlarda config.py'nin otomatik seçtiği
    # context penceresi hiç payı olmadan GPU belleğini doldurabilir ve Ollama
    # `/api/generate` çağrısı HTTP 500 ile döner. Kör bir "fail" yerine, önce
    # daha düşük num_ctx ile tek seferlik bir kurtarma denemesi yap: başarılı
    # olursa OLLAMA_CODING_NUM_CTX'i .env'e kalıcı yaz (bir daha aynı hatayı
    # tekrarlayıp installer auto-heal'in "repeated-failure-signature" ile
    # erken durmasını önle); başarısız olursa kullanıcıya somut bir sonraki
    # adım söyle. num_batch bilerek DOKUNULMADAN bırakılıyor: core/llm/ollama.py
    # içindeki yorum, VRAM için num_batch'i küçültmenin daha önce
    # değerlendirilip reddedildiğini belgeliyor (num_batch'i küçültmek VRAM'i
    # azaltmaz, llama.cpp'nin `GGML_ASSERT(n_tokens_all <= cparams.n_batch)`
    # ile düşme riskini artırır); bu yüzden burada da yalnızca ctx (asıl KV
    # cache/VRAM maliyetini taşıyan değer) küçültülüyor.
    if [[ "$http_status" != "200" ]] \
        && _sidar_ollama_smoke_looks_like_vram_pressure "$http_status" "$response_file" \
        && (( ollama_num_ctx > smoke_floor_ctx )); then
        warn "Coding model JSON smoke testi ilk denemede başarısız oldu (HTTP ${http_status}, ${model_name}); GPU VRAM baskısına işaret ediyor olabilir."
        reduced_num_ctx=$(( ollama_num_ctx / 2 ))
        (( reduced_num_ctx >= smoke_floor_ctx )) || reduced_num_ctx="$smoke_floor_ctx"

        info "Daha düşük context ile tekrar deneniyor (num_ctx=${reduced_num_ctx}, num_batch=${ollama_num_batch} değişmedi)..."
        rm -f "$response_file"
        attempt_output=$(_sidar_ollama_smoke_attempt "$model_name" "$ollama_base_url" "$reduced_num_ctx" "$ollama_num_batch") || true
        http_status="${attempt_output%%$'\n'*}"
        response_file="${attempt_output#*$'\n'}"

        if [[ "$http_status" == "200" ]]; then
            sidar_write_env_value "$env_file" "OLLAMA_CODING_NUM_CTX" "$reduced_num_ctx"
            ok "Düşük VRAM'e uygun context ile smoke testi başarılı; .env dosyasına kalıcı yazıldı (OLLAMA_CODING_NUM_CTX=${reduced_num_ctx})."
            ollama_num_ctx="$reduced_num_ctx"
        fi
    fi

    if [[ "$http_status" != "200" ]]; then
        # Review bulgusu (d): eskiden curl -f Ollama'nın döndürdüğü asıl hata
        # metnini sessizce atıyordu ve OOM tespiti core/llm_client.py'de
        # zaten çözülmüşken burada hiç kullanılmıyordu. Artık gövdeyi
        # kullanıcıya gösteriyoruz ve OOM'a benziyorsa runtime'la AYNI
        # (core/llm_client.py::OOM_REMEDIATION_HINT) tavsiyeyi ekliyoruz.
        _sidar_ollama_smoke_looks_like_vram_pressure "$http_status" "$response_file" && was_vram_pressure=true
        # `|| true` below: these two helpers shell out to python3/uv, and a
        # bare `var=$(fn)` where fn's own risky command fails would trigger
        # install_sidar.sh's global ERR trap (set -Eeuo pipefail + trap ...
        # ERR) even though fn is designed to fail *soft* here — see the note
        # above _sidar_ollama_smoke_attempt. `|| true` puts the assignment in
        # an exempted (non-final `||` operand) context.
        error_snippet="$(_sidar_ollama_extract_error_snippet "$response_file")" || true
        rm -f "$response_file"

        fail_message="Coding model JSON smoke testi başarısız: Ollama generate çağrısı yanıt vermedi (${model_name}, HTTP ${http_status:-000})."
        [[ -n "$error_snippet" ]] && fail_message+=" Ollama hata metni: ${error_snippet}"

        if [[ "$was_vram_pressure" == true ]]; then
            oom_hint="$(_sidar_ollama_oom_remediation_hint)" || true
            [[ -n "$oom_hint" ]] || oom_hint="[GPU belleği yetersiz olabilir (OOM). OLLAMA_NUM_BATCH veya OLLAMA_CODING_NUM_CTX değerini düşürmeyi ya da eşzamanlı istek sayısını (OLLAMA_GPU_REQUEST_POOL_SIZE) azaltmayı deneyin.]"
            fail_message+=" ${oom_hint} .env dosyasında OLLAMA_CODING_NUM_CTX=2048 ayarlayıp kurulumu yeniden deneyin; ya da 'ollama ps'/'nvidia-smi' ile başka bir sürecin VRAM'i işgal etmediğini doğrulayın."
        fi
        fail "$fail_message"
    fi

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

    ok "Coding model JSON smoke testi başarılı (${model_name}, num_ctx=${ollama_num_ctx}, num_batch=${ollama_num_batch})."
}


# download_ollama_models() scripts/install_modules/utils/ollama_models.sh
# içinden yüklenir (pull telemetrisi + bats ile test edilen
# sidar_ollama_count_models_from_tags/sidar_ollama_model_exists_in_tags
# eşleştirme yardımcılarını kullanan tek doğruluk kaynağı). Burada yeniden
# tanımlamayın; utils sürümünü sessizce gölgeler ve telemetri artefaktının
# hiç üretilmemesine yol açar.
