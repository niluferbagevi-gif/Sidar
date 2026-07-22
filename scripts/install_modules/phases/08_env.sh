#!/usr/bin/env bash
set -Eeuo pipefail
# Sidar installer phase: .env and secret synchronization helpers.

# ── 10. .env dosyası ──────────────────────────────────────────────────────────

# Secret generation and DB credential hardening helpers live in scripts/install_modules/utils/env_secrets.sh.

# DATABASE_URL defaults and PostgreSQL dotenv sync helpers live in scripts/install_modules/utils/database_url.sh.

ensure_rag_vector_backend_pgvector() {
    local env_file="$1"
    local current_backend=""

    if [[ ! -f "$env_file" ]]; then
        return
    fi

    current_backend=$(read_env_value_from_file "RAG_VECTOR_BACKEND" "$env_file")
    if [[ -z "$current_backend" ]]; then
        echo "RAG_VECTOR_BACKEND=pgvector" >> "$env_file"
        ok ".env: RAG_VECTOR_BACKEND=pgvector eklendi."
        return
    fi

    if [[ "$current_backend" != "pgvector" ]]; then
        sed_inplace 's|^RAG_VECTOR_BACKEND=.*|RAG_VECTOR_BACKEND=pgvector|' "$env_file"
        ok ".env: RAG_VECTOR_BACKEND pgvector olarak güncellendi."
    fi
}

# Kurulum sırasında kullanıcıdan veya SIDAR_KEYS_FILE üzerinden alınan API
# anahtarları tek merkezden yönetilir. Bu liste .env, raporlama ve .env.*
# varyant senkronizasyonunda ortak kullanılarak .env.advanced gibi şablondan
# üretilen dosyalarda boş placeholder kalması engellenir.
#
# SIDAR_USER_SECRET_ENV_KEYS dizisi (tek doğruluk kaynağı) install_sidar.sh
# içinde, mask_install_log_stream()'in de kullandığı log maskeleme deseninin
# hemen yanında tanımlıdır. Burada ayrı bir liste tutmayın: iki allowlist'in
# elle senkron kalması gerektiği bir tasarım, yeni bir key eklendiğinde
# birinin unutulup secret'ın loglara sızmasına yol açar.
sidar_user_api_key_names() {
    printf '%s\n' "${SIDAR_USER_SECRET_ENV_KEYS[@]}"
}

# ── İnteraktif API Anahtarı Toplama ──────────────────────────────────────────
# Eksik API anahtarları için zenity (GUI) → whiptail (TUI) → read (fallback)
# sırasıyla denenir; kullanıcı anahtarları girdikten sonra kurulum devam eder.
collect_api_keys_interactive() {
    local env_file="$1"

    # ── Tüm kullanıcı girişi gerektiren anahtarlar (otomatik üretilenler hariç) ──
    local -a KEY_ORDER=()
    mapfile -t KEY_ORDER < <(sidar_user_api_key_names)
    local sidar_keys_file="${SIDAR_KEYS_FILE:-$HOME/.sidar_keys.env}"

    # Gruplar: "Başlık|KEY1,KEY2,..."  (her grup zenity'de ayrı form / whiptail'de bölüm)
    # NOT: GROUPS bash reserved değişkeni olduğundan API_GROUPS adı kullanılıyor.
    local -a API_GROUPS=(
        "AI Sağlayıcıları|OPENAI_API_KEY,GEMINI_API_KEY,ANTHROPIC_API_KEY,LITELLM_API_KEY,HF_TOKEN"
        "GitHub ve Web Arama|GITHUB_TOKEN,TAVILY_API_KEY,GOOGLE_SEARCH_API_KEY,GOOGLE_SEARCH_CX"
        "Slack|SLACK_TOKEN,SLACK_APP_LEVEL_TOKEN,SLACK_WEBHOOK_URL,SLACK_DEFAULT_CHANNEL"
        "Jira|JIRA_URL,JIRA_EMAIL,JIRA_TOKEN,JIRA_DEFAULT_PROJECT"
        "Microsoft Teams|TEAMS_WEBHOOK_URL"
    )

    _key_label() {
        case "$1" in
            OPENAI_API_KEY)        echo "OpenAI API Anahtarı" ;;
            GEMINI_API_KEY)        echo "Google Gemini API Anahtarı" ;;
            ANTHROPIC_API_KEY)     echo "Anthropic Claude API Anahtarı" ;;
            LITELLM_API_KEY)       echo "LiteLLM / OpenRouter API Anahtarı" ;;
            HF_TOKEN)              echo "HuggingFace Token" ;;
            GITHUB_TOKEN)          echo "GitHub Token (repo erişimi)" ;;
            TAVILY_API_KEY)        echo "Tavily Arama API Anahtarı" ;;
            GOOGLE_SEARCH_API_KEY) echo "Google Custom Search API Anahtarı" ;;
            GOOGLE_SEARCH_CX)      echo "Google Search Engine ID (cx)" ;;
            SLACK_TOKEN)           echo "Slack Bot OAuth Token (xoxb-...)" ;;
            SLACK_APP_LEVEL_TOKEN) echo "Slack App Level Token (xapp-...) [opt]" ;;
            SLACK_WEBHOOK_URL)     echo "Slack Incoming Webhook URL [opt]" ;;
            SLACK_DEFAULT_CHANNEL) echo "Slack Varsayılan Kanal (örn: #sidar)" ;;
            JIRA_URL)              echo "Jira URL (örn: https://sirket.atlassian.net)" ;;
            JIRA_EMAIL)            echo "Jira Atlassian E-posta" ;;
            JIRA_TOKEN)            echo "Jira API Token" ;;
            JIRA_DEFAULT_PROJECT)  echo "Jira Proje Anahtarı (örn: SID)" ;;
            TEAMS_WEBHOOK_URL)     echo "Microsoft Teams Webhook URL" ;;
            *)                     echo "$1" ;;
        esac
    }

    _sync_real_keys_to_test_env_enabled() {
        local raw="${SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV:-0}"
        raw="${raw,,}"
        raw="${raw//[[:space:]]/}"
        case "$raw" in
            1|true|yes|y|evet|e) return 0 ;;
            *) return 1 ;;
        esac
    }

    _materialize_real_keys_to_env_enabled() {
        local raw="${SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV:-0}"
        raw="${raw,,}"
        raw="${raw//[[:space:]]/}"
        case "$raw" in
            1|true|yes|y|evet|e) return 0 ;;
            *) return 1 ;;
        esac
    }

    _api_key_env_targets_without_warning() {
        local -a targets=()
        local advanced_env_file="$SCRIPT_DIR/.env.advanced"
        local advanced_example_file="$SCRIPT_DIR/.env.advanced.example"
        local optional_env_file

        if ! _materialize_real_keys_to_env_enabled; then
            targets+=("$sidar_keys_file")
            printf '%s\n' "${targets[@]}"
            return 0
        fi

        targets+=("$env_file")
        if [[ ! -f "$advanced_env_file" && -f "$advanced_example_file" ]]; then
            install -m 600 "$advanced_example_file" "$advanced_env_file"
            ok ".env.advanced dosyası .env.advanced.example'dan API anahtarı senkronizasyonu için oluşturuldu."
        fi

        [[ -f "$advanced_env_file" && "$advanced_env_file" != "$env_file" ]] && targets+=("$advanced_env_file")

        optional_env_file="$SCRIPT_DIR/.env.development"
        [[ -f "$optional_env_file" && "$optional_env_file" != "$env_file" ]] && targets+=("$optional_env_file")

        optional_env_file="$SCRIPT_DIR/.env.test"
        if [[ -f "$optional_env_file" && "$optional_env_file" != "$env_file" ]]; then
            if _sync_real_keys_to_test_env_enabled; then
                targets+=("$optional_env_file")
            fi
        fi

        printf '%s\n' "${targets[@]}"
    }

    local -a api_key_target_env_files=()
    local -a api_key_write_failures=()
    local api_key_write_success_count=0
    local api_key_write_failure_count=0
    local api_key_validated_count=0
    mapfile -t api_key_target_env_files < <(_api_key_env_targets_without_warning)
    if ! _materialize_real_keys_to_env_enabled; then
        info "Gerçek servis anahtarları env dosyalarına kopyalanmayacak; kalıcı kaynak: ${sidar_keys_file}. Gerekirse SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV=1 ile bilinçli etkinleştirin."
    fi
    if [[ -f "$SCRIPT_DIR/.env.test" && "$SCRIPT_DIR/.env.test" != "$env_file" ]] &&
        _materialize_real_keys_to_env_enabled && ! _sync_real_keys_to_test_env_enabled; then
        warn ".env.test içine gerçek servis anahtarları senkronize edilmedi (varsayılan güvenli davranış). Gerekirse SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=1 ile bilinçli etkinleştirin."
    fi

    # Anahtarı .env ve mevcut runtime env varyantlarına yazar; boşsa sessizce atlar.
    _write_key() {
        local key="$1"
        local val target target_name max_value_bytes
        val="${2:-}"
        if [[ "$val" == *$'\n'* || "$val" == *$'\r'* ]]; then
            warn "${key}: değer tek satır olmalıdır; configured sayılmayacak."
            api_key_write_failures+=("validation:${key}")
            ((api_key_write_failure_count += 1))
            return 1
        fi
        [[ -z "$val" ]] && return 0
        if ! _validate_api_key_value "$key" "$val"; then
            api_key_write_failures+=("validation:${key}")
            ((api_key_write_failure_count += 1))
            return 1
        fi
        ((api_key_validated_count += 1))
        max_value_bytes="$(_api_key_max_value_bytes "$key")"

        for target in "${api_key_target_env_files[@]}"; do
            mkdir -p "$(dirname "$target")"
            [[ -f "$target" ]] || : > "$target"
            chmod 600 "$target" 2>/dev/null || true
            target_name="$(_api_key_target_display_name "$target")"
            if printf '%s' "$val" | uv run python scripts/update_dotenv_value.py --file "$target" --key "$key" --max-value-bytes "$max_value_bytes"; then
                ok "${target_name}: ${key} güncellendi."
                ((api_key_write_success_count += 1))
            else
                warn "${target_name}: ${key} güncellenemedi (bkz. yukarıdaki update_dotenv_value hatası)."
                api_key_write_failures+=("${target_name}:${key}")
                ((api_key_write_failure_count += 1))
                return 1
            fi
        done
    }

    _api_key_max_value_bytes() {
        case "$1" in
            SLACK_WEBHOOK_URL|TEAMS_WEBHOOK_URL) echo 8192 ;;
            GOOGLE_SEARCH_CX|SLACK_DEFAULT_CHANNEL|JIRA_DEFAULT_PROJECT) echo 1024 ;;
            *) echo 16384 ;;
        esac
    }

    _validate_api_key_value() {
        local key="$1"
        local val="$2"
        local max_value_bytes value_bytes
        max_value_bytes="$(_api_key_max_value_bytes "$key")"
        if [[ "$val" == *$'\n'* || "$val" == *$'\r'* ]]; then
            warn "${key}: değer tek satır olmalıdır; configured sayılmayacak."
            return 1
        fi
        value_bytes="$(LC_ALL=C printf '%s' "$val" | wc -c | tr -d '[:space:]')"
        if (( value_bytes > max_value_bytes )); then
            warn "${key}: değer ${value_bytes} bayt (sınır: ${max_value_bytes}) — configured sayılmayacak."
            return 1
        fi
        case "$key" in
            SLACK_WEBHOOK_URL|TEAMS_WEBHOOK_URL|JIRA_URL)
                if [[ ! "$val" =~ ^https:// ]]; then
                    warn "${key}: webhook/URL değeri https:// şemasıyla başlamalı; configured sayılmayacak."
                    return 1
                fi
                ;;
        esac
        return 0
    }

    _api_key_target_display_name() {
        local target="$1"
        if [[ "$target" == "$sidar_keys_file" ]]; then
            printf 'SIDAR_KEYS_FILE (%s)' "$target"
        else
            basename "$target"
        fi
    }

    _report_imported_api_key_targets() {
        local source_file="$1"
        local imported_count="$2"
        local target target_name total_expected

        total_expected=$((imported_count * ${#api_key_target_env_files[@]}))
        if (( api_key_write_failure_count > 0 )); then
            warn "${source_file}: ${api_key_validated_count} doğrulama, ${total_expected} API anahtarı yazma denemesinden ${api_key_write_success_count} başarılı, ${api_key_write_failure_count} başarısız."
            warn "Başarısız API anahtarı hedefleri: ${api_key_write_failures[*]}"
            return 1
        fi

        if ! _materialize_real_keys_to_env_enabled; then
            ok "${imported_count} API anahtarı SIDAR_KEYS_FILE (${sidar_keys_file}) içinde doğrulandı/güncellendi (${api_key_validated_count} başarılı doğrulama)."
            return 0
        fi

        ok "${imported_count} API anahtarı ${source_file} kaynağından alındı; ${api_key_validated_count} doğrulama başarılı; materialization açık."
        for target in "${api_key_target_env_files[@]}"; do
            target_name="$(_api_key_target_display_name "$target")"
            ok "${target_name}: ${imported_count} API anahtarı güncellendi."
        done
    }

    _warn_if_missing_critical_provider_keys() {
        local openai_key=""
        local anthropic_key=""

        openai_key=$(read_env_value_from_file "OPENAI_API_KEY" "$env_file" | tr -d '[:space:]')
        anthropic_key=$(read_env_value_from_file "ANTHROPIC_API_KEY" "$env_file" | tr -d '[:space:]')
        if [[ -z "$openai_key" && -f "$sidar_keys_file" ]]; then
            openai_key=$(read_env_value_from_file "OPENAI_API_KEY" "$sidar_keys_file" | tr -d '[:space:]')
        fi
        if [[ -z "$anthropic_key" && -f "$sidar_keys_file" ]]; then
            anthropic_key=$(read_env_value_from_file "ANTHROPIC_API_KEY" "$sidar_keys_file" | tr -d '[:space:]')
        fi

        if [[ -z "$openai_key" && -z "$anthropic_key" ]]; then
            warn "[UYARI] Kritik sağlayıcı anahtarı eksik: OPENAI_API_KEY veya ANTHROPIC_API_KEY alanlarından en az biri boş."
            warn "[UYARI] Kurulum durdurulmadı. Lütfen SIDAR_KEYS_FILE veya .env dosyasını sonradan manuel güncelleyin."
        fi
    }

    _sync_existing_api_keys_to_env_targets() {
        local key current_val
        local synced_count=0
        for key in "${KEY_ORDER[@]}"; do
            current_val=$(read_env_value_from_file "$key" "$env_file" | tr -d '\n')
            [[ -z "${current_val//[[:space:]]/}" ]] && continue
            _write_key "$key" "$current_val" || true
            ((synced_count += 1))
        done

        if (( synced_count > 0 )); then
            _report_imported_api_key_targets "$env_file" "$synced_count"
        fi
    }

    if [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: API anahtarı etkileşimli toplama adımı atlandı."
        _sync_existing_api_keys_to_env_targets
        return
    fi

    # ~/.sidar_keys.env gibi kalıcı bir dosyadan anahtarları içeri al.
    # Dosya varsa etkileşimli (zenity/whiptail/read) adımı tamamen atlanır.
    _import_api_keys_from_file() {
        local source_file="$1"
        local imported_count=0
        local read_count=0
        local key raw_val

        [[ -f "$source_file" ]] || return 1

        info "API anahtarları ${source_file} dosyasından içeri alınıyor (etkileşimli giriş atlanacak)..."
        for key in "${KEY_ORDER[@]}"; do
            raw_val=$(read_env_value_from_file "$key" "$source_file")
            raw_val="${raw_val#"${raw_val%%[![:space:]]*}"}"
            raw_val="${raw_val%"${raw_val##*[![:space:]]}"}"

            # Basit tek satır tırnaklarını temizle: KEY="value" / KEY='value'
            if [[ "$raw_val" == \"*\" && "$raw_val" == *\" ]]; then
                raw_val="${raw_val:1:${#raw_val}-2}"
            elif [[ "$raw_val" == \'*\' && "$raw_val" == *\' ]]; then
                raw_val="${raw_val:1:${#raw_val}-2}"
            fi

            if [[ -n "$raw_val" ]]; then
                ((read_count += 1))
                if [[ -f "$sidar_keys_file" && "$source_file" -ef "$sidar_keys_file" ]]; then
                    if _validate_api_key_value "$key" "$raw_val"; then
                        ((api_key_validated_count += 1))
                        ((api_key_write_success_count += 1))
                        ((imported_count += 1))
                    else
                        api_key_write_failures+=("SIDAR_KEYS_FILE:${key}")
                        ((api_key_write_failure_count += 1))
                        [[ "$NO_INTERACTION" == true ]] && return 1
                    fi
                elif _write_key "$key" "$raw_val"; then
                    ((imported_count += 1))
                else
                    [[ "$NO_INTERACTION" == true ]] && return 1
                fi
            fi
        done

        if (( imported_count > 0 )); then
            _report_imported_api_key_targets "$source_file" "$imported_count"
        else
            warn "${source_file} bulundu ancak beklenen API anahtarlarından hiçbiri geçerli/dolu değil (okunan: ${read_count})."
            (( read_count > 0 && api_key_write_failure_count > 0 )) && return 1
        fi

        return 0
    }

    step "API Anahtarları Yapılandırması"
    echo ""

    if _import_api_keys_from_file "$sidar_keys_file"; then
        info "Kalıcı anahtar dosyası tespit edildiği için etkileşimli API anahtarı soruları atlandı."
        _warn_if_missing_critical_provider_keys
        return
    fi

    # ── Durum tespiti: doğrudan inline (subshell yok, \r temizlendi) ──────────
    local -a missing_keys=()
    local _chk_val
    for key in "${KEY_ORDER[@]}"; do
        _chk_val=$(read_env_value_from_file "$key" "$env_file" | tr -d '\n')
        if [[ -z "$_chk_val" ]]; then
            missing_keys+=("$key")
            info "  [ eksik  ] ${key}"
        else
            ok   "  [ mevcut ] ${key}"
        fi
    done
    echo ""

    if [[ ${#missing_keys[@]} -eq 0 ]]; then
        ok "Tüm API anahtarları zaten tanımlı, devam ediliyor."
        _sync_existing_api_keys_to_env_targets
        return
    fi

    info "${#missing_keys[@]} anahtar eksik."
    info "Kullanmak istediğiniz servislerin anahtarlarını girin; kullanmayacaklarınızı boş bırakın."
    info "Sistemi yalnızca yerel Ollama ile kullanacaksanız hepsini boş bırakıp geçebilirsiniz."
    echo ""

    # Bir grubun eksik anahtarlarını döndürür (inline — subshell kullanmaz)
    _fill_group_missing() {
        # $1: virgülle ayrılmış grup anahtarları  $2: sonucu yazacağımız dizi adı (nameref)
        local -n _out_arr="$2"
        _out_arr=()
        local gk mk
        IFS=',' read -ra _gkeys <<< "$1"
        for gk in "${_gkeys[@]}"; do
            for mk in "${missing_keys[@]}"; do
                [[ "$mk" == "$gk" ]] && { _out_arr+=("$mk"); break; }
            done
        done
    }

    # ─── 1. Zenity GUI (WSLg / X11 ekranı varsa) ────────────────────────────
    local has_display=false
    [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]] && has_display=true

    if [[ "$has_display" == true ]] && ! command -v zenity &>/dev/null; then
        info "Grafik pencere için zenity kuruluyor..."
        sudo apt-get install -y zenity -qq >/dev/null 2>&1 || true
    fi

    if command -v zenity &>/dev/null && [[ "$has_display" == true ]]; then
        info "API anahtarı giriş pencereleri açılıyor (zenity — grup grup)..."
        local grp_spec grp_title grp_keys
        local -a grp_missing z_args _vals
        for grp_spec in "${API_GROUPS[@]}"; do
            grp_title="${grp_spec%%|*}"
            grp_keys="${grp_spec##*|}"
            _fill_group_missing "$grp_keys" grp_missing
            [[ ${#grp_missing[@]} -eq 0 ]] && continue

            z_args=(
                "--title=Sidar AI — ${grp_title}"
                "--text=${grp_title} için anahtarları girin.\nKullanmayacaklarınızı boş bırakın."
                "--separator=|"
            )
            local mk
            for mk in "${grp_missing[@]}"; do
                z_args+=("--add-entry=$(_key_label "$mk"):")
            done

            local zenity_out=""
            zenity_out=$(zenity --forms "${z_args[@]}" 2>/dev/null) || true
            [[ -z "$zenity_out" ]] && continue   # iptal / kapatıldı

            IFS='|' read -ra _vals <<< "$zenity_out"
            for i in "${!grp_missing[@]}"; do
                _write_key "${grp_missing[$i]}" "${_vals[$i]:-}" || true
            done
        done
        ok "API anahtarları kaydedildi, kurulum devam ediyor."
        _sync_existing_api_keys_to_env_targets
        _warn_if_missing_critical_provider_keys
        return
    fi

    # ─── 2. Whiptail TUI (terminal içi diyalog) ─────────────────────────────
    if command -v whiptail &>/dev/null; then
        info "Terminal tabanlı arayüz açılıyor (whiptail)..."
        local grp_spec grp_title grp_keys
        local -a grp_missing
        for grp_spec in "${API_GROUPS[@]}"; do
            grp_title="${grp_spec%%|*}"
            grp_keys="${grp_spec##*|}"
            _fill_group_missing "$grp_keys" grp_missing
            [[ ${#grp_missing[@]} -eq 0 ]] && continue

            whiptail --title "Sidar AI — API Anahtarları" \
                --msgbox "── ${grp_title} ──\n\nBu gruba ait anahtarları girmeniz istenecek.\nKullanmayacaklarınızı boş bırakabilirsiniz." \
                9 68 2>/dev/null || true

            local mk lbl input
            for mk in "${grp_missing[@]}"; do
                lbl="$(_key_label "$mk")"
                input=""
                input=$(whiptail \
                    --title "Sidar AI — ${grp_title}" \
                    --inputbox "${lbl}\n(Boş bırakmak için doğrudan Enter'a basın)" \
                    10 72 "" \
                    3>&1 1>&2 2>&3) || true
                _write_key "$mk" "$input" || true
            done
        done
        ok "API anahtar girişi tamamlandı, kurulum devam ediyor."
        _sync_existing_api_keys_to_env_targets
        _warn_if_missing_critical_provider_keys
        return
    fi

    # ─── 3. Basit read (her ortamda çalışır, fallback) ──────────────────────
    info "API anahtarlarını girin (boş bırakmak için doğrudan Enter'a basın):"
    echo ""
    local grp_spec grp_title grp_keys
    local -a grp_missing
    for grp_spec in "${API_GROUPS[@]}"; do
        grp_title="${grp_spec%%|*}"
        grp_keys="${grp_spec##*|}"
        _fill_group_missing "$grp_keys" grp_missing
        [[ ${#grp_missing[@]} -eq 0 ]] && continue

        echo -e "${BOLD}${BLUE}  ── ${grp_title} ──${NC}"
        local mk lbl input
        for mk in "${grp_missing[@]}"; do
            lbl="$(_key_label "$mk")"
            printf "  %-46s : " "$lbl"
            input=""
            # Gizli giriş: anahtarlar terminalde görünmez; satır düzeni için ardından echo basılır.
            clear_stdin_buffer
            IFS= read -rs input || true
            echo ""
            _write_key "$mk" "$input" || true
        done
        echo ""
    done
    ok "API anahtar girişi tamamlandı, kurulum devam ediyor."
    _sync_existing_api_keys_to_env_targets
    _warn_if_missing_critical_provider_keys
}

report_env_api_key_status() {
    local env_file="$1"
    local -a key_order=()
    mapfile -t key_order < <(sidar_user_api_key_names)

    # shellcheck disable=SC2034  # scripts/install_modules/phases/07_finish.sh reads this sourced state.
    ENV_API_KEYS_TOTAL="${#key_order[@]}"
    ENV_API_KEYS_FILLED=0
    ENV_API_KEYS_MISSING=()

    local key value
    for key in "${key_order[@]}"; do
        value=$(read_env_value_from_file "$key" "$env_file" | tr -d '\n')
        if [[ -n "$value" ]]; then
            ((ENV_API_KEYS_FILLED+=1))
        else
            ENV_API_KEYS_MISSING+=("$key")
        fi
    done
}

repair_private_file_permissions() {
    local file_path="$1"
    local label="$2"
    local mode=""

    [[ -f "$file_path" ]] || return 0

    mode="$(stat -c '%a' "$file_path" 2>/dev/null || true)"
    case "$mode" in
        600|400)
            ok "${label} izin kontrolü tamamlandı: ${file_path} mode=${mode}."
            ;;
        *)
            warn "${label} izinleri güvenli değil: ${file_path} mode=${mode:-bilinmiyor}; otomatik chmod 600 uygulanıyor."
            if chmod 600 "$file_path"; then
                ok "${label} izinleri 600 olarak düzeltildi: ${file_path}."
            else
                warn "${label} izinleri otomatik düzeltilemedi; manuel çalıştırın: chmod 600 \"${file_path}\""
            fi
            ;;
    esac
}

verify_sidar_keys_file_permissions() {
    local sidar_keys_file="${SIDAR_KEYS_FILE:-$HOME/.sidar_keys.env}"
    local sidar_session_file="${SIDAR_SESSION_FILE:-$HOME/.sidar_session.json}"
    local env_secret_file=""

    repair_private_file_permissions "$sidar_keys_file" "SIDAR_KEYS_FILE"
    repair_private_file_permissions "$sidar_session_file" "SIDAR_SESSION_FILE"
    for env_secret_file in \
        "$SCRIPT_DIR/.env" \
        "$SCRIPT_DIR/.env.advanced" \
        "$SCRIPT_DIR/.env.development" \
        "$SCRIPT_DIR/.env.test" \
        "$SCRIPT_DIR/.env.production"; do
        repair_private_file_permissions "$env_secret_file" "$(basename "$env_secret_file")"
    done
}

validate_runtime_env_loading() {
    local env_file="$SCRIPT_DIR/.env"

    step "Runtime .env Enjeksiyon Kontrolü"
    info "Yükleme zinciri: .env, .env.advanced, .env.\${SIDAR_ENV}, DOTENV_FILE, SIDAR_KEYS_FILE (proses env korunur; secret dosyası en sonda)"

    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; runtime env enjeksiyon kontrolü atlandı. Önce uv sync --all-extras çalıştırın."
        return 0
    fi

    if [[ ! -f "$env_file" ]]; then
        warn ".env bulunamadı; runtime yalnız proses env ve opsiyonel DOTENV_FILE/SIDAR_KEYS_FILE ile başlayacak."
    fi

    if ! (cd "$SCRIPT_DIR" && uv run python - <<'PY_RUNTIME_ENV_CHECK'
from __future__ import annotations

import config

print("ℹ️ Runtime dotenv yükleme raporu:")
for event in config.get_dotenv_load_report():
    label = event.get("label", "unknown")
    path = event.get("path") or event.get("raw_path") or "-"
    status = "loaded" if event.get("loaded") else f"skipped:{event.get('reason') or 'not_loaded'}"
    override = "override" if event.get("override") else "no-override"
    suffix = f" ({override}) {path}" if event.get("loaded") else ""
    print(f"  - {label}: {status}{suffix}")

missing = config.Config.get_missing_critical_runtime_keys()
if missing:
    print(
        "⚠️ Kritik runtime anahtarları çözülemedi: "
        + ", ".join(missing)
        + ". Değerleri .env, .env.advanced, DOTENV_FILE veya SIDAR_KEYS_FILE içine ekleyin."
    )
else:
    print("✅ Kritik runtime anahtarları dotenv yükleme zincirinden başarıyla çözüldü.")
PY_RUNTIME_ENV_CHECK
    ); then
        warn "Runtime env enjeksiyon kontrolü tamamlanamadı; uygulama başlatmadan önce .env/DOTENV_FILE/SIDAR_KEYS_FILE değerlerini kontrol edin."
        return 0
    fi
}


print_runtime_key_source_summary() {
    echo ""
    echo -e "${BOLD}Kritik key kaynak özeti (değerler maskeli):${NC}"

    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; kritik key kaynak özeti atlandı."
        return 0
    fi

    if ! (cd "$SCRIPT_DIR" && uv run python - <<'PY_KEY_SOURCE_SUMMARY'
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("SIDAR_CONFIG_QUIET", "true")
os.environ.setdefault("SIDAR_CONFIG_BANNER_LOGGED", "1")
env_path = Path(".env").resolve()
if env_path.exists():
    os.environ.setdefault("SIDAR_ENV_LOGGED", str(env_path))

import config

CRITICAL_KEYS = (
    ("API_KEY", ("API_KEY",), "direct"),
    ("JWT_SECRET_KEY", ("JWT_SECRET_KEY",), "direct"),
    ("MEMORY_ENCRYPTION_KEY", ("MEMORY_ENCRYPTION_KEY",), "direct"),
    ("DATABASE_URL", ("DATABASE_URL",), "postgres_derived"),
    ("SIDAR_REDIS_URL", ("SIDAR_REDIS_URL", "REDIS_URL"), "alias"),
    ("OPENAI_API_KEY", ("OPENAI_API_KEY",), "direct"),
    ("GEMINI_API_KEY", ("GEMINI_API_KEY",), "direct"),
    ("ANTHROPIC_API_KEY", ("ANTHROPIC_API_KEY",), "direct"),
    ("GITHUB_TOKEN", ("GITHUB_TOKEN",), "direct"),
    ("SLACK_TOKEN", ("SLACK_TOKEN",), "direct"),
    ("JIRA_TOKEN", ("JIRA_TOKEN",), "direct"),
    ("TEAMS_WEBHOOK_URL", ("TEAMS_WEBHOOK_URL",), "direct"),
)

source_report = config.get_dotenv_key_source_report()
config_cls = config.Config


def source_display_for(*keys: str) -> str:
    for source_key in keys:
        source = source_report.get(source_key)
        if source:
            label = str(source.get("label") or "dotenv")
            path = str(source.get("path") or "")
            path_display = Path(path).name if path else "-"
            return f"{label}:{path_display}:{source_key}"
    return "process-env"


def postgres_parts_available() -> bool:
    return all(
        str(os.getenv(key, "")).strip()
        for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    )


print("  KEY                         DURUM      KAYNAK")
print("  --------------------------  ---------  ----------------------------------------")
for display_key, env_keys, mode in CRITICAL_KEYS:
    value = next((os.getenv(key, "") for key in env_keys if os.getenv(key, "")), "")
    source_display = source_display_for(*env_keys)

    if mode == "postgres_derived" and not value:
        derived_database_url = getattr(config_cls, "DATABASE_URL", "")
        if derived_database_url and postgres_parts_available():
            print(f"  {display_key:<26}  türetildi  POSTGRES_* parçaları")
            continue

    if mode == "alias":
        alias_value = getattr(config_cls, "SIDAR_REDIS_URL", "") or getattr(config_cls, "REDIS_URL", "")
        if alias_value:
            if not value:
                source_display = "varsayılan (SIDAR_REDIS_URL/REDIS_URL yok)"
            print(f"  {display_key:<26}  ***        {source_display} (REDIS_URL alias destekli)")
            continue

    if not value:
        print(f"  {display_key:<26}  eksik      -")
        continue

    print(f"  {display_key:<26}  ***        {source_display}")
PY_KEY_SOURCE_SUMMARY
    ); then
        warn "Kritik key kaynak özeti üretilemedi; config.get_dotenv_key_source_report() çıktısını manuel kontrol edin."
        return 0
    fi
}

ensure_env_file_secrets_after_uv_sync() {
    local env_file="$SCRIPT_DIR/.env"
    local example_file="$SCRIPT_DIR/.env.example"

    # uv venv / uv sync tamamlanır tamamlanmaz temel .env dosyasını hazırla.
    # Bu adım bilinçli olarak interaktif değildir; kullanıcıyı manuel secret
    # üretme yükünden kurtarır ve sonraki setup_env_file doğrulamasına sağlam
    # başlangıç değerleri bırakır.
    if [[ ! -f "$env_file" ]]; then
        if [[ -f "$example_file" ]]; then
            cp "$example_file" "$env_file"
            ok ".env dosyası uv sync sonrası .env.example üzerinden oluşturuldu."
        else
            : > "$env_file"
            warn ".env.example bulunamadı; boş .env oluşturuldu ve secret alanları eklenecek."
        fi
    elif [[ ! -s "$env_file" && -f "$example_file" ]]; then
        cp "$example_file" "$env_file"
        ok "Boş .env dosyası uv sync sonrası .env.example ile dolduruldu."
    fi

    ensure_sidar_env_default "$env_file"
    ensure_auto_secrets "$env_file"
    propagate_shared_secrets_to_env_variants "$env_file"
}

# ── Otomatik Secret Üretimi ────────────────────────────────────────────────
# Güvenlik anahtarlarını (API_KEY, JWT_SECRET_KEY, MEMORY_ENCRYPTION_KEY vb.)
# .env boşsa veya bilinen güvensiz örnekse otomatik üretir.
# Hem yeni oluşturulan hem de mevcut .env üzerinde çalışır.
ensure_auto_secrets() {
    local env_file="$1"

    # Boş, eksik veya bilinen güvensiz değer mi? → 0 (true) döner.
    # Bilinen örnek değerler merkezi weak-secret listesi ve .env.example üzerinden
    # okunur; bu fonksiyon gizli/örnek literal değerleri install script içinde
    # tekrar gömmemelidir.
    _is_missing_or_insecure() {
        local key="$1"
        local val
        val=$(read_env_value_from_file "$key" "$env_file" | tr -d '\n')
        is_weak_secret_value "$val" && return 0
        is_known_weak_secret_value "$key" "$val" && return 0
        is_env_example_secret_value "$key" "$val" && return 0
        return 1
    }

    # Üretilen değeri .env'e yazar (varsa günceller, yoksa satır ekler)
    _write_secret() {
        local key="$1" val="$2"
        if grep -q "^${key}=" "$env_file" 2>/dev/null; then
            sed_inplace "s|^${key}=.*|${key}=${val}|" "$env_file"
        else
            echo "${key}=${val}" >> "$env_file"
        fi
    }

    # urlsafe token üretici (python3 → openssl fallback)
    _gen_urlsafe() {
        local n="$1"
        local candidate
        if command -v python3 &>/dev/null; then
            for _ in {1..10}; do
                candidate="$(python3 -c "import secrets; print(secrets.token_urlsafe($n))" 2>/dev/null || true)"
                [[ -n "$candidate" ]] || continue
                if ! is_weak_secret_value "$candidate"; then
                    printf '%s\n' "$candidate"
                    return 0
                fi
            done
        elif command -v openssl &>/dev/null; then
            for _ in {1..10}; do
                candidate="$(openssl rand -base64 "$n" 2>/dev/null | tr '+/' '-_' | tr -d '\n=' || true)"
                [[ -n "$candidate" ]] || continue
                if ! is_weak_secret_value "$candidate"; then
                    printf '%s\n' "$candidate"
                    return 0
                fi
            done
        fi
    }

    # hex token üretici
    _gen_hex() {
        local bits="$1"
        local candidate
        if command -v python3 &>/dev/null; then
            for _ in {1..10}; do
                candidate="$(python3 -c "import secrets; print(secrets.token_hex($((bits / 2))))" 2>/dev/null || true)"
                [[ -n "$candidate" ]] || continue
                if ! is_weak_secret_value "$candidate"; then
                    printf '%s\n' "$candidate"
                    return 0
                fi
            done
        elif command -v openssl &>/dev/null; then
            for _ in {1..10}; do
                candidate="$(openssl rand -hex "$((bits / 2))" 2>/dev/null | tr -d '\n' || true)"
                [[ -n "$candidate" ]] || continue
                if ! is_weak_secret_value "$candidate"; then
                    printf '%s\n' "$candidate"
                    return 0
                fi
            done
        fi
    }

    # Fernet anahtarı üretici
    _gen_fernet() {
        local candidate
        for _ in {1..10}; do
            candidate="$(python3 - 2>/dev/null <<'PY' || true
try:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())
except Exception:
    pass
PY
)"
            [[ -n "$candidate" ]] || continue
            if ! is_weak_secret_value "$candidate"; then
                printf '%s\n' "$candidate"
                return 0
            fi
        done
    }

    # ── POSTGRES_PASSWORD ────────────────────────────────────────────────────
    if _is_missing_or_insecure "POSTGRES_PASSWORD"; then
        local _v; _v=$(_gen_urlsafe 24)
        if [[ -n "$_v" ]]; then
            _write_secret "POSTGRES_PASSWORD" "$_v"
            ok ".env: POSTGRES_PASSWORD otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "POSTGRES_PASSWORD otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── REDIS_PASSWORD ───────────────────────────────────────────────────────
    # docker-compose Redis'i --requirepass ile başlatır ve portu yalnızca host
    # loopback arayüzüne publish eder; bu değer boş/zayıfsa `docker compose up` REDIS_PASSWORD'ün
    # zorunlu ${VAR:?...} kontrolünde başarısız olur.
    if _is_missing_or_insecure "REDIS_PASSWORD"; then
        local _v; _v=$(_gen_urlsafe 24)
        if [[ -n "$_v" ]]; then
            _write_secret "REDIS_PASSWORD" "$_v"
            ok ".env: REDIS_PASSWORD otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "REDIS_PASSWORD otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── API_KEY ──────────────────────────────────────────────────────────────
    if _is_missing_or_insecure "API_KEY"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "API_KEY" "$_v"
            ok ".env: API_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "API_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── JWT_SECRET_KEY ────────────────────────────────────────────────────────
    if _is_missing_or_insecure "JWT_SECRET_KEY"; then
        local _v; _v=$(_gen_urlsafe 64)
        if [[ -n "$_v" ]]; then
            _write_secret "JWT_SECRET_KEY" "$_v"
            ok ".env: JWT_SECRET_KEY otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "JWT_SECRET_KEY otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── MEMORY_ENCRYPTION_KEY (Fernet) ────────────────────────────────────────
    if _is_missing_or_insecure "MEMORY_ENCRYPTION_KEY"; then
        local _v; _v=$(_gen_fernet)
        if [[ -n "$_v" ]]; then
            _write_secret "MEMORY_ENCRYPTION_KEY" "$_v"
            ok ".env: MEMORY_ENCRYPTION_KEY (Fernet) otomatik üretildi."
        else
            warn "MEMORY_ENCRYPTION_KEY otomatik üretilemedi. Lütfen .env içinde geçerli bir Fernet anahtarı tanımlayın."
        fi
    else
        ok ".env: MEMORY_ENCRYPTION_KEY mevcut ve güvenli; yeniden üretilmedi."
    fi

    # ── Hex tabanlı webhook/federation secret'lar ─────────────────────────────
    _auto_hex_secret() {
        local key="$1" bits="${2:-64}"; shift 2
        if _is_missing_or_insecure "$key" "$@"; then
            local _v; _v=$(_gen_hex "$bits")
            if [[ -n "$_v" ]]; then
                _write_secret "$key" "$_v"
                ok ".env: ${key} otomatik ve güvenli bir değerle oluşturuldu."
            else
                warn "${key} otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
            fi
        fi
    }

    _auto_hex_secret "AUTONOMY_WEBHOOK_SECRET" 64
    _auto_hex_secret "SWARM_FEDERATION_SHARED_SECRET" 64
    _auto_hex_secret "GITHUB_WEBHOOK_SECRET" 40

    # ── GRAFANA_ADMIN_PASSWORD ────────────────────────────────────────────────
    if _is_missing_or_insecure "GRAFANA_ADMIN_PASSWORD"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "GRAFANA_ADMIN_PASSWORD" "$_v"
            ok ".env: GRAFANA_ADMIN_PASSWORD otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "GRAFANA_ADMIN_PASSWORD otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi

    # ── METRICS_TOKEN ─────────────────────────────────────────────────────────
    # /metrics uçlarını koruyan Bearer token; örnek/legacy değerler merkezi listeden denetlenir.
    if _is_missing_or_insecure "METRICS_TOKEN"; then
        local _v; _v=$(_gen_urlsafe 32)
        if [[ -n "$_v" ]]; then
            _write_secret "METRICS_TOKEN" "$_v"
            ok ".env: METRICS_TOKEN otomatik ve güvenli bir değerle oluşturuldu."
        else
            warn "METRICS_TOKEN otomatik üretilemedi. Lütfen .env içinde güçlü bir değer tanımlayın."
        fi
    fi
}

sidar_production_secret_rotation_keys() {
    printf '%s\n' \
        API_KEY \
        JWT_SECRET_KEY \
        MEMORY_ENCRYPTION_KEY \
        AUTONOMY_WEBHOOK_SECRET \
        SWARM_FEDERATION_SHARED_SECRET \
        GITHUB_WEBHOOK_SECRET \
        GRAFANA_ADMIN_PASSWORD \
        METRICS_TOKEN
}

emit_production_secret_rotation_notice() {
    local src="$1"
    local -a shared_matches=()
    mapfile -t shared_matches < <(sidar_shared_production_secret_keys "$src")

    if (( ${#shared_matches[@]} == 0 )); then
        return 0
    fi

    warn ".env.production ${#shared_matches[@]} ortak secret değerini local/dev/test zinciriyle paylaşıyor: ${shared_matches[*]}. Gerçek production rollout öncesi bu 8 secret'ı rotate edin; komut: uv run python -m scripts.rotate_production_secrets --env-file .env.production --apply --ack-memory-key-impact; runbook: docs/runbooks/production-secret-rotation.md"
}

sidar_shared_production_secret_keys() {
    local src="$1"
    local production_env="$SCRIPT_DIR/.env.production"
    local key="" src_val="" prod_val=""

    [[ -f "$src" && -f "$production_env" ]] || return 0

    while IFS= read -r key; do
        [[ -n "$key" ]] || continue
        src_val=$(read_env_value_from_file "$key" "$src" | tr -d '\n')
        prod_val=$(read_env_value_from_file "$key" "$production_env" | tr -d '\n')
        if [[ -n "${src_val//[[:space:]]/}" && "$src_val" == "$prod_val" ]]; then
            printf '%s\n' "$key"
        fi
    done < <(sidar_production_secret_rotation_keys)
}

production_secret_rotation_gate_passes() {
    local src="$1"
    local -a shared_matches=()
    mapfile -t shared_matches < <(sidar_shared_production_secret_keys "$src")
    if (( ${#shared_matches[@]} == 0 )); then
        return 0
    fi
    warn "SIDAR_ENV=production kalıcılaştırması engellendi: .env.production içinde local/dev/test ile ortak secret bulundu: ${shared_matches[*]}. Önce production secret rotasyonunu tamamlayın."
    return 1
}

propagate_shared_secrets_to_env_variants() {
    local src="$1"
    local -a shared_keys=()
    mapfile -t shared_keys < <(sidar_production_secret_rotation_keys)
    local -a variants=(
        ".env.development:.env.development.example"
        ".env.test:.env.test.example"
        ".env.production:.env.production.example"
        ".env.advanced:.env.advanced.example"  # Sürüm kontrollü şablondan üretilen advanced runtime env.
    )

    [[ -f "$src" ]] || return 0

    local pair target example name key val cur example_val changed_count
    for pair in "${variants[@]}"; do
        target="$SCRIPT_DIR/${pair%%:*}"
        example="$SCRIPT_DIR/${pair##*:}"
        name="${pair%%:*}"

        if [[ ! -f "$target" ]]; then
            if [[ -f "$example" ]]; then
                install -m 600 "$example" "$target"
                ok "${name} dosyası ${pair##*:} üzerinden oluşturuldu."
            else
                warn "${pair##*:} bulunamadı; ${name} secret senkronizasyonu atlandı."
                continue
            fi
        fi

        changed_count=0
        for key in "${shared_keys[@]}"; do
            val=$(read_env_value_from_file "$key" "$src" | tr -d '\n')
            [[ -z "${val//[[:space:]]/}" ]] && continue

            cur=$(read_env_value_from_file "$key" "$target" | tr -d '\n')
            example_val=$(read_env_value_from_file "$key" "$example" | tr -d '\n')

            if is_weak_secret_value "$cur" \
                || is_known_weak_secret_value "$key" "$cur" \
                || is_env_example_secret_value "$key" "$cur" \
                || [[ -n "${example_val//[[:space:]]/}" && "$cur" == "$example_val" ]]; then
                if grep -q "^${key}=" "$target" 2>/dev/null; then
                    sed_inplace "s|^${key}=.*|${key}=${val}|" "$target"
                else
                    echo "${key}=${val}" >> "$target"
                fi
                changed_count=$((changed_count + 1))
            fi
        done
        if (( changed_count > 0 )); then
            ok "${name}: ${changed_count} ortak secret .env ile senkronize edildi."
        fi
    done

    emit_production_secret_rotation_notice "$src"

    # PostgreSQL credentials are intentionally delegated to the idempotent Python
    # helper to avoid per-key/per-file bash rewrites and noisy repeated logs.
    sync_database_env_chain_after_setup
}

# GPU tespiti bir makine gerçeğidir; .env'e yazılan USE_GPU/REQUIRE_GPU/
# GPU_MIXED_PRECISION/COMPOSE_PROFILES değerleri .env.development ve
# .env.advanced şablonlarına da yayılmazsa, runtime dotenv zinciri
# (config.py) SIDAR_ENV=development için .env.development'ı override=True
# ile en son yüklediğinden .env'deki GPU ayarı sessizce ezilir.
# .env.production kasıtlı olarak hariç tutulur: production GPU etkinleştirme
# production-readiness gate'i geçmeden manuel/açık olmalıdır.
propagate_gpu_settings_to_env_variants() {
    local src="$1"
    [[ -f "$src" ]] || return 0

    local -a gpu_keys=(USE_GPU REQUIRE_GPU GPU_MIXED_PRECISION COMPOSE_PROFILES)
    local -a variants=(
        ".env.development:.env.development.example"
        ".env.advanced:.env.advanced.example"
    )

    local pair target example name key val cur changed_count
    for pair in "${variants[@]}"; do
        target="$SCRIPT_DIR/${pair%%:*}"
        example="$SCRIPT_DIR/${pair##*:}"
        name="${pair%%:*}"

        if [[ ! -f "$target" ]]; then
            if [[ -f "$example" ]]; then
                install -m 600 "$example" "$target"
                ok "${name} dosyası ${pair##*:} üzerinden oluşturuldu."
            else
                warn "${pair##*:} bulunamadı; ${name} GPU senkronizasyonu atlandı."
                continue
            fi
        fi

        changed_count=0
        for key in "${gpu_keys[@]}"; do
            val=$(read_env_value_from_file "$key" "$src" | tr -d '\n')
            [[ -z "${val//[[:space:]]/}" ]] && continue

            cur=$(read_env_value_from_file "$key" "$target" | tr -d '\n')
            [[ "$cur" == "$val" ]] && continue

            if grep -q "^${key}=" "$target" 2>/dev/null; then
                sed_inplace "s|^${key}=.*|${key}=${val}|" "$target"
            else
                echo "${key}=${val}" >> "$target"
            fi
            changed_count=$((changed_count + 1))
        done
        if (( changed_count > 0 )); then
            ok "${name}: ${changed_count} GPU ayarı .env ile senkronize edildi."
        fi
    done
}

# GPU tespitine göre USE_GPU/REQUIRE_GPU/GPU_MIXED_PRECISION/COMPOSE_PROFILES
# değerlerini $env_file içinde uyumlu hale getirir ve ardından
# .env.development/.env.advanced şablonlarına yayar. Hem ilk kurulumda hem
# de mevcut .env üzerinde yeniden çalıştırmada (idempotent) çağrılmalıdır.
configure_gpu_env_defaults() {
    local env_file="$1"
    command -v sed &>/dev/null || return 0

    if [[ "$GPU_AVAILABLE" == true ]]; then
        info "DEBUG: GPU branch entered for .env configuration (GPU_AVAILABLE=true)."
        if grep -q '^USE_GPU=' "$env_file"; then
            sed_inplace 's/^USE_GPU=.*/USE_GPU=true/' "$env_file"
        else
            echo 'USE_GPU=true' >> "$env_file"
        fi
        if grep -q '^GPU_MIXED_PRECISION=' "$env_file"; then
            sed_inplace 's/^GPU_MIXED_PRECISION=.*/GPU_MIXED_PRECISION=true/' "$env_file"
        else
            echo 'GPU_MIXED_PRECISION=true' >> "$env_file"
        fi
        if grep -q '^REQUIRE_GPU=' "$env_file"; then
            sed_inplace 's/^REQUIRE_GPU=.*/REQUIRE_GPU=true/' "$env_file"
        else
            echo 'REQUIRE_GPU=true' >> "$env_file"
        fi

        # Docker için GPU modunu ön tanımlı yap
        if grep -q '^COMPOSE_PROFILES=' "$env_file"; then
            sed_inplace 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=gpu/' "$env_file"
        else
            echo "COMPOSE_PROFILES=gpu" >> "$env_file"
        fi

        ok "${env_file##*/}: USE_GPU=true, REQUIRE_GPU=true, GPU_MIXED_PRECISION=true (GPU tespit edildi)"
        ok "${env_file##*/}: COMPOSE_PROFILES=gpu ayarlandı (Docker GPU modu artık varsayılan)."
    else
        if grep -q '^USE_GPU=' "$env_file"; then
            sed_inplace 's/^USE_GPU=.*/USE_GPU=false/' "$env_file"
        else
            echo 'USE_GPU=false' >> "$env_file"
        fi
        if grep -q '^GPU_MIXED_PRECISION=' "$env_file"; then
            sed_inplace 's/^GPU_MIXED_PRECISION=.*/GPU_MIXED_PRECISION=false/' "$env_file"
        else
            echo 'GPU_MIXED_PRECISION=false' >> "$env_file"
        fi
        if grep -q '^REQUIRE_GPU=' "$env_file"; then
            sed_inplace 's/^REQUIRE_GPU=.*/REQUIRE_GPU=false/' "$env_file"
        else
            echo 'REQUIRE_GPU=false' >> "$env_file"
        fi
        if grep -q '^COMPOSE_PROFILES=' "$env_file"; then
            sed_inplace 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=cpu/' "$env_file"
        else
            echo "COMPOSE_PROFILES=cpu" >> "$env_file"
        fi
        ok "${env_file##*/}: USE_GPU=false, REQUIRE_GPU=false, GPU_MIXED_PRECISION=false, COMPOSE_PROFILES=cpu ayarlandı."
    fi

    # Docker + GPU tespit edildiyse NVIDIA runtime'ı varsayılan yap
    if [[ "$GPU_AVAILABLE" == true ]] && command -v docker &>/dev/null; then
        if grep -q '^DOCKER_RUNTIME=' "$env_file"; then
            sed_inplace 's/^DOCKER_RUNTIME=.*/DOCKER_RUNTIME=nvidia/' "$env_file"
        else
            echo 'DOCKER_RUNTIME=nvidia' >> "$env_file"
        fi

        if grep -q '^DOCKER_ALLOWED_RUNTIMES=' "$env_file"; then
            if ! grep -q '^DOCKER_ALLOWED_RUNTIMES=.*nvidia' "$env_file"; then
                sed_inplace 's/^DOCKER_ALLOWED_RUNTIMES=.*/DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime,nvidia/' "$env_file"
            fi
        else
            echo 'DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime,nvidia' >> "$env_file"
        fi

        ok "${env_file##*/}: Docker GPU varsayılanları ayarlandı (DOCKER_RUNTIME=nvidia)."
    fi

    propagate_gpu_settings_to_env_variants "$env_file"
}

ensure_local_service_host_defaults() {
    local env_file="$1"
    # Lokal kurulumda Docker hostname yerine localhost kullan
    if grep -q '^REDIS_URL=redis://redis:6379/0' "$env_file"; then
        sed_inplace 's|^REDIS_URL=redis://redis:6379/0|REDIS_URL=redis://localhost:6379/0|' "$env_file"
        ok ".env: REDIS_URL lokal ortam için localhost olarak güncellendi."
    fi

    if grep -q '^OTEL_EXPORTER_ENDPOINT=http://jaeger:' "$env_file"; then
        sed_inplace 's|^OTEL_EXPORTER_ENDPOINT=http://jaeger:|OTEL_EXPORTER_ENDPOINT=http://localhost:|' "$env_file"
        ok ".env: OTEL_EXPORTER_ENDPOINT lokal ortam için localhost olarak güncellendi."
    fi
}

ensure_sidar_env_default() {
    local env_file="$1"
    local current_env=""

    current_env=$(read_env_value_from_file "SIDAR_ENV" "$env_file" | tr -d '"'\''[:space:]')

    if [[ -z "$current_env" ]]; then
        echo "SIDAR_ENV=development" >> "$env_file"
        ok ".env: SIDAR_ENV=development eklendi."
        return
    fi

    if [[ "$current_env" == "production" ]]; then
        sed_inplace 's/^SIDAR_ENV=.*/SIDAR_ENV=development/' "$env_file"
        warn ".env: SIDAR_ENV=production varsayılanı development olarak düzeltildi (üretimde manuel production yapın)."
    fi
}

prompt_post_install_sidar_env_mode() {
    local env_file="$SCRIPT_DIR/.env"
    local example_file="$SCRIPT_DIR/.env.example"
    local env_choice=""
    local selected_env="development"
    local previous_env=""

    step "Kurulum Sonrası Uygulama Ortamı Seçimi"

    # Emniyet ağı: .env herhangi bir nedenle yoksa örnek dosyadan oluştur.
    if [[ ! -f "$env_file" ]]; then
        if [[ -f "$example_file" ]]; then
            cp "$example_file" "$env_file"
            ok ".env dosyası .env.example üzerinden oluşturuldu."
        else
            warn ".env.example bulunamadı; SIDAR_ENV güncellemesi atlanıyor."
            return
        fi
    fi
    previous_env="$(read_env_value_from_file "SIDAR_ENV" "$env_file" | tr -d '"'\''[:space:]')"

    if [[ "$AUTO_ENV_TYPE" != "ask" ]]; then
        selected_env="$AUTO_ENV_TYPE"
        info "AUTO_INSTALL: ENV_TYPE=$selected_env olarak uygulandı."
    elif [[ -n "${SIDAR_SELECTED_ENV_TYPE:-}" ]]; then
        selected_env="$SIDAR_SELECTED_ENV_TYPE"
        info "Önceden seçilen SIDAR_ENV=$selected_env tekrar uygulanıyor."
    elif [[ "$NO_INTERACTION" == true ]]; then
        info "--ci/--no-interaction etkin: SIDAR_ENV varsayılanı development bırakıldı."
    else
        echo ""
        echo "======================================================"
        echo "✅ Kurulum işlemleri tamamlandı!"
        echo "Sistemi hangi modda çalıştırmak istiyorsunuz?"
        echo "  1) Development (Geliştirme ve Test - Debug logları açık)"
        echo "  2) Production  (Canlı Kullanım - Hızlı, güvenli, optimize)"
        echo "======================================================"

        clear_stdin_buffer
        if read -r -t "$SIDAR_PROMPT_TIMEOUT" -p "Seçiminiz (1 veya 2, varsayılan=1): " env_choice 2>/dev/tty; then
            :
        else
            warn "${SIDAR_PROMPT_TIMEOUT} saniye içinde seçim yapılmadı. Varsayılan seçim: 1 (Development)."
            env_choice="1"
        fi

        if [[ "$env_choice" == "2" ]]; then
            selected_env="production"
        fi
    fi

    SIDAR_SELECTED_ENV_TYPE="$selected_env"
    export SIDAR_SELECTED_ENV_TYPE

    if [[ "$selected_env" == "production" ]]; then
        local production_ready=""
        if declare -F sidar_install_summary_field_or_empty >/dev/null; then
            production_ready="$(sidar_install_summary_field_or_empty production_ready)"
        fi
        if [[ "$production_ready" != "true" ]]; then
            info "Production seçimi kaydedildi; production-readiness gate geçmeden SIDAR_ENV=production kalıcılaştırılmayacak."
            return 0
        fi

        if ! production_secret_rotation_gate_passes "$env_file"; then
            info "Production seçimi kaydedildi; secret rotasyon kapısı geçmeden SIDAR_ENV=production kalıcılaştırılmayacak."
            return 0
        fi

        if is_alembic_at_head; then
            info "Production seçimi için Alembic current=head doğrulandı."
        else
            info "Production seçimi için Alembic current/head uyuşmuyor; veritabanı migrasyonu doğrulanıyor..."
            run_migrations
        fi
    fi

    if grep -qE '^SIDAR_ENV=' "$env_file"; then
        sed_inplace "s/^SIDAR_ENV=.*/SIDAR_ENV=$selected_env/" "$env_file"
    else
        echo "SIDAR_ENV=$selected_env" >> "$env_file"
    fi

    if [[ "$selected_env" == "production" ]]; then
        ok "🚀 Ortam değişkenleri 'Production' (Canlı Kullanım) olarak güncellendi; production-readiness, secret rotasyon ve migration doğrulamaları tamamlandı."
    else
        ok "🛠️ Ortam değişkenleri 'Development' (Geliştirme) olarak güncellendi."
        if is_alembic_at_head; then
            if [[ "$previous_env" != "$selected_env" ]]; then
                info "SIDAR_ENV değişti (${previous_env:-bilinmiyor} -> ${selected_env}) ancak Alembic current=head; tekrar migrasyon atlandı."
            else
                info "SIDAR_ENV değişmedi ve Alembic current=head; tekrar migrasyon atlandı."
            fi
        else
            if [[ "$previous_env" != "$selected_env" ]]; then
                info "SIDAR_ENV değişti (${previous_env:-bilinmiyor} -> ${selected_env}) ve Alembic current/head uyuşmuyor; veritabanı migrasyonu tekrar doğrulanıyor..."
            else
                info "Alembic current/head uyuşmuyor; veritabanı migrasyonu tekrar doğrulanıyor..."
            fi
            run_migrations
        fi
    fi

    ok "Sidar kullanıma hazır!"
}


get_env_value() {
    local env_file="$1" key="$2"
    read_env_value_from_file "$key" "$env_file"
}

secret_strength_script_file() {
    local primary="${SCRIPT_DIR}/scripts/secret_strength.py"
    local original="${ORIGINAL_SCRIPT_DIR}/scripts/secret_strength.py"
    if [[ -f "$primary" ]]; then
        printf '%s\n' "$primary"
    elif [[ -f "$original" ]]; then
        printf '%s\n' "$original"
    fi
}

is_weak_secret_value() {
    local value="${1:-}"
    local strength_script=""
    local strength_status=0
    [[ -n "${value//[[:space:]]/}" ]] || return 0

    strength_script="$(secret_strength_script_file)"
    if [[ -n "$strength_script" ]] && command -v python3 &>/dev/null; then
        if python3 "$strength_script" --quiet -- "$value"; then
            return 0
        fi
        strength_status="$?"
        [[ "$strength_status" == "1" ]] && return 1
    fi

    case "${value,,}" in
        *password*|*passwd*|sidar|admin|changeme|change_me|change-me*|replace-with-*|*secret*|default|*test*|example|postgres|root|*qwerty*|*letmein*|*welcome*|123456|12345678|*1234*|*abcd*|*asdf*|*zxcv*)
            return 0
            ;;
    esac
    (( ${#value} < 24 )) && return 0
    [[ "$value" =~ (.)\1\1\1 ]] && return 0
    return 1
}

known_weak_secrets_file() {
    local primary="${SCRIPT_DIR}/scripts/known_weak_secrets.txt"
    local original="${ORIGINAL_SCRIPT_DIR}/scripts/known_weak_secrets.txt"
    if [[ -f "$primary" ]]; then
        printf '%s\n' "$primary"
    elif [[ -f "$original" ]]; then
        printf '%s\n' "$original"
    fi
}

is_known_weak_secret_value() {
    local key="$1" value="${2:-}" weak_file line entry_key entry_value
    [[ -n "${value//[[:space:]]/}" ]] || return 1
    weak_file="$(known_weak_secrets_file)"
    if [[ -z "$weak_file" || ! -f "$weak_file" ]]; then
        return 1
    fi

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ -n "${line//[[:space:]]/}" ]] || continue
        [[ "${line:0:1}" == "#" ]] && continue
        [[ "$line" == *=* ]] || continue
        entry_key="${line%%=*}"
        entry_value="${line#*=}"
        entry_key="${entry_key//[[:space:]]/}"
        [[ "$entry_key" == "$key" || "$entry_key" == "*" ]] || continue
        [[ "$value" == "$entry_value" ]] && return 0
    done < "$weak_file"

    return 1
}

is_env_example_secret_value() {
    local key="$1" value="${2:-}" example_file example_value
    [[ -n "${value//[[:space:]]/}" ]] || return 1

    for example_file in "${SCRIPT_DIR}/.env.example" "${ORIGINAL_SCRIPT_DIR}/.env.example"; do
        [[ -f "$example_file" ]] || continue
        example_value=$(read_env_value_from_file "$key" "$example_file" | tr -d '\n')
        [[ -n "${example_value//[[:space:]]/}" ]] || continue
        [[ "$value" == "$example_value" ]] && return 0
    done

    return 1
}

validate_required_security_profile() {
    local env_file="$1"
    local api_key memory_key access_level db_password database_url pg_password grafana_password redis_password
    api_key="$(get_env_value "$env_file" API_KEY)"
    memory_key="$(get_env_value "$env_file" MEMORY_ENCRYPTION_KEY)"
    access_level="$(get_env_value "$env_file" ACCESS_LEVEL)"
    database_url="$(get_env_value "$env_file" DATABASE_URL)"
    pg_password="$(get_env_value "$env_file" POSTGRES_PASSWORD)"
    grafana_password="$(get_env_value "$env_file" GRAFANA_ADMIN_PASSWORD)"
    redis_password="$(get_env_value "$env_file" REDIS_PASSWORD)"

    if is_weak_secret_value "$api_key"; then
        fail ".env güvenlik doğrulaması başarısız: API_KEY boş veya zayıf. Güçlü bir token tanımlayın."
    fi

    if [[ -z "$memory_key" ]]; then
        fail ".env güvenlik doğrulaması başarısız: MEMORY_ENCRYPTION_KEY boş. Geçerli Fernet anahtarı zorunludur."
    fi
    if ! python3 - "$memory_key" <<'PYFERNET'
import sys
from cryptography.fernet import Fernet
Fernet(sys.argv[1].encode())
PYFERNET
    then
        fail ".env güvenlik doğrulaması başarısız: MEMORY_ENCRYPTION_KEY geçerli Fernet anahtarı değil."
    fi

    if [[ "${access_level,,}" == "full" && "$ALLOW_FULL_ACCESS" != true ]]; then
        fail "ACCESS_LEVEL=full yalnız açık onayla kullanılabilir. Riskleri kabul ediyorsanız --i-understand-full-access bayrağını verin."
    fi

    db_password="$(python3 - "$database_url" <<'PYDB' 2>/dev/null || true
import sys
from urllib.parse import urlparse, unquote
url = sys.argv[1]
if url:
    print(unquote(urlparse(url).password or ""))
PYDB
)"
    if [[ -n "$database_url" ]] && is_weak_secret_value "$db_password"; then
        fail ".env güvenlik doğrulaması başarısız: DATABASE_URL içindeki veritabanı parolası boş veya zayıf."
    fi
    if is_weak_secret_value "$pg_password"; then
        fail ".env güvenlik doğrulaması başarısız: POSTGRES_PASSWORD boş veya zayıf."
    fi
    if is_weak_secret_value "$grafana_password"; then
        fail ".env güvenlik doğrulaması başarısız: GRAFANA_ADMIN_PASSWORD boş veya zayıf."
    fi
    if is_weak_secret_value "$redis_password"; then
        fail ".env güvenlik doğrulaması başarısız: REDIS_PASSWORD boş veya zayıf."
    fi
}

sync_database_env_chain_after_setup() {
    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; PostgreSQL dotenv zinciri Python senkronizasyonu atlandı."
        return 0
    fi

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_database_passwords.py" ]]; then
        warn "scripts.sync_database_passwords bulunamadı; PostgreSQL dotenv zinciri Python senkronizasyonu atlandı."
        return 0
    fi

    info "Ortam değişkenlerindeki PostgreSQL şifreleri tek Python helper ile eşitleniyor..."
    if (
        cd "$SCRIPT_DIR" && \
            uv run python -m scripts.sync_database_passwords --all-envs >/dev/null 2>&1 && \
            uv run python -m scripts.sync_database_passwords --remove-explicit-urls >/dev/null 2>&1
    ); then
        ok ".env zincirindeki PostgreSQL şifreleri kalıcı olarak eşitlendi."
    else
        warn "PostgreSQL dotenv zinciri Python senkronizasyonu tamamlanamadı; gerekirse manuel çalıştırın: "\
            "uv run python -m scripts.sync_database_passwords --all-envs && uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    fi
}

setup_env_file() {
    step ".env Yapılandırması"
    ENV_FILE="$SCRIPT_DIR/.env"
    EXAMPLE_FILE="$SCRIPT_DIR/.env.example"

    ADVANCED_ENV_FILE="$SCRIPT_DIR/.env.advanced"
    ADVANCED_EXAMPLE_FILE="$SCRIPT_DIR/.env.advanced.example"
    PRODUCTION_ENV_FILE="$SCRIPT_DIR/.env.production"
    PRODUCTION_EXAMPLE_FILE="$SCRIPT_DIR/.env.production.example"

    # .env.production eksikse example üzerinden oluştur. Secret değerleri
    # ensure_auto_secrets sonrasında propagate_shared_secrets_to_env_variants
    # ile .env dosyasından senkronize edilir.
    if [[ ! -f "$PRODUCTION_ENV_FILE" && -f "$PRODUCTION_EXAMPLE_FILE" ]]; then
        install -m 600 "$PRODUCTION_EXAMPLE_FILE" "$PRODUCTION_ENV_FILE"
        ok ".env.production dosyası .env.production.example'dan oluşturuldu."
    fi

    # .env.advanced eksikse example üzerinden oluştur. Secret değerleri
    # ensure_auto_secrets sonrasında propagate_shared_secrets_to_env_variants
    # ile .env dosyasından senkronize edilir.
    if [[ ! -f "$ADVANCED_ENV_FILE" && -f "$ADVANCED_EXAMPLE_FILE" ]]; then
        cp "$ADVANCED_EXAMPLE_FILE" "$ADVANCED_ENV_FILE"
        ok ".env.advanced dosyası .env.advanced.example'dan oluşturuldu."
    fi

    if [[ -f "$ENV_FILE" ]]; then
        ok ".env dosyası zaten mevcut — varsayılanlar ve güvenlik anahtarları kontrol ediliyor."
        ensure_sidar_env_default "$ENV_FILE"
        ensure_database_url_defaults "$ENV_FILE"
        ensure_rag_vector_backend_pgvector "$ENV_FILE"
        harden_database_credentials "$ENV_FILE"
        ensure_local_service_host_defaults "$ENV_FILE"
        ensure_auto_secrets "$ENV_FILE"
        propagate_shared_secrets_to_env_variants "$ENV_FILE"
        validate_required_security_profile "$ENV_FILE"
        configure_gpu_env_defaults "$ENV_FILE"
        collect_api_keys_interactive "$ENV_FILE"
        report_env_api_key_status "$ENV_FILE"
        sync_database_env_chain_after_setup
        validate_runtime_env_loading
        return
    fi

    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        warn ".env.example bulunamadı — .env oluşturulamadı. Manuel olarak oluşturun."
        return
    fi

    cp "$EXAMPLE_FILE" "$ENV_FILE"
    ok ".env dosyası .env.example'dan oluşturuldu."
    ensure_sidar_env_default "$ENV_FILE"
    ensure_database_url_defaults "$ENV_FILE"
    ensure_rag_vector_backend_pgvector "$ENV_FILE"
    harden_database_credentials "$ENV_FILE"
    ensure_local_service_host_defaults "$ENV_FILE"

    sync_postgres_env_with_database_url "$ENV_FILE"

    # Güvenlik secret'larını üret/doğrula (her iki yolda da çalışan üst-düzey fonksiyon)
    ensure_auto_secrets "$ENV_FILE"
    propagate_shared_secrets_to_env_variants "$ENV_FILE"
    validate_required_security_profile "$ENV_FILE"

    # GPU tespitine göre USE_GPU/REQUIRE_GPU/GPU_MIXED_PRECISION/COMPOSE_PROFILES
    # değerlerini .env içinde uyumlu hale getir ve .env.development/.env.advanced'e yay.
    configure_gpu_env_defaults "$ENV_FILE"

    collect_api_keys_interactive "$ENV_FILE"
    report_env_api_key_status "$ENV_FILE"
    sync_database_env_chain_after_setup
    validate_runtime_env_loading
}
