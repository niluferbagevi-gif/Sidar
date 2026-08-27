#!/usr/bin/env bats

bats_require_minimum_version 1.5.0

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
  run ! grep -q '^POSTGRES_PASSWORD=__GENERATE__$' "$target"
  run ! grep -q '^POSTGRES_PASSWORD=$' "$target"
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

# Reproduces the reported scenario: a "Tam Docker" installer run never
# populates .venv locally, and a later minimal `uv sync --frozen --extra
# postgres` (e.g. for Alembic) still leaves ruff, a dev-only dependency,
# missing. `uv run --frozen ruff ...` never installs anything by itself, so
# without a self-heal this used to fail hard with "No such file or
# directory" before the backend test phase's own runtime-dependency
# self-heal (ensure_runtime_dependencies) ever gets a chance to run.
_write_fake_uv_missing_then_healed_by_dev_extra() {
  local bin_dir="$1"
  local marker="$2"
  cat > "$bin_dir/uv" <<EOF
#!/usr/bin/env bash
printf "%s\\n" "\$*" >> "$bin_dir/../calls.log"
if [[ "\$1" == "run" ]]; then
  shift
  # drop the --frozen flag before dispatching on the subcommand
  [[ "\$1" == "--frozen" ]] && shift
  if [[ "\$1" == "ruff" ]]; then
    [[ -f "$marker" ]] && exit 0
    exit 1
  fi
  exit 0
fi
if [[ "\$1" == "sync" ]]; then
  touch "$marker"
  exit 0
fi
exit 0
EOF
  chmod +x "$bin_dir/uv"
}

@test "ensure_ruff_available self-heals a missing ruff via uv sync --frozen --extra dev" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  _write_fake_uv_missing_then_healed_by_dev_extra "$tmpdir/bin" "$tmpdir/ruff-installed.marker"

  run env PATH="$tmpdir/bin:$PATH" bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    ensure_ruff_available
  ' _ "$root"

  [ "$status" -eq 0 ]
  [[ "$output" == *"Ruff bulunamadı"* ]]
  [[ "$output" == *"Ruff hazır"* ]]
  grep -q -- "sync --frozen --extra dev" "$tmpdir/calls.log"
  # Only the "dev" extra is used, never the heavier all-extras profile that
  # would drag in PortAudio/voice system dependencies just for a lint gate.
  run ! grep -q -- "--all-extras" "$tmpdir/calls.log"
  rm -rf "$tmpdir"
}

@test "ensure_ruff_available is a no-op when ruff is already available" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  # Marker pre-exists: ruff --version succeeds on the very first call.
  touch "$tmpdir/ruff-installed.marker"
  _write_fake_uv_missing_then_healed_by_dev_extra "$tmpdir/bin" "$tmpdir/ruff-installed.marker"

  run env PATH="$tmpdir/bin:$PATH" bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    ensure_ruff_available
  ' _ "$root"

  [ "$status" -eq 0 ]
  run ! grep -q -- "sync" "$tmpdir/calls.log"
  rm -rf "$tmpdir"
}

@test "ensure_ruff_available fails closed when uv sync cannot install ruff" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  cat > "$tmpdir/bin/uv" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "run" ]]; then
  exit 1
fi
if [[ "$1" == "sync" ]]; then
  exit 1
fi
exit 0
EOF
  chmod +x "$tmpdir/bin/uv"

  run env PATH="$tmpdir/bin:$PATH" bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    ensure_ruff_available
  ' _ "$root"

  [ "$status" -eq 1 ]
  [[ "$output" == *"otomatik kurulumu başarısız"* ]]
}

@test "run_ruff_quality_gate self-heals a missing ruff before running the lint/format checks" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  _write_fake_uv_missing_then_healed_by_dev_extra "$tmpdir/bin" "$tmpdir/ruff-installed.marker"

  run env PATH="$tmpdir/bin:$PATH" bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    run_ruff_quality_gate
  ' _ "$root"

  [ "$status" -eq 0 ]
  grep -q -- "sync --frozen --extra dev" "$tmpdir/calls.log"
  grep -q -- "run --frozen ruff check ." "$tmpdir/calls.log"
  grep -q -- "run --frozen ruff format --check ." "$tmpdir/calls.log"
  rm -rf "$tmpdir"
}
