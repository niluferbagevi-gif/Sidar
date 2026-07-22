#!/usr/bin/env bash
set -Eeuo pipefail
# Sidar installer .env secret generation and hardening helpers.

generate_secure_token() {
    local token_length="${1:-32}"
    local generated=""

    if command -v python3 &>/dev/null; then
        generated=$(python3 - <<PY
import secrets
print(secrets.token_urlsafe(${token_length}))
PY
)
    elif command -v openssl &>/dev/null; then
        generated=$(openssl rand -base64 "$((token_length * 3))" | tr -dc 'A-Za-z0-9' | head -c "$token_length")
    fi

    echo "$generated"
}
