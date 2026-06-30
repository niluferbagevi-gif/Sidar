#!/usr/bin/env bash
# shellcheck disable=SC2034  # REACT_UI_STATUS is consumed by installer summary phases.

# ── 7. React Web UI bağımlılıkları ve build ──────────────────────────────────
maybe_upgrade_npm_latest() {
    local npm_bin="${1:-npm}"
    local upgrade_raw="${SIDAR_UPGRADE_NPM_LATEST:-${UPGRADE_NPM_LATEST:-0}}"
    upgrade_raw="$(echo "$upgrade_raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"

    case "$upgrade_raw" in
        1|true|yes|y|evet|e|on)
            info "SIDAR_UPGRADE_NPM_LATEST etkin; npm@latest global güncellemesi deneniyor..."
            if "$npm_bin" install -g npm@latest --no-audit --no-fund; then
                ok "npm güncellendi: $("$npm_bin" -v 2>/dev/null || echo 'sürüm alınamadı')"
            else
                warn "npm@latest güncellemesi başarısız oldu; mevcut npm ile devam edilecek."
            fi
            ;;
        *)
            info "npm major update notice gürültüsünü azaltmak için npm update notifier kapalı çalıştırılacak. Global npm güncellemesi için SIDAR_UPGRADE_NPM_LATEST=1 kullanın."
            ;;
    esac
}

setup_react_frontend() {
    step "React Web Arayüzü"

    REACT_DIR="$SCRIPT_DIR/web_ui_react"
    if [[ ! -d "$REACT_DIR" ]]; then
        info "web_ui_react dizini bulunamadı — frontend kurulumu atlandı."
        REACT_UI_STATUS="dizin_yok"
        return
    fi

    if [[ ! -f "$REACT_DIR/package.json" ]]; then
        info "web_ui_react/package.json bulunamadı — frontend kurulumu atlandı."
        REACT_UI_STATUS="package_json_yok"
        return
    fi

    local npm_bin=""
    npm_bin="$(resolve_native_binary_path npm || true)"
    if [[ -z "$npm_bin" ]]; then
        if command -v npm &>/dev/null; then
            warn "Sadece Windows Interop npm bulundu ($(command -v npm)). Linux Node.js/npm kullanın."
        fi
        warn "npm bulunamadı. React Web UI için Node.js + npm kurun ve şu komutları çalıştırın:"
        echo "       cd web_ui_react && npm ci && npm run build"
        REACT_UI_STATUS="npm_yok"
        return
    fi
    export npm_config_update_notifier=false
    export NPM_CONFIG_UPDATE_NOTIFIER=false
    maybe_upgrade_npm_latest "$npm_bin"

    local node_bin=""
    node_bin="$(resolve_native_binary_path node || true)"
    local node_target_major=""
    node_target_major="$(resolve_target_node_major)"
    if [[ -n "$node_bin" ]]; then
        NODE_MAJOR="$("$node_bin" -v | sed 's/^v//' | cut -d. -f1)"
        if [[ "$NODE_MAJOR" -lt "$node_target_major" ]]; then
            warn "Node.js sürümü düşük: $("$node_bin" -v). React build için Node.js ${node_target_major}+ önerilir."
            warn "Kurulum komutları: sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs (NodeSource repo betik tarafından hedef sürüme göre otomatik ayarlanır)"
        elif [[ "$NODE_MAJOR" -gt "$node_target_major" ]]; then
            warn "Node.js sürüm sapması tespit edildi: hedef ${node_target_major}.x, aktif $("$node_bin" -v). React build uyumluluğu için Node.js ${node_target_major}.x önerilir (.nvmrc)."
            if command -v apt-cache &>/dev/null; then
                if ! apt-cache policy nodejs 2>/dev/null | grep -qi 'nodesource'; then
                    warn "Aktif nodejs paketi NodeSource görünmüyor; Ubuntu varsayılan apt deposu Node.js ${NODE_MAJOR}.x sürümünü öne alıyor olabilir."
                fi
            fi
        else
            ok "Node.js sürümü uygun: $("$node_bin" -v)"
        fi
    elif command -v node &>/dev/null; then
        warn "Sadece Windows Interop node bulundu ($(command -v node)). React build için Linux Node.js kullanılmalı."
    fi

    if [[ "$FORCE_REACT_BUILD" != true && -d "$REACT_DIR/dist" && -d "$REACT_DIR/node_modules" ]]; then
        ok "React Web UI zaten build edilmiş. Yeniden derleme atlanıyor (--build-ui ile zorlayabilirsiniz)."
        REACT_UI_STATUS="hazır_cache"
        return
    fi

    if ! (
        cd "$REACT_DIR"
        if [[ -f "package-lock.json" ]]; then
            info "package-lock.json bulundu. npm ci çalıştırılıyor..."
            npm ci
        else
            warn "package-lock.json bulunamadı. npm ci yerine npm install kullanılacak."
            npm install
        fi
        info "npm run build çalıştırılıyor..."
        npm run build
    ); then
        warn "React UI build başarısız oldu. Kurulum devam edecek; özet bölümünde durum işaretlenecek."
        REACT_UI_STATUS="build_hata"
        return
    fi
    if [[ ! -d "$REACT_DIR/dist" ]]; then
        warn "React UI build tamamlandı görünüyor ancak dist klasörü bulunamadı: $REACT_DIR/dist"
        REACT_UI_STATUS="build_hata"
        return
    fi
    ok "React Web UI bağımlılıkları kuruldu ve build tamamlandı."
    REACT_UI_STATUS="hazır"
}
