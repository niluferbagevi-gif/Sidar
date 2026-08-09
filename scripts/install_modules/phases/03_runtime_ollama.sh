#!/usr/bin/env bash
set -Eeuo pipefail

_ollama_install_step() {
    # Ollama (varsayılan AI provider) - Akıllı Kontrol ve Kurulum
    if ! ollama -v &>/dev/null; then
        warn "Ollama bulunamadı veya kurulumu bozuk. İndiriliyor..."
        if command -v sudo &>/dev/null; then
            # Eski bozuk dosya kalıntılarını temizle
            sudo rm -f /usr/local/bin/ollama
            info "Ollama kurulumu başlatılıyor..."
            local ollama_install_script=""
            if [[ "$OFFLINE_MODE" == true ]]; then
                ollama_install_script="$(resolve_offline_package_file "ollama/install.sh" || true)"
                if [[ -z "$ollama_install_script" ]]; then
                    ollama_install_script="$(resolve_offline_package_file "ollama_install.sh" || true)"
                fi
                if [[ -z "$ollama_install_script" ]]; then
                    ollama_install_script="$(resolve_offline_package_file "install_ollama.sh" || true)"
                fi
                if [[ -z "$ollama_install_script" ]]; then
                    fail "Çevrimdışı mod: offline_packages altında Ollama kurulum betiği bulunamadı (ollama/install.sh, ollama_install.sh, install_ollama.sh)."
                fi
            else
                DOWNLOADED_SCRIPT_FILE=""
                download_verified_script \
                    "https://ollama.com/install.sh" \
                    "${OLLAMA_INSTALL_SHA256:-}" \
                    "ollama_install"
                validate_downloaded_script_file "$DOWNLOADED_SCRIPT_FILE" "ollama_install"
                ollama_install_script="$DOWNLOADED_SCRIPT_FILE"
            fi

            info "Ollama kurulumu öncesi sudo yetkisi doğrulanıyor..."
            if [[ "$NO_INTERACTION" == true ]]; then
                sudo -n -v || fail "Ollama kurulumu için sudo yetkisi gerekli. --ci/--no-interaction modunda şifresiz sudo veya önceden doğrulanmış sudo oturumu beklenir."
            else
                sudo -v || fail "Ollama kurulumu için sudo doğrulaması başarısız oldu."
            fi

            local sudo_keepalive_pid=""
            (
                while true; do
                    sudo -n -v 2>/dev/null || exit 0
                    sleep "${SUDO_KEEPALIVE_INTERVAL_SECONDS:-30}"
                done
            ) &
            sudo_keepalive_pid=$!
            info "Ollama kurulumu boyunca sudo zaman damgası canlı tutulacak (pid=${sudo_keepalive_pid})."

            local _ollama_rc=0
            if sh "$ollama_install_script"; then
                _ollama_rc=0
            else
                _ollama_rc=$?
            fi

            if [[ -n "$sudo_keepalive_pid" ]]; then
                kill "$sudo_keepalive_pid" 2>/dev/null || true
                wait "$sudo_keepalive_pid" 2>/dev/null || true
            fi
            [[ "$ollama_install_script" == "${DOWNLOADED_SCRIPT_FILE:-}" ]] && rm -f "$DOWNLOADED_SCRIPT_FILE"

            if (( _ollama_rc != 0 )); then
                if command -v ollama &>/dev/null && ollama -v &>/dev/null; then
                    warn "Ollama install.sh rc=${_ollama_rc} döndü (büyük olasılıkla sudo timestamp expire); ancak 'ollama -v' yanıt veriyor, kurulum tamamlanmış kabul ediliyor."
                else
                    fail "Ollama kurulumu başarısız (rc=${_ollama_rc}). /var/log/syslog veya logs/install_*.log dosyalarını kontrol edin."
                fi
            fi
            ok "Ollama başarıyla kuruldu."
        else
            warn "Sudo yetkisi bulunamadı. Kurulum manuel yapılmalı: https://ollama.com"
        fi
    else
        ok "Ollama zaten kurulu."
    fi

    # Servisin anlık olarak yanıt verip vermediğini kontrol et
    OLLAMA_VERSION_URL=$(resolve_ollama_version_url "$SCRIPT_DIR/.env")
    local ollama_healthcheck_wait_seconds="${OLLAMA_API_HEALTHCHECK_MAX_WAIT_SECONDS:-30}"
    info "Ollama API healthcheck bekleme döngüsü başlatılıyor (maksimum ${ollama_healthcheck_wait_seconds} saniye)..."
    if wait_for_ollama_api_ready "$OLLAMA_VERSION_URL" "$ollama_healthcheck_wait_seconds" 1; then
        ok "Ollama API servisi aktif (${OLLAMA_VERSION_URL})."
    else
        warn "Ollama kurulu ancak API servisi şu an yanıt vermiyor (${OLLAMA_VERSION_URL})."
        info "Model indirmek veya servisi başlatmak için ayrı bir terminalde 'ollama serve' komutunu çalıştırabilirsiniz."
        info "Alternatif olarak .env içinde AI_PROVIDER=gemini veya openai kullanabilirsiniz."
    fi
}
