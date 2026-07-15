#!/usr/bin/env bash
set -Eeuo pipefail

env_file="$1"
root="$2"

ok() { printf 'OK:%s\n' "$*"; }
info() { printf 'INFO:%s\n' "$*"; }
warn() { printf 'WARN:%s\n' "$*"; }
read_env_value_from_file() {
  grep -E "^$1=" "$2" | head -n1 | cut -d= -f2-
}
sed_inplace() { sed -i "$1" "$2"; }
is_weak_secret_value() { [[ "$1" == "sidar" || "$1" == "postgres" ]]; }
source "$root/scripts/install_modules/utils/env_secrets.sh"
generate_secure_token() { printf 'strong-generated-password'; }
harden_database_credentials "$env_file"

grep -q '^DATABASE_URL=postgresql+asyncpg://sidar:strong-generated-password@127.0.0.1:5432/sidar$' "$env_file"
grep -q '^POSTGRES_PASSWORD=strong-generated-password$' "$env_file"
grep -q '^POSTGRES_USER=sidar$' "$env_file"
grep -q '^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:strong-generated-password@postgres:5432/sidar$' "$env_file"
[[ "${DB_PASSWORD_HARDENED:-false}" == "true" ]]
