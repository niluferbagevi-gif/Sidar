#!/usr/bin/env bats

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

@test "render_generated_secret_sentinels reuses an already-set process env POSTGRES_PASSWORD" {
  local root tmpdir target
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  target="$tmpdir/.env.test"
  cat > "$target" <<'ENV'
SIDAR_ENV=test
POSTGRES_PASSWORD=__GENERATE__
ENV

  # A CI job (or any shell) that already exports POSTGRES_PASSWORD before a
  # fresh `bash run_tests.sh` must not get an unrelated, freshly-generated
  # password written into .env.test — that desyncs the file from the actual
  # PostgreSQL role's credentials whenever nothing else (e.g. an ALTER ROLE
  # step) reconciles the two.
  run env POSTGRES_PASSWORD='ci-service-password' bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    render_generated_secret_sentinels "$2"
  ' _ "$root" "$target"

  [ "$status" -eq 0 ]
  [[ "$output" == *"process env POSTGRES_PASSWORD ile senkronize edildi"* ]]
  grep -q '^POSTGRES_PASSWORD=ci-service-password$' "$target"
  rm -rf "$tmpdir"
}

@test "render_generated_secret_sentinels generates a random password when process env is unset" {
  local root tmpdir target
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  target="$tmpdir/.env.test"
  cat > "$target" <<'ENV'
SIDAR_ENV=test
POSTGRES_PASSWORD=__GENERATE__
ENV

  run env -u POSTGRES_PASSWORD bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    render_generated_secret_sentinels "$2"
  ' _ "$root" "$target"

  [ "$status" -eq 0 ]
  [[ "$output" == *"güçlü lokal parola ile değiştirildi"* ]]
  ! grep -q '^POSTGRES_PASSWORD=__GENERATE__$' "$target"
  ! grep -q '^POSTGRES_PASSWORD=$' "$target"
  rm -rf "$tmpdir"
}

@test "render_generated_secret_sentinels is a no-op without a __GENERATE__ sentinel" {
  local root tmpdir target
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  target="$tmpdir/.env.test"
  cat > "$target" <<'ENV'
SIDAR_ENV=test
POSTGRES_PASSWORD=already-set-value
ENV

  run env POSTGRES_PASSWORD='ci-service-password' bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    render_generated_secret_sentinels "$2"
  ' _ "$root" "$target"

  [ "$status" -eq 0 ]
  grep -q '^POSTGRES_PASSWORD=already-set-value$' "$target"
  rm -rf "$tmpdir"
}
