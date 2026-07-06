#!/usr/bin/env bash

sidar_phase_apply_coverage_dark_mode_assets() {
    local source_css="$SCRIPT_DIR/assets/dark_mode.css"
    local -a coverage_asset_dirs=(
        "$SCRIPT_DIR/htmlcov/assets"
        "$SCRIPT_DIR/artifacts/htmlcov/assets"
    )
    local -a coverage_html_dirs=(
        "$SCRIPT_DIR/htmlcov"
        "$SCRIPT_DIR/artifacts/htmlcov"
    )
    local assets_dir=""
    local html_dir=""

    if [[ ! -f "$source_css" ]]; then
        warn "Coverage dark-mode CSS bulunamadı: $source_css"
        return 0
    fi

    for assets_dir in "${coverage_asset_dirs[@]}"; do
        mkdir -p "$assets_dir"
        cp -f "$source_css" "$assets_dir/dark_mode.css"
    done

    for html_dir in "${coverage_html_dirs[@]}"; do
        [[ -d "$html_dir" ]] || continue
        while IFS= read -r -d '' html_file; do
            sed_inplace 's/light-mode/dark-mode/g' "$html_file"
        done < <(find "$html_dir" -type f -name '*.html' -print0)
    done

    ok "Coverage dark-mode varlıkları hazırlandı ve mevcut HTML raporları dark-mode'a geçirildi."
}

deploy_with_helm() {
    step "Kubernetes/Helm Dağıtımı"
    local chart_dir="$SCRIPT_DIR/helm/sidar"
    local helm_cmd=(helm upgrade --install "$HELM_RELEASE_NAME" "$chart_dir" --namespace "$HELM_NAMESPACE" --create-namespace)

    if ! command -v helm &>/dev/null; then
        fail "helm bulunamadı. Kurulum için: https://helm.sh/docs/intro/install/"
    fi

    if [[ ! -f "$chart_dir/Chart.yaml" ]]; then
        fail "Helm chart bulunamadı: $chart_dir/Chart.yaml"
    fi

    if [[ -n "$HELM_VALUES_FILE" ]]; then
        if [[ ! -f "$SCRIPT_DIR/$HELM_VALUES_FILE" && ! -f "$HELM_VALUES_FILE" ]]; then
            fail "--values ile verilen dosya bulunamadı: $HELM_VALUES_FILE"
        fi
        if [[ -f "$SCRIPT_DIR/$HELM_VALUES_FILE" ]]; then
            HELM_VALUES_FILE="$SCRIPT_DIR/$HELM_VALUES_FILE"
        fi
        helm_cmd+=(--values "$HELM_VALUES_FILE")
    fi

    info "Helm chart doğrulaması çalıştırılıyor..."
    helm lint "$chart_dir"

    info "Helm release kuruluyor/güncelleniyor: release=$HELM_RELEASE_NAME namespace=$HELM_NAMESPACE"
    "${helm_cmd[@]}"
    ok "Helm dağıtımı tamamlandı."

    if command -v kubectl &>/dev/null; then
        info "Servisleri doğrulamak için:"
        echo "       kubectl get pods -n $HELM_NAMESPACE"
        echo "       kubectl get svc -n $HELM_NAMESPACE"
    else
        warn "kubectl bulunamadı. Cluster doğrulaması için kubectl kurmanız önerilir."
    fi
}

report_repo_lookup_context() {
    local current_pwd
    current_pwd="$(pwd)"

    info "Kurulum çalışma dizini: $current_pwd"
    info "Sidar deposu hedef dizini: $TARGET_DIR"

    if [[ "$current_pwd" == /mnt/* ]]; then
        warn "Kurulum /mnt altında çalışıyor. Windows dosya sistemi önceki Sidar klasörünü koruyor olabilir."
        info "Temiz kurulum için öneri: cd \"$HOME\" && ./Sidar/install_sidar.sh veya doğrudan cd \"$TARGET_DIR\"."
    fi
}

# ── 0. GitHub deposunu hazırla / güncelle ────────────────────────────────────
sync_repo() {
    step "Sidar projesi GitHub'dan çekiliyor"

    if [[ "$OFFLINE_MODE" == true ]]; then
        if [[ -d "$SCRIPT_DIR/.git" ]]; then
            TARGET_DIR="$SCRIPT_DIR"
            ok "Çevrimdışı mod: mevcut repo kullanılacak (git clone/pull atlandı): $SCRIPT_DIR"
            return
        fi

        if [[ -d "$TARGET_DIR/.git" ]]; then
            SCRIPT_DIR="$TARGET_DIR"
            ok "Çevrimdışı mod: mevcut hedef repo kullanılacak (git clone/pull atlandı): $TARGET_DIR"
            return
        fi

        fail "Çevrimdışı modda git clone yapılamaz. Lütfen repo içinden çalıştırın veya $TARGET_DIR altında önceden klonlanmış repo sağlayın."
    fi

    # Bu adım git clone/pull çalıştırdığı için, akış sırası değişse bile
    # git erişimi burada da kesin olarak doğrulanır.
    if ! command -v git &>/dev/null; then
        fail "git komutu bulunamadı. Önce sistem bağımlılıklarını kurun (install_system_dependencies)."
    fi

    if [[ "$SCRIPT_DIR" == "$TARGET_DIR" && -d "$SCRIPT_DIR/.git" ]]; then
        ok "Kurulum betiği zaten $TARGET_DIR içinde çalışıyor."
        return
    fi

    if [[ ! -d "$TARGET_DIR/.git" ]]; then
        info "Sidar deposu klonlanıyor: $REPO_URL → $TARGET_DIR"
        git clone "$REPO_URL" --depth=1 --branch "${REPO_BRANCH:-main}" "$TARGET_DIR"
    else
        warn "Sidar klasörü zaten var ($TARGET_DIR). Rebase tabanlı git pull ile güncelleniyor..."
        info "Not: Sıfır kurulum beklenirken bu uyarıyı görüyorsanız mevcut çalışma dizinini kontrol edin: $(pwd)"
        (
            cd "$TARGET_DIR" || fail "Depo dizinine geçilemedi: $TARGET_DIR"
            local STASHED_CHANGES=false
            local INSTALL_STASH_REF=""
            local INSTALL_STASH_MESSAGE=""
            if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
                INSTALL_STASH_MESSAGE="sidar-install-auto-stash-$(date +%Y%m%d_%H%M%S)"
                info "Lokal değişiklikler geçici olarak stash'e alınıyor."
                git stash push -u -m "$INSTALL_STASH_MESSAGE" >/dev/null 2>&1 || fail "Lokal değişiklikler yedek stash'e alınamadı; git güncellemesi güvenli şekilde durduruldu."
                INSTALL_STASH_REF="$(git stash list --format='%gd:%gs' | awk -F: -v msg="$INSTALL_STASH_MESSAGE" '$0 ~ msg {print $1; exit}')"
                INSTALL_STASH_REF="${INSTALL_STASH_REF:-stash@{0}}"
                STASHED_CHANGES=true
                ok "Lokal değişiklikler yedek stash'e alındı: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE})"
            fi

            git pull --rebase origin main || fail "Git çekme işlemi başarısız oldu!"

            if [[ "$STASHED_CHANGES" == true ]]; then
                # `apply` kullanıyoruz; başarı kesinleşmeden stash'i drop etmeyerek
                # reset/clean gibi yıkıcı kurtarma adımlarında kullanıcı çalışmasını
                # geri alınabilir bir stash referansıyla koruyoruz.
                if git stash apply "$INSTALL_STASH_REF" >/dev/null 2>&1; then
                    git stash drop "$INSTALL_STASH_REF" >/dev/null 2>&1 || warn "Uygulanan stash otomatik silinemedi; manuel kontrol edin: ${INSTALL_STASH_REF}"
                    ok "Lokal değişiklikler stash'ten geri yüklendi."
                else
                    warn "Stash apply sırasında çakışma oluştu; yedek stash korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE})"
                    git merge --abort >/dev/null 2>&1 || true
                    git rebase --abort >/dev/null 2>&1 || true
                    if [[ "$NO_INTERACTION" == true ]]; then
                        fail "Git çalışma ağacı çakışmalı durumda kaldı. --no-interaction modunda otomatik kurtarma yapılmadı. Yerel çalışma yedek stash içinde korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE}). Manuel çözün veya stash'i doğruladıktan sonra reset/clean işlemini bilinçli çalıştırın."
                    fi

                    echo ""
                    warn "Yerel değişiklikler yedek stash içinde korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE})"
                    warn "Yalnız bu stash referansını doğruladıktan sonra çalışma ağacını origin/main durumuna sıfırlayabilirsiniz."
                    local recovery_reply
                    recovery_reply=$(prompt_yes_no_with_timeout_default_no "Yedek stash doğrulandı. Çakışmayı temizlemek için 'git reset --hard origin/main && git clean -fd' uygulansın mı? [e/H] ")
                    case "${recovery_reply:-H}" in
                        [EeYy]*)
                            if [[ -z "$INSTALL_STASH_REF" ]] || ! git rev-parse -q --verify "${INSTALL_STASH_REF}^{commit}" >/dev/null; then
                                fail "Yıkıcı git kurtarma reddedildi: geçerli yedek stash referansı bulunamadı. git clean -fd çalıştırılmadı."
                            fi
                            warn "Kurtarma adımı uygulanıyor. Yerel çalışma yedek stash'te korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE})"
                            git fetch origin main || fail "Kurtarma için origin/main fetch başarısız oldu."
                            git reset --hard origin/main || fail "git reset --hard origin/main başarısız oldu. Yedek stash: ${INSTALL_STASH_REF}"
                            git clean -fd || warn "git clean -fd sırasında bazı dosyalar temizlenemedi. Yedek stash: ${INSTALL_STASH_REF}"
                            ok "Repo origin/main durumuna sıfırlandı. Yedek stash korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE}). Geri almak için: git stash apply ${INSTALL_STASH_REF}"
                            ;;
                        *)
                            fail "Git çalışma ağacı çakışmalı durumda kaldı. Yerel çalışma yedek stash içinde korunuyor: ${INSTALL_STASH_REF} (${INSTALL_STASH_MESSAGE}). Lütfen '$TARGET_DIR' içinde çakışmaları manuel çözün veya stash'i doğruladıktan sonra reset/clean işlemini bilinçli çalıştırın."
                            ;;
                    esac
                fi
            fi
        )
    fi

    SCRIPT_DIR="$TARGET_DIR"
    refresh_install_sidar_version_from_repo
    ok "Kurulum dizini güncellendi: $SCRIPT_DIR"
    info "Installer sürümü repo kaynaklarından yenilendi: v$INSTALL_SIDAR_VERSION"
    banner
}


sidar_phase_bootstrap_repo_system() {
    # Kritik sıra:
    # 1) Sistem bağımlılıkları (git/curl vb.)
    # 2) Repo senkronizasyonu (git clone/pull)
    # 3) Ön koşul doğrulaması (uv/Python/FFmpeg/Docker/Ollama)
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR" || return
    sidar_phase_apply_coverage_dark_mode_assets
}
