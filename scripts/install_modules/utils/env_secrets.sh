#!/usr/bin/env bash
set -Eeuo pipefail
# Sidar installer .env secret generation and hardening helpers.

generate_secure_token() {
    # NOT: token_bytes secrets.token_urlsafe()'e verilen byte sayısıdır, üretilen
    # karakter sayısı değildir (token_urlsafe(n) ~1.3n karakter döndürür).
    local token_bytes="${1:-32}"
    local generated=""
    local attempt=0

    for (( attempt = 0; attempt < 10; attempt++ )); do
        generated=""
        if command -v python3 &>/dev/null; then
            generated=$(python3 - <<PY
import secrets
print(secrets.token_urlsafe(${token_bytes}))
PY
)
        elif command -v openssl &>/dev/null; then
            generated=$(openssl rand -base64 "$((token_bytes * 3))" | tr -dc 'A-Za-z0-9' | head -c "$token_bytes")
        else
            break
        fi
        [[ -n "$generated" ]] || continue
        # is_weak_secret_value diğer otomatik-üretilen secret'lar (POSTGRES_PASSWORD
        # dışındakiler) için zaten uygulanan aynı kalite kapısı; DB parolası da bu
        # kapıdan geçmeli. Fonksiyon henüz yüklenmemişse (izole/erken çağrı) atla.
        if ! declare -F is_weak_secret_value >/dev/null 2>&1 || ! is_weak_secret_value "$generated"; then
            break
        fi
    done

    echo "$generated"
}
