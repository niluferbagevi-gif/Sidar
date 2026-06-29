#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_REMOTE_SCRIPT_SH_LOADED=1

remote_script_checksum_hint() {
    local script_url="$1"
    local script_label="$2"
    local checksum_var="${script_label^^}_SHA256"

    cat <<EOF
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

    if [[ -z "$expected_sha" ]]; then
        if [[ "${ALLOW_UNVERIFIED_REMOTE_SCRIPTS:-0}" != "1" ]]; then
            local checksum_hint
            checksum_hint="$(remote_script_checksum_hint "$script_url" "$script_label")"
            rm -f "$script_file"
            fail "$checksum_hint"
        fi
        warn "${script_label} checksum doğrulaması atlandı (ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1)."
    elif [[ "$actual_sha" != "$expected_sha" ]]; then
        rm -f "$script_file"
        fail "${script_label} checksum doğrulaması başarısız! Beklenen=${expected_sha}, Gelen=${actual_sha}"
    else
        ok "${script_label} checksum doğrulaması başarılı."
    fi

    DOWNLOADED_SCRIPT_FILE="$script_file"
}
