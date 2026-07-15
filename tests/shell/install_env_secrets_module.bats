#!/usr/bin/env bats

bats_require_minimum_version 1.5.0

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

@test "env_secrets hardens weak DATABASE_URL and syncs postgres dotenv values" {
  root="$(repo_root)"
  tmpdir="$BATS_TEST_TMPDIR/env-secrets"
  mkdir -p "$tmpdir"
  env_file="$tmpdir/.env"
  {
    printf '%s\n' 'SIDAR_ENV=development'
    printf '%s\n' 'DATABASE_URL=postgresql+asyncpg://sidar:sidar@127.0.0.1:5432/sidar'
    printf '%s\n' 'POSTGRES_PASSWORD=sidar'
  } > "$env_file"

  run "$root/tests/shell/helpers/env_secrets_hardening_case.sh" "$env_file" "$root"

  [ "$status" -eq 0 ]
  [[ "$output" == *"DATABASE_URL için güvenli bir veritabanı şifresi üretildi"* ]]
}
