#!/usr/bin/env bash
# Sidar installer phase: Docker service startup and validation orchestration.

phase06_docker_daemon_gate_or_fail() {
    local max_attempts=3
    local attempt=1
    local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"

    while (( attempt <= max_attempts )); do
        if docker info >/dev/null 2>&1; then
            if (( attempt > 1 )); then
                ok "Docker daemon doğrulaması ${attempt}. denemede başarılı."
            fi
            return 0
        fi

        warn "Phase 06 öncesi Docker daemon erişilemiyor (deneme ${attempt}/${max_attempts})."
        if [[ "$WSL2" == true && ("${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "$integration_autofix_sentinel") ]]; then
            info "Bu oturumda WSL integration autofix uygulandı; Docker Desktop açılışı gecikmiş olabilir."
        fi

        if (( attempt >= max_attempts )); then
            break
        fi

        if [[ "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
            info "Etkileşimsiz mod: yeniden deneme öncesi 10sn bekleniyor."
            sleep 10
        else
            info "Lütfen Docker Desktop'ı açın/yeniden başlatın, sonra yeniden deneme yapılacak."
            clear_stdin_buffer
            read -r -p "Devam etmek için [ENTER] tuşuna basın..." 2>/dev/tty
        fi

        ((attempt += 1))
    done

    fail "Phase 06 öncesi Docker daemon doğrulanamadı (${max_attempts} deneme). Docker Compose adımlarına geçilmeden kurulum durduruldu."
}


sidar_add_unique_value() {
    local array_name="$1"
    local value="${2:-}"
    local existing=""

    [[ -n "$value" ]] || return 0
    local -n target_array="$array_name"
    for existing in "${target_array[@]}"; do
        [[ "$existing" == "$value" ]] && return 0
    done
    target_array+=("$value")
}

sidar_normalize_compose_project_name() {
    local raw="${1:-}"
    raw="${raw,,}"
    raw="$(printf '%s' "$raw" | sed -E 's/[^a-z0-9_-]+/-/g; s/^-+//; s/-+$//')"
    printf '%s' "$raw"
}

sidar_volume_name_matches_suffix() {
    local docker_volume_name="$1"
    local volume_suffix="$2"
    local compose_project_candidate="${3:-}"
    local normalized_project=""
    local lower_volume_name="${docker_volume_name,,}"
    local lower_volume_suffix="${volume_suffix,,}"

    [[ -n "$docker_volume_name" && -n "$volume_suffix" ]] || return 1

    if [[ "$docker_volume_name" == "$volume_suffix" || "$lower_volume_name" == "$lower_volume_suffix" ]]; then
        return 0
    fi

    if [[ -n "$compose_project_candidate" ]]; then
        normalized_project="$(sidar_normalize_compose_project_name "$compose_project_candidate")"
        if [[ "$docker_volume_name" == "${compose_project_candidate}_${volume_suffix}" || "$lower_volume_name" == "${compose_project_candidate,,}_${lower_volume_suffix}" ]]; then
            return 0
        fi
        if [[ -n "$normalized_project" && ( "$lower_volume_name" == "${normalized_project}_${lower_volume_suffix}" || "$lower_volume_name" == "${normalized_project}-${lower_volume_suffix//_/-}" ) ]]; then
            return 0
        fi
    fi

    # Sidar'ın eski/yeniden klonlanmış dizinlerinden kalmış, compose label'ı olmayan
    # volume adlarını da yakala. Başka projelerin genel postgres_data volume'lerini
    # proje adı bilinçli olarak Sidar ile ilişkilendirilemediği sürece kapsam dışında bırakır.
    if [[ "$lower_volume_name" =~ (^|[_-])sidar([_-].*)?([_-])(postgres|pg)([_-])?data$ ]]; then
        return 0
    fi

    return 1
}

sidar_volume_has_matching_compose_labels() {
    local docker_volume_name="$1"
    local volume_suffix="$2"
    shift 2
    local -a compose_project_candidates=("$@")
    local label_output=""
    local label_project=""
    local label_volume=""
    local candidate=""

    label_output=$(docker volume inspect "$docker_volume_name" --format '{{ index .Labels "com.docker.compose.project" }}|{{ index .Labels "com.docker.compose.volume" }}' 2>/dev/null || true)
    [[ -n "$label_output" ]] || return 1
    label_project="${label_output%%|*}"
    label_volume="${label_output#*|}"
    [[ "$label_project" != "<no value>" ]] || label_project=""
    [[ "$label_volume" != "<no value>" ]] || label_volume=""

    [[ "$label_volume" == "$volume_suffix" || "${label_volume,,}" == "${volume_suffix,,}" ]] || return 1
    for candidate in "${compose_project_candidates[@]}"; do
        if [[ "$label_project" == "$candidate" || "${label_project,,}" == "${candidate,,}" || "${label_project,,}" == "$(sidar_normalize_compose_project_name "$candidate")" ]]; then
            return 0
        fi
    done
    return 1
}

sidar_discover_postgres_volumes() {
    local compose_project_name="${1:-}"
    shift || true
    local -a candidate_volume_suffixes=("$@")
    local -a compose_project_candidates=()
    local docker_volume_name=""
    local volume_suffix=""
    local project_candidate=""
    local script_project_name=""
    local matched_volume=false

    sidar_add_unique_value compose_project_candidates "$compose_project_name"
    sidar_add_unique_value compose_project_candidates "$(sidar_normalize_compose_project_name "$compose_project_name")"
    script_project_name="$(basename "$SCRIPT_DIR")"
    sidar_add_unique_value compose_project_candidates "$script_project_name"
    sidar_add_unique_value compose_project_candidates "$(sidar_normalize_compose_project_name "$script_project_name")"
    sidar_add_unique_value compose_project_candidates "sidar"

    if mapfile -t docker_volume_names < <(docker volume ls --format '{{.Name}}' 2>/dev/null); then
        for docker_volume_name in "${docker_volume_names[@]}"; do
            matched_volume=false
            for volume_suffix in "${candidate_volume_suffixes[@]}"; do
                for project_candidate in "${compose_project_candidates[@]}"; do
                    if sidar_volume_name_matches_suffix "$docker_volume_name" "$volume_suffix" "$project_candidate"; then
                        printf '%s\n' "$docker_volume_name"
                        matched_volume=true
                        break 2
                    fi
                done
                if sidar_volume_has_matching_compose_labels "$docker_volume_name" "$volume_suffix" "${compose_project_candidates[@]}"; then
                    printf '%s\n' "$docker_volume_name"
                    matched_volume=true
                    break
                fi
            done
            if [[ "$matched_volume" == true ]]; then
                continue
            fi
        done
    fi
}

# DB parola hardening sonrası PostgreSQL volume sıfırlamanın mevcut SIDAR_ENV
# için güvenli olup olmadığına karar verir. SIDAR_ENV tanımsız/boşsa (ör.
# eksik/yarım .env dosyası) güvenli tarafta kalıp reddeder — "development"a
# sessizce düşmez. Bu karar birden fazla çağıran (parola değişimi sonrası ilk
# reset denemesi ve smoke test öncesi zorunlu reset doğrulaması) tarafından
# paylaşılır; ikisi de aynı güvenlik frenine tabi olmalıdır.
sidar_postgres_volume_reset_allowed_for_env() {
    local env_file="$1"
    local sidar_env=""
    if [[ -f "$env_file" ]]; then
        sidar_env=$(read_env_value_from_file "SIDAR_ENV" "$env_file")
    fi
    sidar_env=$(echo "$sidar_env" | tr -d '"'\''[:space:]')

    local allow_production_volume_reset="${ALLOW_PRODUCTION_DB_VOLUME_RESET:-0}"
    case "$sidar_env" in
        development|dev|local|test)
            return 0
            ;;
        production|prod|staging|preprod)
            if [[ "$allow_production_volume_reset" != "1" ]]; then
                warn "DB parola hardening algılandı ancak SIDAR_ENV=${sidar_env} olduğu için PostgreSQL volume otomatik sıfırlanmadı (güvenlik freni)."
                warn "Sadece bilinçli operasyonlarda ALLOW_PRODUCTION_DB_VOLUME_RESET=1 ile açıkça izin verin."
                return 1
            fi
            warn "ALLOW_PRODUCTION_DB_VOLUME_RESET=1 verildi; SIDAR_ENV=${sidar_env} için PostgreSQL volume sıfırlama güvenlik freni operatör onayıyla bypass edildi."
            return 0
            ;;
        "")
            warn "SIDAR_ENV tanımlı değil veya boş; veri kaybını önlemek için PostgreSQL volume otomatik sıfırlanmadı (güvenli varsayılan: reddet)."
            warn "Geliştirme ortamındaysanız .env dosyanızda SIDAR_ENV=development ayarlayın."
            return 1
            ;;
        *)
            warn "SIDAR_ENV='${sidar_env}' tanınmadı; veri kaybını önlemek için PostgreSQL volume otomatik sıfırlanmadı."
            return 1
            ;;
    esac
}

maybe_reset_postgres_volume_after_password_hardening() {
    local -a compose_cmd=()
    while [[ $# -gt 0 ]]; do
        if [[ "$1" == "--" ]]; then
            shift
            break
        fi
        compose_cmd+=("$1")
        shift
    done
    local -a services=("$@")
    local reset_attempted=false

    if [[ "$DB_PASSWORD_HARDENED" != true || "$POSTGRES_VOLUME_RESET_DONE" == true ]]; then
        return 0
    fi

    local includes_postgres=false
    for service in "${services[@]}"; do
        if [[ "$service" == "postgres" ]]; then
            includes_postgres=true
            break
        fi
    done
    [[ "$includes_postgres" == true ]] || return 0

    local env_file="$SCRIPT_DIR/.env"
    sidar_postgres_volume_reset_allowed_for_env "$env_file" || return 0

    if [[ "${AUTO_RESET_POSTGRES_VOLUME_ON_PASSWORD_CHANGE:-1}" != "1" ]]; then
        warn "AUTO_RESET_POSTGRES_VOLUME_ON_PASSWORD_CHANGE=1 olmadığı için PostgreSQL volume otomatik sıfırlanmadı."
        return 0
    fi

    if ! command -v docker &>/dev/null; then
        warn "DB parola hardening algılandı ancak docker CLI bulunamadı; PostgreSQL volume otomatik sıfırlanamadı."
        return 0
    fi

    local -a candidate_volume_suffixes=()
    local compose_project_name="${COMPOSE_PROJECT_NAME:-}"
    local compose_arg=""
    local consume_next_as_project_name=false
    for compose_arg in "${compose_cmd[@]}"; do
        if [[ "$consume_next_as_project_name" == true ]]; then
            compose_project_name="$compose_arg"
            consume_next_as_project_name=false
            continue
        fi
        case "$compose_arg" in
            -p|--project-name)
                consume_next_as_project_name=true
                ;;
            -p=*|--project-name=*)
                compose_project_name="${compose_arg#*=}"
                ;;
        esac
    done

    if [[ -z "$compose_project_name" ]]; then
        compose_project_name=$(read_env_value_from_file "COMPOSE_PROJECT_NAME" "$env_file")
    fi
    compose_project_name=$(echo "${compose_project_name:-}" | tr -d '"'\''[:space:]')
    if mapfile -t compose_volumes < <("${compose_cmd[@]}" config --volumes 2>/dev/null); then
        for volume_name in "${compose_volumes[@]}"; do
            if [[ "$volume_name" =~ (^|_)postgres_data$ ]]; then
                candidate_volume_suffixes+=("$volume_name")
            fi
        done
    fi

    # docker compose config --volumes çoğunlukla kısa adı (örn: postgres_data) döndürür.
    # Gerçek Docker volume adı ise çoğu zaman proje önekli olur (örn: sidar_postgres_data).
    # Bu nedenle kısa adları suffix olarak ele alıp docker volume ls çıktısından gerçek adları çözüyoruz.
    if [[ ${#candidate_volume_suffixes[@]} -eq 0 ]]; then
        candidate_volume_suffixes+=("postgres_data")
    fi

    local -a existing_pg_volumes=()
    if mapfile -t existing_pg_volumes < <(sidar_discover_postgres_volumes "$compose_project_name" "${candidate_volume_suffixes[@]}"); then
        :
    fi

    if [[ ${#existing_pg_volumes[@]} -gt 1 ]]; then
        local -A unique_existing_pg_volumes=()
        local -a deduped_existing_pg_volumes=()
        for volume_name in "${existing_pg_volumes[@]}"; do
            if [[ -z "${unique_existing_pg_volumes[$volume_name]:-}" ]]; then
                unique_existing_pg_volumes["$volume_name"]=1
                deduped_existing_pg_volumes+=("$volume_name")
            fi
        done
        existing_pg_volumes=("${deduped_existing_pg_volumes[@]}")
    fi

    if [[ ${#existing_pg_volumes[@]} -eq 0 ]]; then
        if "${compose_cmd[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
            if mapfile -t existing_pg_volumes < <(sidar_discover_postgres_volumes "$compose_project_name" "${candidate_volume_suffixes[@]}"); then
                :
            fi
            if [[ ${#existing_pg_volumes[@]} -eq 0 ]]; then
                POSTGRES_VOLUME_RESET_DONE=true
                return 0
            fi
            warn "Fallback sonrası PostgreSQL volume adayları bulundu: ${existing_pg_volumes[*]}"
        else
            warn "docker compose down --volumes --remove-orphans fallback'i çalıştırılamadı; volume adı eşleşmesi bulunamazsa kurulum güvenli uyarıyla devam edecek."
        fi
    fi

    local should_reset="E"
    if [[ "$AUTO_RESET_POSTGRES_VOLUMES" == "true" ]]; then
        should_reset="E"
        info "AUTO_INSTALL: RESET_DB=true olduğu için PostgreSQL volume sıfırlama onayı otomatik verildi."
    elif [[ "$AUTO_RESET_POSTGRES_VOLUMES" == "false" ]]; then
        should_reset="H"
        info "AUTO_INSTALL: RESET_DB=false olduğu için PostgreSQL volume sıfırlama atlandı."
    elif [[ "$NO_INTERACTION" != true ]]; then
        should_reset=$(prompt_yes_no_with_timeout_default_no \
            "DB şifresi güncellendi. Eski PostgreSQL volume'leri (${existing_pg_volumes[*]}) şimdi sıfırlansın mı? [e/H] ")
    fi

    local strict_postgres_reset_on_password_change="${STRICT_POSTGRES_VOLUME_RESET_ON_PASSWORD_CHANGE:-${STRICT_POSTGRES_VOLUME_RESET:-0}}"

    case "${should_reset:-E}" in
        E|e)
            reset_attempted=true
            warn "DB parola hardening sonrası eski kimlik bilgisi riskine karşı PostgreSQL volume sıfırlanıyor: ${existing_pg_volumes[*]}"
            if ! backup_postgres_before_volume_reset "${compose_cmd[@]}"; then
                warn "PostgreSQL yedeği alınamadı; volume yine de sıfırlanıyor (geliştirme ortamı — veri kurtarılamaz durumda)."
            fi
            local -a postgres_service_container_ids=()
            if mapfile -t postgres_service_container_ids < <("${compose_cmd[@]}" ps -q postgres 2>/dev/null); then
                if [[ ${#postgres_service_container_ids[@]} -gt 0 ]]; then
                    warn "postgres servisine ait mevcut container(lar) doğrudan kaldırılıyor."
                    docker stop "${postgres_service_container_ids[@]}" >/dev/null 2>&1 || true
                    docker rm -f "${postgres_service_container_ids[@]}" >/dev/null 2>&1 || warn "postgres container kaldırma adımı tamamlanamadı."
                fi
            fi
            if ! "${compose_cmd[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
                warn "docker compose down --volumes --remove-orphans komutu başarısız oldu; volume kilidi manuel olarak çözülecek."
            fi
            if [[ "$FORCE_POSTGRES_VOLUME_CLEANUP" == true ]]; then
                warn "Agresif container temizliği etkin: projeye ait asılı kalan container'lar zorla kaldırılıyor."
                local -a project_container_ids=()
                if [[ -n "$compose_project_name" ]]; then
                    if mapfile -t project_container_ids < <(docker ps -a --filter "label=com.docker.compose.project=${compose_project_name}" --format '{{.ID}}' 2>/dev/null); then
                        if [[ ${#project_container_ids[@]} -gt 0 ]]; then
                            docker rm -f "${project_container_ids[@]}" >/dev/null 2>&1 || warn "Projeye ait bazı container'lar zorla kaldırılamadı."
                        fi
                    fi
                fi
            fi
            local removed_any=false
            for volume_name in "${existing_pg_volumes[@]}"; do
                local -a volume_container_ids=()
                if mapfile -t volume_container_ids < <(docker ps -a --filter "volume=${volume_name}" --format '{{.ID}}' 2>/dev/null); then
                    if [[ ${#volume_container_ids[@]} -gt 0 ]]; then
                        warn "Volume bağlı container(lar) bulundu (${volume_name}); zorla kaldırılıyor."
                        docker rm -f "${volume_container_ids[@]}" >/dev/null 2>&1 || warn "Volume kullanan container'lar kaldırılamadı: ${volume_name}"
                    fi
                fi
                if [[ "$FORCE_POSTGRES_VOLUME_CLEANUP" == true ]]; then
                    local -a dangling_by_name_container_ids=()
                    if mapfile -t dangling_by_name_container_ids < <(docker ps -a --filter "name=${volume_name}" --format '{{.ID}}' 2>/dev/null); then
                        if [[ ${#dangling_by_name_container_ids[@]} -gt 0 ]]; then
                            warn "Agresif mod: volume adıyla eşleşen asılı container(lar) kaldırılıyor (${volume_name})."
                            docker rm -f "${dangling_by_name_container_ids[@]}" >/dev/null 2>&1 || warn "Volume adına göre bulunan container'lar kaldırılamadı: ${volume_name}"
                        fi
                    fi
                fi
                if docker volume rm "$volume_name" -f >/dev/null 2>&1; then
                    ok "PostgreSQL volume temizlendi: ${volume_name}"
                    removed_any=true
                else
                    warn "PostgreSQL volume otomatik silinemedi (${volume_name}). Geliştirme ortamında manuel olarak sıfırlayın."
                fi
            done
            if [[ "$removed_any" == true ]]; then
                POSTGRES_VOLUME_RESET_DONE=true
            fi
            ;;
        *)
            warn "PostgreSQL volume sıfırlama kullanıcı tercihiyle atlandı; eski parola kaynaklı auth hatası oluşabilir."
            ;;
    esac

    if [[ "$POSTGRES_VOLUME_RESET_DONE" == true ]]; then
        return 0
    fi

    if [[ "$reset_attempted" == true && "${DB_PASSWORD_HARDENED:-false}" == true ]]; then
        warn "Volume temizliği tamamlanamadı; kilitli Docker artefaktlarını çözmek için docker system prune -f çalıştırılıyor."
        docker system prune -f >/dev/null 2>&1 || warn "docker system prune -f adımı tamamlanamadı."

        local removed_after_prune=false
        for volume_name in "${existing_pg_volumes[@]}"; do
            if docker volume rm "$volume_name" -f >/dev/null 2>&1; then
                ok "PostgreSQL volume prune sonrası temizlendi: ${volume_name}"
                removed_after_prune=true
            fi
        done
        if [[ "$removed_after_prune" == true ]]; then
            POSTGRES_VOLUME_RESET_DONE=true
            return 0
        fi
    fi

    warn "PostgreSQL volume sıfırlama tamamlanamadı; bağlantı hatası olursa docker compose down --volumes --remove-orphans && docker volume rm sidar_postgres_data -f komutlarını çalıştırın."
    if [[ "$reset_attempted" == true ]]; then
        if [[ "$strict_postgres_reset_on_password_change" == "1" ]]; then
            return 1
        fi
        warn "Kurulum durdurulmadan devam ediliyor (STRICT_POSTGRES_VOLUME_RESET=1 veya STRICT_POSTGRES_VOLUME_RESET_ON_PASSWORD_CHANGE=1 ayarlanırsa bu durumda fail edilir)."
        return 0
    fi
    return 0
}

backup_postgres_before_volume_reset() {
    local -a compose_cmd=("$@")
    local postgres_container_id=""
    local backup_dir="$SCRIPT_DIR/backups"
    local backup_file=""
    local dump_error_file=""
    local dump_ok=false
    local candidate_db_user=""
    local -a candidate_db_users=()
    local candidate_db_users_seen="|"
    local env_db_user=""
    local env_postgres_user=""

    if ! command -v docker &>/dev/null; then
        warn "Docker CLI bulunamadı; volume sıfırlama öncesi PostgreSQL yedeği alınamadı."
        return 0
    fi

    if mapfile -t _postgres_container_ids < <("${compose_cmd[@]}" ps -q postgres 2>/dev/null); then
        if [[ ${#_postgres_container_ids[@]} -gt 0 ]]; then
            postgres_container_id="${_postgres_container_ids[0]}"
        fi
    fi

    if [[ -z "$postgres_container_id" ]]; then
        warn "postgres container bulunamadı; volume sıfırlama öncesi pg_dumpall yedeği alınamadı (kurulum otomatik devam edecek)."
        return 1
    fi

    mkdir -p "$backup_dir"
    backup_file="$backup_dir/postgres_before_volume_reset_$(date +%Y%m%d_%H%M%S).sql"
    dump_error_file="$(mktemp)"

    # Önce container içi yapılandırmadan ve .env dosyasından özel kullanıcı adlarını dene.
    env_postgres_user="$(docker exec "$postgres_container_id" sh -lc 'printenv POSTGRES_USER' 2>/dev/null || true)"
    env_postgres_user="$(echo "$env_postgres_user" | tr -d '"'\''[:space:]')"
    if [[ -n "$env_postgres_user" ]] && [[ "$candidate_db_users_seen" != *"|${env_postgres_user}|"* ]]; then
        candidate_db_users+=("$env_postgres_user")
        candidate_db_users_seen+="${env_postgres_user}|"
    fi

    if [[ -n "${ENV_FILE:-}" && -f "${ENV_FILE:-}" ]]; then
        env_postgres_user="$(read_env_value_from_file "POSTGRES_USER" "$ENV_FILE")"
        env_postgres_user="$(echo "$env_postgres_user" | tr -d '"'\''[:space:]')"
        if [[ -n "$env_postgres_user" ]] && [[ "$candidate_db_users_seen" != *"|${env_postgres_user}|"* ]]; then
            candidate_db_users+=("$env_postgres_user")
            candidate_db_users_seen+="${env_postgres_user}|"
        fi
        local env_database_url=""
        env_database_url="$(read_env_value_from_file "DATABASE_URL" "$ENV_FILE")"
        if [[ "$env_database_url" =~ ^postgresql(\+asyncpg)?://([^:@/]+):([^@/]+)@ ]]; then
            env_db_user="${BASH_REMATCH[2]}"
        fi
        env_db_user="$(echo "$env_db_user" | tr -d '"'\''[:space:]')"
        if [[ -n "$env_db_user" ]] && [[ "$candidate_db_users_seen" != *"|${env_db_user}|"* ]]; then
            candidate_db_users+=("$env_db_user")
            candidate_db_users_seen+="${env_db_user}|"
        fi
    fi

    # Varsayılan fallback kullanıcılarını en sona ekle.
    if [[ "$candidate_db_users_seen" != *"|postgres|"* ]]; then
        candidate_db_users+=("postgres")
        candidate_db_users_seen+="postgres|"
    fi
    if [[ "$candidate_db_users_seen" != *"|sidar|"* ]]; then
        candidate_db_users+=("sidar")
        candidate_db_users_seen+="sidar|"
    fi

    for candidate_db_user in "${candidate_db_users[@]}"; do
        if docker exec "$postgres_container_id" sh -lc "pg_dumpall -U ${candidate_db_user}" >"$backup_file" 2>"$dump_error_file"; then
            local backup_size=0
            backup_size=$(stat -c%s "$backup_file" 2>/dev/null || echo 0)
            if [[ -s "$backup_file" && "$backup_size" -gt 512 ]] && grep -qE '^(CREATE|INSERT|--.*PostgreSQL)' "$backup_file" 2>/dev/null; then
                dump_ok=true
                break
            fi
        fi
    done

    if [[ "$dump_ok" == true ]]; then
        ok "PostgreSQL hızlı yedek alındı: ${backup_file}"
        info "Eski verileriniz ${backup_file} olarak kaydedildi, volume sıfırlanıyor."
        rm -f "$dump_error_file"
        return 0
    fi

    rm -f "$backup_file"
    warn "Volume sıfırlama öncesi pg_dumpall yedeği alınamadı. Detay: $(cat "$dump_error_file" 2>/dev/null || echo 'bilinmeyen_hata')"
    rm -f "$dump_error_file"
    return 1
}

wait_for_postgres_ready_after_docker_start() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"
    local max_attempts="${6:-30}"
    local sleep_seconds="${7:-2}"
    local stable_auth_checks_required="${POSTGRES_READY_STABLE_AUTH_CHECKS:-2}"
    local stable_auth_checks_passed=0

    info "PostgreSQL'in tabloları ve kullanıcıları oluşturması bekleniyor (${db_host}:${db_port}/${db_name})..."
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        if pg_isready -h "$db_host" -p "$db_port" -U "$db_user" -d "$db_name" >/dev/null 2>&1; then
            local auth_rc=0
            verify_postgres_auth "$db_host" "$db_port" "$db_user" "$db_name" "$db_password" || auth_rc=$?
            case "$auth_rc" in
                0)
                    ((stable_auth_checks_passed+=1))
                    if (( stable_auth_checks_passed >= stable_auth_checks_required )); then
                        ok "PostgreSQL tam olarak hazır ve kimlik doğrulaması başarılı."
                        return 0
                    fi
                    info "Kimlik doğrulaması başarılı (denge kontrolü ${stable_auth_checks_passed}/${stable_auth_checks_required}); kısa bir doğrulama daha yapılacak..."
                    ;;
                10)
                    stable_auth_checks_passed=0
                    warn "PostgreSQL henüz hazır değil veya parola senkronize değil (${attempt}/${max_attempts}): ${POSTGRES_AUTH_CHECK_ERROR:-password authentication failed}"
                    ;;
                2)
                    stable_auth_checks_passed=0
                    warn "PostgreSQL erişilebilir, ancak psql/asyncpg ile auth doğrulaması yapılamadı (${attempt}/${max_attempts})."
                    warn "Auth doğrulaması yapılamadığından DB hazır kabul ediliyor; Alembic adımında yeniden doğrulanacak."
                    return 0
                    ;;
                *)
                    stable_auth_checks_passed=0
                    warn "PostgreSQL bağlantı kontrolü başarısız (${attempt}/${max_attempts}): ${POSTGRES_AUTH_CHECK_ERROR:-bilinmeyen_hata}"
                    ;;
            esac
        else
            stable_auth_checks_passed=0
            info "⏳ Veritabanı başlatılıyor... (${attempt}/${max_attempts})"
        fi
        sleep "$sleep_seconds"
    done

    warn "PostgreSQL ${max_attempts} denemede tam hazır hale gelmedi."
    return 1
}

wait_for_redis_ready_after_docker_start() {
    local env_file="$SCRIPT_DIR/.env"
    local redis_url=""
    local redis_host="localhost"
    local redis_port="6379"
    local -a python_cmd=()

    if [[ -f "$env_file" ]]; then
        redis_url=$(read_env_value_from_file "REDIS_URL" "$env_file")
    fi
    if [[ -z "$redis_url" ]]; then
        redis_url="redis://localhost:6379/0"
    fi

    if command -v python3 &>/dev/null; then
        python_cmd=(python3)
    elif command -v python &>/dev/null; then
        python_cmd=(python)
    fi

    if [[ ${#python_cmd[@]} -gt 0 ]]; then
        if mapfile -t redis_conn < <("${python_cmd[@]}" - "$redis_url" <<'PY'
from urllib.parse import urlparse
import sys

url = (sys.argv[1] or "").strip() or "redis://localhost:6379/0"
parsed = urlparse(url)
print(parsed.hostname or "localhost")
print(str(parsed.port or 6379))
PY
); then
            redis_host="${redis_conn[0]:-localhost}"
            redis_port="${redis_conn[1]:-6379}"
        fi
    fi

    info "Redis hazır olana kadar bekleniyor (${redis_host}:${redis_port})..."
    for _ in {1..30}; do
        if command -v redis-cli &>/dev/null; then
            if redis-cli -h "$redis_host" -p "$redis_port" ping 2>/dev/null | grep -q "PONG"; then
                ok "Redis erişilebilir hale geldi."
                return 0
            fi
        elif command -v timeout &>/dev/null; then
            # Hafif fallback: her döngüde python process spawn etmek yerine bash /dev/tcp kullan.
            if timeout 1 bash -c "</dev/tcp/$redis_host/$redis_port" >/dev/null 2>&1; then
                ok "Redis erişilebilir hale geldi."
                return 0
            fi
        elif [[ ${#python_cmd[@]} -gt 0 ]]; then
            # timeout yoksa son çare olarak tek TCP connect kontrolü.
            if "${python_cmd[@]}" - "$redis_host" "$redis_port" <<'PY' >/dev/null 2>&1
import socket
import sys
host = sys.argv[1]
port = int(sys.argv[2])
with socket.create_connection((host, port), timeout=1.0):
    pass
PY
            then
                ok "Redis erişilebilir hale geldi."
                return 0
            fi
        else
            warn "redis-cli veya python bulunamadı; Redis hazır kontrolü atlanıyor."
            return 0
        fi
        sleep 2
    done

    warn "Redis ${redis_host}:${redis_port} 60 saniye içinde hazır olmadı."
    return 1
}

verify_postgres_auth_with_psql() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"
    POSTGRES_AUTH_CHECK_ERROR=""

    if ! command -v psql &>/dev/null; then
        POSTGRES_AUTH_CHECK_ERROR="psql_missing"
        return 2
    fi

    local psql_output=""
    if psql_output=$(
        PGPASSWORD="$db_password" psql \
            "host=$db_host port=$db_port user=$db_user dbname=$db_name connect_timeout=5" \
            -w \
            -tAc "SELECT 1" 2>&1
    ); then
        return 0
    fi

    POSTGRES_AUTH_CHECK_ERROR="$psql_output"
    if [[ "$psql_output" == *"password authentication failed"* ]]; then
        return 10
    fi
    return 1
}

verify_postgres_auth_with_python() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"
    local -a py_cmd=()
    local py_output=""
    POSTGRES_AUTH_CHECK_ERROR=""

    if command -v python3 &>/dev/null; then
        py_cmd=(python3)
    elif command -v python &>/dev/null; then
        py_cmd=(python)
    else
        POSTGRES_AUTH_CHECK_ERROR="python_missing"
        return 2
    fi

    if py_output=$("${py_cmd[@]}" - "$db_host" "$db_port" "$db_user" "$db_name" "$db_password" <<'PY' 2>&1
import asyncio
import sys

host, port, user, database, password = sys.argv[1:6]

async def main():
    try:
        import asyncpg
    except Exception as exc:
        print(f"asyncpg_missing:{exc}")
        raise SystemExit(2)

    try:
        conn = await asyncpg.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=database,
            timeout=5,
        )
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        print("ok")
        raise SystemExit(0)
    except Exception as exc:
        print(str(exc))
        raise

try:
    asyncio.run(main())
except SystemExit:
    raise
except Exception:
    raise SystemExit(1)
PY
); then
        return 0
    fi

    local py_rc=$?
    POSTGRES_AUTH_CHECK_ERROR="$py_output"
    if [[ "$py_output" == *"password authentication failed"* || "$py_output" == *"InvalidPasswordError"* ]]; then
        return 10
    fi
    if [[ "$py_rc" -eq 2 ]]; then
        return 2
    fi
    return 1
}

verify_postgres_auth() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local db_password="$5"

    verify_postgres_auth_with_psql "$db_host" "$db_port" "$db_user" "$db_name" "$db_password"
    local auth_rc=$?
    if [[ "$auth_rc" -ne 2 ]]; then
        return "$auth_rc"
    fi

    verify_postgres_auth_with_python "$db_host" "$db_port" "$db_user" "$db_name" "$db_password"
    return $?
}

try_recover_postgres_password_with_alter_user() {
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_name="$4"
    local new_password="$5"
    shift 5
    local -a old_password_candidates=("$@")

    local candidate=""
    local escape_sql_literal_password="${new_password//\'/\'\'}"
    local escape_sql_identifier_user="${db_user//\"/\"\"}"
    local -A seen_candidates=()

    for candidate in "${old_password_candidates[@]}"; do
        [[ -n "$candidate" ]] || continue
        if [[ -n "${seen_candidates[$candidate]:-}" ]]; then
            continue
        fi
        seen_candidates["$candidate"]=1
        if [[ "$candidate" == "$new_password" ]]; then
            continue
        fi

        if verify_postgres_auth "$db_host" "$db_port" "$db_user" "$db_name" "$candidate"; then
            info "Eski parola ile erişim doğrulandı; ALTER USER ile parola güncellemesi deneniyor."

            if command -v psql &>/dev/null; then
                if PGPASSWORD="$candidate" psql \
                    "host=$db_host port=$db_port user=$db_user dbname=$db_name connect_timeout=5" \
                    -w \
                    -v ON_ERROR_STOP=1 \
                    -c "ALTER USER \"${escape_sql_identifier_user}\" WITH PASSWORD '${escape_sql_literal_password}';" \
                    >/dev/null 2>&1; then
                    ok "ALTER USER ile PostgreSQL parolası güncellendi."
                    return 0
                fi
            fi

            local -a py_cmd=()
            if command -v python3 &>/dev/null; then
                py_cmd=(python3)
            elif command -v python &>/dev/null; then
                py_cmd=(python)
            fi

            if [[ ${#py_cmd[@]} -gt 0 ]]; then
                if "${py_cmd[@]}" - "$db_host" "$db_port" "$db_user" "$db_name" "$candidate" "$new_password" <<'PY' >/dev/null 2>&1
import asyncio
import sys

host, port, user, database, old_password, new_password = sys.argv[1:7]

async def main():
    import asyncpg
    conn = await asyncpg.connect(
        host=host,
        port=int(port),
        user=user,
        password=old_password,
        database=database,
        timeout=5,
    )
    try:
        await conn.execute(f'ALTER USER "{user.replace(chr(34), chr(34)*2)}" WITH PASSWORD $1', new_password)
    finally:
        await conn.close()

asyncio.run(main())
PY
                then
                    ok "ALTER USER (python/asyncpg) ile PostgreSQL parolası güncellendi."
                    return 0
                fi
            fi
        fi
    done

    return 1
}


seed_rag_in_docker_after_startup() {
    if [[ "${SIDAR_INSTALL_TEST_MODE:-}" == "1" ]]; then
        info "Test modu: RAG warmup seed atlandı."
        return 0
    fi

    local seed_mode="${AUTO_SEED_RAG_DOCKER_WARMUP:-true}"
    seed_mode="$(normalize_bool "$seed_mode")"
    [[ -z "$seed_mode" ]] && seed_mode="true"

    if [[ "$seed_mode" != "true" ]]; then
        info "AUTO_SEED_RAG_DOCKER_WARMUP=${AUTO_SEED_RAG_DOCKER_WARMUP:-false}; Docker RAG warmup seed atlandı."
        return 0
    fi

    local -a compose_cmd=()
    local compose_profiles="${COMPOSE_PROFILES:-}"
    local seed_service="sidar-web"
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        compose_cmd=(docker-compose)
    else
        warn "Docker compose bulunamadı; RAG warmup seed atlandı. Manuel: docker compose run --rm --no-deps --entrypoint \"\" ${seed_service} uv run python -m scripts.seed_rag"
        return 0
    fi

    if [[ "$compose_profiles" == *"gpu"* ]]; then
        seed_service="sidar-web-gpu"
    fi

    info "RAG seed servisi aktif profillere göre seçildi: ${seed_service} (COMPOSE_PROFILES=${compose_profiles:-cpu})."
    info "Tam Docker modu: ilk açılış gecikmesini azaltmak için RAG/GraphRAG seed adımı çalıştırılıyor..."
    if (cd "$SCRIPT_DIR" && "${compose_cmd[@]}" run --rm --no-deps --entrypoint "" "$seed_service" uv run python -m scripts.seed_rag); then
        ok "Docker RAG/GraphRAG seed adımı tamamlandı."
    else
        warn "Docker RAG/GraphRAG seed adımı başarısız. Geçici container temizliği deneniyor..."
        (cd "$SCRIPT_DIR" && "${compose_cmd[@]}" rm -f -s "$seed_service" >/dev/null 2>&1) || true
        warn "Docker RAG/GraphRAG seed adımı başarısız. Manuel: ${compose_cmd[*]} run --rm --no-deps --entrypoint \"\" ${seed_service} uv run python -m scripts.seed_rag"
    fi
}

sidar_phase_local_migrations_and_models() {
    sidar_source_install_utils "ollama_models.sh"
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
        # DB migrasyonu öncesi servis hazırlığı: kullanıcı onayı bu aşamada alınır.
        prepare_docker_for_migrations
        local runtime_db_url=""
        local db_conn_info=""
        if resolve_runtime_database_url >/dev/null; then
            runtime_db_url="$RUNTIME_DATABASE_URL"
            db_conn_info=$("$(command -v python3 || command -v python)" - "$runtime_db_url" <<'PY'
from urllib.parse import urlparse, unquote
import sys

url = sys.argv[1].replace("postgresql+asyncpg://", "postgresql://", 1)
parsed = urlparse(url)
print("|".join([
    parsed.hostname or "127.0.0.1",
    str(parsed.port or 5432),
    unquote(parsed.username or "sidar"),
    unquote(parsed.password or ""),
    parsed.path.lstrip("/") or "sidar",
]))
PY
)
            ensure_postgres_databases_exist \
                "$(echo "$db_conn_info" | cut -d'|' -f1)" \
                "$(echo "$db_conn_info" | cut -d'|' -f2)" \
                "$(echo "$db_conn_info" | cut -d'|' -f3)" \
                "$(echo "$db_conn_info" | cut -d'|' -f4)" \
                "$(echo "$db_conn_info" | cut -d'|' -f5)"
        else
            local pg_pw="${POSTGRES_PASSWORD:-}"
            if [[ -z "${pg_pw//[[:space:]]/}" ]]; then
                pg_pw=$(read_env_value_from_file "POSTGRES_PASSWORD" "$SCRIPT_DIR/.env" | tr -d "\n")
            fi
            warn "PostgreSQL DSN çözümlenemedi; veritabanı varlık hazırlığı POSTGRES_* fallback değerleriyle sürdürülecek."
            ensure_postgres_databases_exist "127.0.0.1" "${POSTGRES_PORT:-5432}" "${POSTGRES_USER:-sidar}" "$pg_pw" "${POSTGRES_DB:-sidar}"
        fi
        # Önce DB migrasyonu: olası bağlantı/şema hataları sonraki adımlara geçmeden görülsün.
        run_migrations
        # Model indirme: fonksiyon sonunda cleanup_temp_ollama trap'i geçici 'ollama serve'
        # sürecini otomatik sonlandırır; hemen ardından gelen launch_docker_services'in
        # Docker Ollama servisiyle 11434 port çakışması bu şekilde önlenir.
        download_ollama_models
    else
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        MIGRATION_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal migrasyon/model indirme adımları atlanıyor."
        seed_rag_in_docker_after_startup
    fi
}


sidar_phase06_run_database_password_sync_all_envs() {
    if [[ "${SIDAR_PHASE06_DATABASE_PASSWORDS_SYNCED_FOR:-}" == "$SCRIPT_DIR" ]]; then
        info "PostgreSQL dotenv profilleri bu kurulum turunda zaten eşitlendi; tekrar senkronizasyon atlandı."
        return 0
    fi

    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
        return 1
    fi

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_database_passwords.py" ]]; then
        warn "scripts/sync_database_passwords.py bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
        return 1
    fi

    if (cd "$SCRIPT_DIR" && uv run python scripts/sync_database_passwords.py --all-envs >/dev/null 2>&1); then
        SIDAR_PHASE06_DATABASE_PASSWORDS_SYNCED_FOR="$SCRIPT_DIR"
        return 0
    fi
    return 1
}

sidar_phase06_cleanup_pre_service_smoke_log() {
    if [[ -n "${SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG:-}" ]]; then
        rm -f -- "$SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG"
        SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG=""
    fi
}

sidar_phase06_preserve_pre_service_smoke_log() {
    local log_path="$1"
    local dir=""
    local target=""

    [[ -f "$log_path" ]] || return 1
    if declare -F sidar_remediation_log_dir >/dev/null 2>&1; then
        dir="$(sidar_remediation_log_dir)"
    else
        dir="${SCRIPT_DIR}/artifacts/install/remediation"
        mkdir -p "$dir"
    fi

    target="${dir}/$(date +%Y%m%d_%H%M%S)_pre_service_smoke_gate.log"
    if cp "$log_path" "$target"; then
        printf '%s\n' "$target"
        return 0
    fi
    return 1
}

ensure_env_test_postgres_password_matches_base_before_smoke() {
    local base_env_file="$SCRIPT_DIR/.env"
    local test_env_file="$SCRIPT_DIR/.env.test"
    local test_example_file="$SCRIPT_DIR/.env.test.example"
    local base_password=""
    local test_password=""

    if [[ ! -f "$base_env_file" ]]; then
        warn ".env bulunamadı; .env.test PostgreSQL parola guard'ı atlandı."
        return 0
    fi

    base_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$base_env_file" | tr -d '\n')
    if [[ -z "${base_password//[[:space:]]/}" ]]; then
        warn ".env içinde POSTGRES_PASSWORD bulunamadı; .env.test PostgreSQL parola guard'ı atlandı."
        return 0
    fi

    if [[ ! -f "$test_env_file" && -f "$test_example_file" ]]; then
        cp "$test_example_file" "$test_env_file"
        ok ".env.test dosyası smoke guard için .env.test.example üzerinden oluşturuldu."
    fi

    if [[ ! -f "$test_env_file" ]]; then
        warn ".env.test bulunamadı; smoke guard otomatik düzeltme için --all-envs senkronizasyonunu tekrar deneyecek."
        sidar_phase06_run_database_password_sync_all_envs || true
    fi

    test_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$test_env_file" | tr -d '\n')
    if [[ "$test_password" == "$base_password" ]]; then
        ok ".env.test POSTGRES_PASSWORD değeri .env ile uyumlu."
        return 0
    fi

    warn ".env.test POSTGRES_PASSWORD değeri .env ile uyuşmuyor; smoke test öncesi otomatik düzeltiliyor."
    sidar_phase06_run_database_password_sync_all_envs || warn "--all-envs senkronizasyonu guard sırasında tamamlanamadı; dar kapsamlı .env.test düzeltmesi uygulanacak."

    test_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$test_env_file" | tr -d '\n')
    if [[ "$test_password" != "$base_password" ]]; then
        if [[ ! -f "$test_env_file" ]]; then
            : > "$test_env_file"
        fi
        sed_inplace '/^POSTGRES_PASSWORD=/d' "$test_env_file"
        echo "POSTGRES_PASSWORD=${base_password}" >> "$test_env_file"
        warn ".env.test POSTGRES_PASSWORD dar kapsamlı fallback ile .env değerine eşitlendi."
    fi

    test_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$test_env_file" | tr -d '\n')
    if [[ "$test_password" != "$base_password" ]]; then
        fail ".env.test POSTGRES_PASSWORD değeri .env ile eşitlenemedi; smoke testler güvenli şekilde durduruldu."
    fi

    ok ".env.test POSTGRES_PASSWORD değeri smoke test öncesi .env ile eşitlendi."
}

sidar_phase06_discover_postgres_volumes() {
    local -a compose_cmd=("$@")
    local env_file="$SCRIPT_DIR/.env"
    local compose_project_name="${COMPOSE_PROJECT_NAME:-}"
    local compose_arg=""
    local consume_next_as_project_name=false
    local -a candidate_volume_suffixes=()
    local volume_name=""

    for compose_arg in "${compose_cmd[@]}"; do
        if [[ "$consume_next_as_project_name" == true ]]; then
            compose_project_name="$compose_arg"
            consume_next_as_project_name=false
            continue
        fi
        case "$compose_arg" in
            -p|--project-name)
                consume_next_as_project_name=true
                ;;
            -p=*|--project-name=*)
                compose_project_name="${compose_arg#*=}"
                ;;
        esac
    done

    if [[ -z "$compose_project_name" && -f "$env_file" ]]; then
        compose_project_name=$(read_env_value_from_file "COMPOSE_PROJECT_NAME" "$env_file")
    fi
    compose_project_name=$(echo "${compose_project_name:-}" | tr -d "\"'[:space:]")

    if mapfile -t compose_volumes < <("${compose_cmd[@]}" config --volumes 2>/dev/null); then
        for volume_name in "${compose_volumes[@]}"; do
            if [[ "$volume_name" =~ (^|_)postgres_data$ ]]; then
                candidate_volume_suffixes+=("$volume_name")
            fi
        done
    fi
    if [[ ${#candidate_volume_suffixes[@]} -eq 0 ]]; then
        candidate_volume_suffixes+=("postgres_data")
    fi

    if declare -F sidar_discover_postgres_volumes >/dev/null 2>&1; then
        sidar_discover_postgres_volumes "$compose_project_name" "${candidate_volume_suffixes[@]}"
    else
        docker volume ls --format '{{.Name}}' 2>/dev/null | grep -Ei '(^|[_-])sidar([_-].*)?[_-](postgres|pg)[_-]?data$|(^|[_-])postgres_data$' || true
    fi
}

ensure_postgres_volume_reset_before_smoke_tests() {
    local -a docker_compose_cmd=()
    local -a volumes_before=()
    local -a volumes_after_down=()
    local -a volumes_after_rm=()
    local volume_name=""

    if [[ "${DB_PASSWORD_HARDENED:-false}" != true ]]; then
        info "DB parola hardening işaretlenmedi; smoke öncesi PostgreSQL volume reset gerekmiyor."
        return 0
    fi

    if [[ "${POSTGRES_VOLUME_RESET_DONE:-false}" == true ]]; then
        ok "PostgreSQL volume reset daha önce tamamlanmış olarak işaretli; smoke öncesi ek reset gerekmiyor."
        return 0
    fi

    if ! sidar_postgres_volume_reset_allowed_for_env "$SCRIPT_DIR/.env"; then
        warn "Smoke test öncesi PostgreSQL volume reset, SIDAR_ENV güvenlik freni nedeniyle atlanıyor; smoke testler mevcut volume ile devam edecek."
        return 0
    fi

    if ! command -v docker &>/dev/null; then
        fail "DB parola hardening sonrası PostgreSQL volume reset doğrulaması için docker CLI gerekli."
    fi
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        docker_compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        docker_compose_cmd=(docker-compose)
    else
        fail "DB parola hardening sonrası PostgreSQL volume reset doğrulaması için docker compose gerekli."
    fi

    mapfile -t volumes_before < <(sidar_phase06_discover_postgres_volumes "${docker_compose_cmd[@]}")
    if [[ ${#volumes_before[@]} -gt 0 ]]; then
        warn "Smoke öncesi PostgreSQL volume reset doğrulaması: mevcut volume(ler): ${volumes_before[*]}"
    else
        info "Smoke öncesi PostgreSQL volume reset doğrulaması: mevcut PostgreSQL volume bulunamadı."
    fi

    warn "DB parola hardening sonrası volume reset tamamlanmamış; pg_isready/smoke öncesi docker compose down --volumes --remove-orphans çalıştırılıyor."
    if ! "${docker_compose_cmd[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
        fail "PostgreSQL volume reset için docker compose down --volumes --remove-orphans başarısız oldu."
    fi

    mapfile -t volumes_after_down < <(sidar_phase06_discover_postgres_volumes "${docker_compose_cmd[@]}")
    if [[ ${#volumes_after_down[@]} -gt 0 ]]; then
        warn "docker compose down -v sonrası kalan PostgreSQL volume(ler): ${volumes_after_down[*]} — zorla silinecek."
        for volume_name in "${volumes_after_down[@]}"; do
            if docker volume rm "$volume_name" -f >/dev/null 2>&1; then
                ok "PostgreSQL volume smoke öncesi zorla temizlendi: ${volume_name}"
            else
                warn "PostgreSQL volume smoke öncesi silinemedi: ${volume_name}"
            fi
        done
    else
        ok "docker compose down -v sonrası PostgreSQL volume kalmadı; reset doğrulandı."
    fi

    mapfile -t volumes_after_rm < <(sidar_phase06_discover_postgres_volumes "${docker_compose_cmd[@]}")
    if [[ ${#volumes_after_rm[@]} -gt 0 ]]; then
        fail "PostgreSQL volume reset doğrulanamadı; kalan volume(ler): ${volumes_after_rm[*]}"
    fi

    POSTGRES_VOLUME_RESET_DONE=true
    ok "PostgreSQL volume reset smoke test öncesi doğrulandı; yeni init için servisler tekrar başlatılıyor."
    start_docker_services_or_fail "${docker_compose_cmd[@]}" -- postgres redis
    wait_for_compose_services_health "${docker_compose_cmd[@]}" -- postgres redis || warn "PostgreSQL/Redis healthcheck reset sonrası beklenen sürede doğrulanamadı; smoke test kendi hazır kontrolleriyle devam edecek."
}

sync_database_passwords_before_smoke_tests() {
    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
    elif [[ ! -f "$SCRIPT_DIR/scripts/sync_database_passwords.py" ]]; then
        warn "scripts/sync_database_passwords.py bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
    else
        info "Smoke test öncesi PostgreSQL dotenv profilleri eşitleniyor (.env.test dahil)..."
        if sidar_phase06_run_database_password_sync_all_envs; then
            ok "Smoke test öncesi PostgreSQL dotenv profilleri eşitlendi."
        else
            warn "Smoke test öncesi PostgreSQL dotenv senkronizasyonu tamamlanamadı; guard dar kapsamlı düzeltmeyi deneyecek."
        fi
    fi

    ensure_env_test_postgres_password_matches_base_before_smoke
    ensure_postgres_volume_reset_before_smoke_tests

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_postgres_password.py" ]]; then
        warn "scripts/sync_postgres_password.py bulunamadı; canlı PostgreSQL parola senkronizasyonu atlandı."
        return 0
    fi

    info "Smoke test öncesi canlı PostgreSQL kullanıcı parolası doğrulanıyor..."
    if (cd "$SCRIPT_DIR" && uv run python scripts/sync_postgres_password.py >/dev/null 2>&1); then
        ok "Canlı PostgreSQL kullanıcı parolası smoke test öncesi eşitlendi."
    else
        warn "Canlı PostgreSQL parola senkronizasyonu tamamlanamadı; smoke testler mevcut veritabanı durumu ile devam edecek."
        sidar_phase06_report_production_postgres_password_alignment || true
    fi
}

sidar_phase06_report_production_postgres_password_alignment() {
    local sidar_env=""
    sidar_env=$(read_env_value_from_file "SIDAR_ENV" "$SCRIPT_DIR/.env" | tr -d '\n' | tr '[:upper:]' '[:lower:]')
    sidar_env="${sidar_env:-development}"

    case "$sidar_env" in
        production|prod)
            ;;
        *)
            return 0
            ;;
    esac

    local pg_user pg_password pg_db pg_container runtime_db_url db_conn_info
    if resolve_runtime_database_url >/dev/null; then
        runtime_db_url="$RUNTIME_DATABASE_URL"
        db_conn_info=$("$(command -v python3 || command -v python)" - "$runtime_db_url" <<'PY'
from urllib.parse import urlparse, unquote
import sys

url = sys.argv[1].replace("postgresql+asyncpg://", "postgresql://", 1)
parsed = urlparse(url)
print("|".join([
    unquote(parsed.username or "sidar"),
    unquote(parsed.password or ""),
    parsed.path.lstrip("/") or "postgres",
]))
PY
)
        pg_user=$(echo "$db_conn_info" | cut -d'|' -f1)
        pg_password=$(echo "$db_conn_info" | cut -d'|' -f2)
        pg_db=$(echo "$db_conn_info" | cut -d'|' -f3)
    else
        pg_user=$(read_env_value_from_file "POSTGRES_USER" "$SCRIPT_DIR/.env" | tr -d '\n')
        pg_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$SCRIPT_DIR/.env" | tr -d '\n')
        pg_db=$(read_env_value_from_file "POSTGRES_DB" "$SCRIPT_DIR/.env" | tr -d '\n')
    fi
    pg_container=$(read_env_value_from_file "SIDAR_POSTGRES_CONTAINER" "$SCRIPT_DIR/.env" | tr -d '\n')

    pg_user="${pg_user:-sidar}"
    pg_db="${pg_db:-postgres}"
    pg_container="${pg_container:-sidar_postgres}"

    if [[ -z "${pg_password//[[:space:]]/}" ]]; then
        warn "Production profili: POSTGRES_PASSWORD boş görünüyor; mevcut volume parola uyumu doğrulanamadı."
        return 0
    fi

    if ! command -v docker &>/dev/null; then
        warn "Production profili: docker CLI bulunamadı; mevcut volume parola uyumu doğrulanamadı."
        return 0
    fi

    if env PGPASSWORD="$pg_password" docker exec "$pg_container" psql -U "$pg_user" -d "$pg_db" -c 'SELECT 1;' >/dev/null 2>&1; then
        ok "Production profili seçildi: mevcut PostgreSQL volume parolası .env ile uyumlu görünüyor."
    else
        warn "Production profili seçildi: mevcut PostgreSQL volume parolası .env ile doğrulanamadı. Gerekirse .env parolasını volume ile eşleştirin veya temiz kurulum için volume reset uygulayın."
    fi
}

run_pre_service_installer_smoke_gate() {
    local gate_enabled="${SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE:-1}"
    gate_enabled="$(normalize_bool "$gate_enabled")"
    [[ -z "$gate_enabled" ]] && gate_enabled="true"

    if [[ "$gate_enabled" != "true" ]]; then
        info "SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0; servis öncesi installer smoke gate atlandı."
        return 0
    fi
    if [[ "${RUN_SMOKE_TESTS_MODE:-prompt}" == "never" ]]; then
        info "--skip-smoke-test/RUN_SMOKE_TESTS_MODE=never verildiği için servis öncesi installer smoke gate atlandı."
        return 0
    fi
    if [[ ! -f "$SCRIPT_DIR/tests/smoke/test_install_verification.py" ]]; then
        warn "Servis öncesi installer smoke gate atlandı: tests/smoke/test_install_verification.py bulunamadı."
        return 0
    fi
    if ! command -v uv >/dev/null 2>&1; then
        warn "Servis öncesi installer smoke gate atlandı: uv bulunamadı."
        return 0
    fi

    local expected_installer_version=""
    if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
        expected_installer_version="$(sed -nE 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$SCRIPT_DIR/pyproject.toml" | head -n1 || true)"
    fi
    if [[ -n "${expected_installer_version//[[:space:]]/}" ]]; then
        info "Installer sürüm sözleşmesi pyproject.toml üzerinden okunuyor: v${expected_installer_version}. Source/export doğrulaması CI smoke testi kapsamındadır."
        if [[ -n "${INSTALL_SIDAR_VERSION:-}" && "${INSTALL_SIDAR_VERSION}" != "$expected_installer_version" ]]; then
            fail "Servis öncesi smoke gate durduruldu: INSTALL_SIDAR_VERSION=${INSTALL_SIDAR_VERSION}, pyproject.toml=${expected_installer_version}. Kurulumu repo kökündeki ./install_sidar.sh ile yeniden başlatın veya ortam değişkenini pyproject.toml ile eşitleyin."
        fi
    else
        warn "pyproject.toml içinde [project].version okunamadı; INSTALL_SIDAR_VERSION sözleşmesi CI smoke testi kapsamında doğrulanacak."
    fi

    local smoke_log
    smoke_log="$(mktemp "${TMPDIR:-/tmp}/sidar_pre_service_smoke.XXXXXX")" || fail "Servis öncesi installer smoke gate log dosyası oluşturulamadı."
    SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG="$smoke_log"
    sidar_phase06_fail_with_smoke_cleanup() {
        sidar_phase06_cleanup_pre_service_smoke_log
        fail "$@"
    }

    info "Servis öncesi installer smoke gate Python bağımlılıkları doğrulanıyor (pytest + pydantic)."
    if ! (
        cd "$SCRIPT_DIR" && \
            uv run python - <<'PY'
import importlib.util
import sys

missing = [
    module
    for module in ("pytest", "pydantic", "pydantic_settings")
    if importlib.util.find_spec(module) is None
]
if missing:
    print(", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
PY
    ); then
        warn "Servis öncesi installer smoke gate için pytest/pydantic bağımlılıkları eksik; dev-light profili uv ile senkronize ediliyor."
        if ! (cd "$SCRIPT_DIR" && uv sync --frozen --extra dev-light); then
            sidar_phase06_fail_with_smoke_cleanup "Servis öncesi installer smoke gate başlatılamadı; pytest/pydantic bağımlılıkları hazırlanamadı. Manuel doğrulama: uv sync --frozen --extra dev-light"
        fi
        ok "Servis öncesi installer smoke gate bağımlılıkları dev-light profiliyle hazırlandı."
    fi

    info "Servis öncesi installer smoke gate başlamadan PostgreSQL dotenv profilleri eşitleniyor..."
    if sidar_phase06_run_database_password_sync_all_envs; then
        ok "Servis öncesi installer smoke gate dotenv profilleri eşitlendi."
    else
        sidar_phase06_fail_with_smoke_cleanup "Servis öncesi installer smoke gate başlatılamadı; PostgreSQL dotenv profilleri eşitlenemedi."
    fi

    info "Servis başlatmadan önce installer smoke gate çalıştırılıyor (-x, no-cov)."
    if (
        set -o pipefail
        (
            cd "$SCRIPT_DIR" && \
                SIDAR_ENV=test \
                SIDAR_KEYS_FILE="" \
                SIDAR_TEST_LOAD_REAL_KEYS=0 \
                SIDAR_INSTALL_TEST_MODE=1 \
                SIDAR_INSTALL_SMOKE_BASH_TIMEOUT="${SIDAR_INSTALL_SMOKE_BASH_TIMEOUT:-180}" \
                uv run pytest \
                    -q \
                    --no-cov \
                    -p no:xdist \
                    -x \
                    --confcutdir="$SCRIPT_DIR/tests/smoke" \
                    tests/smoke/test_install_verification.py \
                </dev/null
        ) 2>&1 | tee "$smoke_log"
    ); then
        ok "Servis öncesi installer smoke gate başarılı."
        SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE_STATUS="tamamlandi"
        sidar_phase06_cleanup_pre_service_smoke_log
    else
        # shellcheck disable=SC2034  # scripts/install_modules/phases/10_validation.sh reads this sourced state.
        SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE_STATUS="hata"
        local persisted_smoke_log=""
        SIDAR_LAST_FAILED_TEST="$(
            grep -m1 -E '^FAILED[[:space:]]+tests/' "$smoke_log" 2>/dev/null |
                sed -E 's/^FAILED[[:space:]]+([^[:space:]]+).*/\1/' ||
                true
        )"
        export SIDAR_LAST_FAILED_TEST
        persisted_smoke_log="$(sidar_phase06_preserve_pre_service_smoke_log "$smoke_log" || true)"
        warn "Smoke gate çıktısı: $smoke_log"
        if [[ -n "${persisted_smoke_log//[[:space:]]/}" ]]; then
            warn "Smoke gate kalıcı log kopyası: $persisted_smoke_log"
        else
            warn "Smoke gate kalıcı log kopyası artifacts/install/remediation altına yazılamadı."
        fi
        warn "Smoke gate hata önizleme (ilk 200 satır):"
        if command -v head >/dev/null 2>&1; then
            head -n 200 "$smoke_log" | sed 's/^/  | /' || true
        else
            sed -n '1,200p' "$smoke_log" | sed 's/^/  | /' || true
        fi
        if grep -qE 'INSTALL_SIDAR_VERSION|_run_bash_smoke .* tamamlanamadı|TimeoutExpired' "$smoke_log" 2>/dev/null; then
            warn "Smoke gate INSTALL_SIDAR_VERSION sözleşmesi başarısız olmuş olabilir; pyproject.toml içindeki [project].version satırını ve 'source install_sidar.sh' çıktısındaki INSTALL_SIDAR_VERSION değerini kontrol edin."
            warn "Probe-only sürüm kontrolü güncel install_sidar.sh içinde Bash fast-path ile saniyeler içinde bitmelidir; timeout alıyorsanız eski/farklı checkout, branch uyumsuzluğu veya WSL dosya sistemi yavaşlığını kontrol edin."
            warn "Ayrıntılı teşhis için docs/INSTALL_SMOKE_GATE_TROUBLESHOOTING.md içindeki hızlı 'SIDAR_INSTALL_VERSION_PROBE_ONLY=1' doğrulamasını çalıştırın."
            warn "Smoke gate probe timeout belirtisi varsa SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=240 gibi daha yüksek bir değerle yeniden deneyin; kurulumun servis öncesi smoke gate'ini bilinçli atlamak için --skip-smoke-test veya RUN_SMOKE_TESTS_MODE=never kullanın."
        elif grep -q 'Argument list too long' "$smoke_log" 2>/dev/null; then
            warn "Smoke subprocess environment boyutu işletim sistemi sınırını aştı."
            warn "SIDAR_KEYS_FILE ve dotenv zincirindeki büyük değerleri kontrol edin."
        fi
        if grep -q "test_install_sidar_bootstrap_core_hash_drift_reports_core_layer" "$smoke_log" 2>/dev/null; then
            warn "Installer core manifest drift smoke testi başarısız oldu; install_sidar.sh içinde SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY erken çıkışının core_manifest_status=2 durumunu maskelemediğini kontrol edin."
        fi
        if grep -qE '\.env\.test:.*expected=.*actual=|unexpectedly received real key value|SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV' "$smoke_log" 2>/dev/null; then
            warn "Smoke gate .env.test API key senkronizasyon sözleşmesi nedeniyle başarısız görünüyor."
            warn "Varsayılan güvenlik davranışı gerçek servis anahtarlarını .env.test içine kopyalamaz."
            warn "Test gerekiyorsa SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=1 opt-in davranışı ayrı test edilmelidir."
        fi
        sidar_phase06_fail_with_smoke_cleanup "Servis öncesi installer smoke gate başarısız; Docker servisleri başlatılmadan kurulum durduruldu (detay: ${persisted_smoke_log:-$smoke_log})."
    fi
    sidar_phase06_cleanup_pre_service_smoke_log
}

sidar_phase_services_and_validation() {
    if declare -F phase06_docker_daemon_gate_or_fail >/dev/null 2>&1; then
        phase06_docker_daemon_gate_or_fail
    fi
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
        run_pre_service_installer_smoke_gate || return $?
    fi
    # Tüm altyapı (jaeger/prometheus/grafana dahil) smoke testlerden önce hazır olsun.
    launch_docker_services
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
        sync_database_passwords_before_smoke_tests
        run_smoke_tests
        run_install_integration_api_tests
        run_install_frontend_quality_validation
        run_test_artifact_audit
    else
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        SMOKE_TEST_STATUS="tam_docker_modu_nedeniyle_atlandi"
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        INTEGRATION_TEST_STATUS="tam_docker_modu_nedeniyle_atlandi"
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        AUDIT_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal smoke-test/integration/audit adımları atlanıyor."
    fi
}
