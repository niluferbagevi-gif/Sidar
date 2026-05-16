#!/usr/bin/env bash
# Sidar installer phase 02: repository discovery, clone, and update flow.

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
        git clone "$REPO_URL" "$TARGET_DIR"
    else
        warn "Sidar klasörü zaten var ($TARGET_DIR). Rebase tabanlı git pull ile güncelleniyor..."
        info "Not: Sıfır kurulum beklenirken bu uyarıyı görüyorsanız mevcut çalışma dizinini kontrol edin: $(pwd)"
        (
            cd "$TARGET_DIR"
            local STASHED_CHANGES=false
            local STASH_REF=""
            if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
                info "Lokal değişiklikler geçici olarak stash'e alınıyor."
                git stash push -u -m "sidar-install-auto-stash-$(date +%Y%m%d_%H%M%S)" >/dev/null 2>&1
                STASH_REF="$(git stash list -n 1 --format='%gd' || true)"
                [[ -n "$STASH_REF" ]] || fail "Git stash oluşturuldu sanıldı ancak referans okunamadı; güvenli kurtarma için kurulum durduruldu."
                info "Lokal değişiklik yedeği oluşturuldu: ${STASH_REF}. Gerekirse '$TARGET_DIR' içinde 'git stash apply ${STASH_REF}' ile geri alabilirsiniz."
                STASHED_CHANGES=true
            fi

            git pull --rebase origin main || fail "Git çekme işlemi başarısız oldu!"

            if [[ "$STASHED_CHANGES" == true ]]; then
                if git stash pop "$STASH_REF" >/dev/null 2>&1; then
                    ok "Lokal değişiklikler stash'ten geri yüklendi."
                else
                    warn "Stash pop sırasında çakışma oluştu. Repo güvenliği için kurtarma seçeneği sunulacak."
                    git merge --abort >/dev/null 2>&1 || true
                    git rebase --abort >/dev/null 2>&1 || true
                    if [[ -z "$STASH_REF" ]] || ! git rev-parse -q --verify "$STASH_REF" >/dev/null; then
                        fail "Git çalışma ağacı çakışmalı durumda ve doğrulanmış stash yedeği bulunamadı. Veri kaybı riskinden dolayı reset/clean çalıştırılmadı; lütfen '$TARGET_DIR' içinde manuel çözün."
                    fi
                    warn "Lokal değişiklik yedeği stash içinde korunuyor: ${STASH_REF}. Geri almak için: cd '$TARGET_DIR' && git stash apply ${STASH_REF}"

                    if [[ "$NO_INTERACTION" == true ]]; then
                        fail "Git çalışma ağacı çakışmalı durumda kaldı. --no-interaction modunda otomatik kurtarma yapılmadı. Stash yedeği: ${STASH_REF}. Manuel çözün veya yedeği doğruladıktan sonra temiz kurulumu tekrar başlatın."
                    fi

                    echo ""
                    warn "İsterseniz doğrulanmış stash yedeği (${STASH_REF}) korunurken çalışma ağacı origin/main durumuna temizlenebilir."
                    local recovery_reply
                    recovery_reply=$(prompt_yes_no_with_timeout_default_no "Stash yedeği ${STASH_REF} korunarak 'git reset --hard origin/main && git clean -fd' uygulansın mı? [e/H] ")
                    case "${recovery_reply:-H}" in
                        [EeYy]*)
                            if ! git rev-parse -q --verify "$STASH_REF" >/dev/null; then
                                fail "Stash yedeği (${STASH_REF}) artık doğrulanamıyor; veri kaybını önlemek için git clean -fd çalıştırılmadı."
                            fi
                            warn "Kurtarma adımı uygulanıyor: çalışma ağacı temizlenecek; yedek stash referansı korunuyor: ${STASH_REF}."
                            git fetch origin main || fail "Kurtarma için origin/main fetch başarısız oldu."
                            git reset --hard origin/main || fail "git reset --hard origin/main başarısız oldu."
                            git clean -fd || warn "git clean -fd sırasında bazı dosyalar temizlenemedi. Stash yedeği: ${STASH_REF}"
                            ok "Repo origin/main durumuna sıfırlandı. Stash yedeği korunuyor: ${STASH_REF}. Kurulum devam edecek."
                            ;;
                        *)
                            fail "Git çalışma ağacı çakışmalı durumda kaldı. Stash yedeği: ${STASH_REF}. Lütfen '$TARGET_DIR' içinde çakışmaları çözün veya yedeği doğruladıktan sonra temizleyip kurulumu tekrar başlatın."
                            ;;
                    esac
                fi
            fi
        )
    fi

    SCRIPT_DIR="$TARGET_DIR"
    ok "Kurulum dizini güncellendi: $SCRIPT_DIR"
}

