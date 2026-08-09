#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_REMOTE_SCRIPT_SH_LOADED=1

remote_script_checksum_hint() {
    local script_url="$1"
    local script_label="$2"
    local checksum_var="${3:-${script_label^^}_SHA256}"

    cat <<EOF
NEXT STEP → ${checksum_var}=<hash> ./install_sidar.sh  (detay aşağıda)
${script_label} checksum değeri tanımlı değil. Supply-chain doğrulamasını korumak için ${checksum_var} değişkenini ayarlayın.
Bu kök neden deterministiktir: ortam değişkeni sağlanmadan auto-heal/retry aynı duvara çarpar (no-retry;manual-fix-required).
Örnek güvenli TOFU hazırlığı (betiği inceleyip hash'i aynı içerikten üretin):
  tmp=\$(mktemp)
  curl -fsSL --retry 3 --retry-all-errors -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' '${script_url}' -o "\$tmp"
  less "\$tmp"                    # betiği gözden geçir
  export ${checksum_var}=\$(sha256sum "\$tmp" | awk '{print \$1}')
  rm -f "\$tmp"
  ./install_sidar.sh
Alternatif (sadece bilinçli test/izole ortam): risk kabulüyle ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1 kullanın.
EOF
}

review_and_pin_remote_script_checksum() {
    local script_file="$1"
    local script_url="$2"
    local script_label="$3"
    local actual_sha="$4"
    local checksum_var="${5:-${script_label^^}_SHA256}"
    local tty_fd

    # AUTO_INSTALL yalnız diğer kurulum sorularının varsayılanlarını otomatikleştirir;
    # yeni bir uzak betiğe güvenme kararı ise TTY varsa daima operatöre aittir.
    # Böylece normal `./install_sidar.sh` akışında AUTO_INSTALL seçilmiş olsa bile
    # eksik pin, kullanıcıya manuel export yaptırmak yerine güvenli biçimde
    # inceleme/onay kapısına düşer. CI/no-interaction çalışmaları fail-closed kalır.
    if [[ "${NO_INTERACTION:-false}" == true ]]; then
        return 1
    fi

    # install_sidar.sh stdout/stderr'i maskeleyip loglamak için bir pipe'a
    # yönlendirir. Bu nedenle burada `-t 1` kontrolü gerçek bir interaktif
    # kurulumda bile false olur. Kontrol ve tüm güven kararı I/O'su için
    # controlling terminal'i doğrudan aç; CI/container gibi controlling TTY'si
    # olmayan ortamlarda open başarısız olur ve akış fail-closed kalır.
    if ! exec {tty_fd}<>/dev/tty 2>/dev/null; then
        return 1
    fi

    warn "HATA: ${script_label} checksum değeri tanımlı değil; supply-chain doğrulaması olmadan kurulum sürdürülemez."
    info "Sidar betiği indirdi ve SHA-256 değerini hesapladı; yalnız siz onaylarsanız betik gösterilecek, değer bu oturum için pinlenecek ve kurulum kaldığı adımdan devam edecektir."
    printf '%s\n' "URL: ${script_url}" "Hesaplanan SHA-256: ${actual_sha}" >&"$tty_fd"
    printf '%s' "Betiği inceleyip checksum değerini oluşturmak ve kurulumu yeniden denemek ister misiniz? [y/N] " >&"$tty_fd"
    local review_answer=""
    read -r review_answer <&"$tty_fd"
    case "${review_answer,,}" in
        y|yes|e|evet) ;;
        *) return 1 ;;
    esac
    "${PAGER:-less}" "$script_file" <&"$tty_fd" >&"$tty_fd" || return 1
    printf '%s' "${checksum_var}=${actual_sha} olarak bu kurulum oturumu için kabul edilsin mi? [y/N] " >&"$tty_fd"
    local answer=""
    read -r answer <&"$tty_fd"
    case "${answer,,}" in
        y|yes|e|evet)
            printf -v "$checksum_var" '%s' "$actual_sha"
            export "${checksum_var?}"
            warn "${script_label} checksum bu oturum için interaktif TOFU ile kabul edildi. Kalıcı pin için scripts/install_modules/remote_checksums.env güncellenmelidir."
            info "${checksum_var} oluşturuldu; kurulum doğrulanmış betikle kaldığı adımdan yeniden devam ediyor."
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

download_verified_script() {
    local script_url="$1"
    local expected_sha="$2"
    local script_label="$3"
    local script_file
    script_file=$(mktemp)

    if [[ "$OFFLINE_MODE" == true ]]; then
        rm -f "$script_file"
        fail "${script_label}: --offline/--air-gapped modunda uzak betik indirilemez (${script_url}). offline_packages kullanın."
    fi

    if ! curl -fsSL --retry 3 --retry-all-errors \
        -H "Cache-Control: no-cache" -H "Pragma: no-cache" \
        "$script_url" -o "$script_file"; then
        rm -f "$script_file"
        fail "${script_label} indirilemedi: ${script_url}"
    fi

    local actual_sha
    actual_sha=$(compute_sha256 "$script_file")

    local checksum_accepted=false
    if [[ -z "$expected_sha" ]]; then
        if review_and_pin_remote_script_checksum "$script_file" "$script_url" "$script_label" "$actual_sha"; then
            checksum_accepted=true
            ok "${script_label} checksum interaktif review-and-pin ile doğrulandı."
        elif [[ "${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}" != "1" ]]; then
            local checksum_hint
            checksum_hint="$(remote_script_checksum_hint "$script_url" "$script_label")"
            rm -f "$script_file"
            fail "$checksum_hint"
        fi
        if [[ "$checksum_accepted" != true ]]; then
            warn "${script_label} checksum doğrulaması atlandı (ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1)."
        fi
    elif [[ "$actual_sha" != "$expected_sha" ]]; then
        rm -f "$script_file"
        fail "${script_label} checksum doğrulaması başarısız! Beklenen=${expected_sha}, Gelen=${actual_sha}"
    else
        ok "${script_label} checksum doğrulaması başarılı."
    fi

    DOWNLOADED_SCRIPT_FILE="$script_file"
}

# download_verified_script'in "soft" (fail-kapatmayan) sürümü. Kurulumun tek
# yolu olmayan, en az bir sonraki fallback katmanı bulunan best-effort
# kurulumlar için kullanılır (ör. Volta -> NVM -> apt NodeSource): checksum
# doğrulanamazsa/reddedilirse tüm kurulumu `fail` ile durdurmak yerine sadece
# uyarı basıp 1 döner, böylece çağıran taraf bir sonraki fallback'e geçebilir.
download_verified_script_soft() {
    local script_url="$1"
    local expected_sha="$2"
    local script_label="$3"
    local script_file
    script_file=$(mktemp)

    if [[ "$OFFLINE_MODE" == true ]]; then
        rm -f "$script_file"
        warn "${script_label}: --offline/--air-gapped modunda uzak betik indirilemez (${script_url})."
        return 1
    fi

    if ! curl -fsSL --retry 3 --retry-all-errors \
        -H "Cache-Control: no-cache" -H "Pragma: no-cache" \
        "$script_url" -o "$script_file"; then
        rm -f "$script_file"
        warn "${script_label} indirilemedi: ${script_url}"
        return 1
    fi

    local actual_sha
    actual_sha=$(compute_sha256 "$script_file")

    local checksum_accepted=false
    if [[ -z "$expected_sha" ]]; then
        if review_and_pin_remote_script_checksum "$script_file" "$script_url" "$script_label" "$actual_sha"; then
            checksum_accepted=true
            ok "${script_label} checksum interaktif review-and-pin ile doğrulandı."
        elif [[ "${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}" != "1" ]]; then
            warn "$(remote_script_checksum_hint "$script_url" "$script_label")"
            rm -f "$script_file"
            return 1
        fi
        if [[ "$checksum_accepted" != true ]]; then
            warn "${script_label} checksum doğrulaması atlandı (ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1)."
        fi
    elif [[ "$actual_sha" != "$expected_sha" ]]; then
        rm -f "$script_file"
        warn "${script_label} checksum doğrulaması başarısız! Beklenen=${expected_sha}, Gelen=${actual_sha}"
        return 1
    else
        ok "${script_label} checksum doğrulaması başarılı."
    fi

    # shellcheck disable=SC2034  # Read by callers after validate_downloaded_script_file succeeds.
    DOWNLOADED_SCRIPT_FILE="$script_file"
    return 0
}
