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

# Reproduces a real-world crash: `python` is bare-called in several places
# (check_python_version, generate_test_secret_value,
# render_generated_secret_sentinels, validate_coverage_ratchet_state) but
# many modern Ubuntu/WSL systems only ship `python3`, not a `python` shim.
# This is exactly the scenario when `uv` isn't on PATH yet either (e.g.
# install_sidar.sh was executed, not sourced, so its PATH export never
# reaches the caller's shell): ensure_project_venv() returns early without
# activating the venv, and these helpers then fell through to a bare
# `python` call that doesn't exist. resolve_test_gate_python() must resolve
# python3 in that case, matching the
# scripts/install_modules/phases/12_alembic.sh::resolve_alembic_python
# pattern used elsewhere in the installer.
_write_fake_bin_with_only_python3() {
  local bin_dir="$1"
  ln -s "$(command -v python3)" "$bin_dir/python3"
  ln -s "$(command -v bash)" "$bin_dir/bash"
}

@test "resolve_test_gate_python finds python3 when bare 'python' is absent from PATH" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  _write_fake_bin_with_only_python3 "$tmpdir/bin"

  run env -i "PATH=$tmpdir/bin" "HOME=$HOME" bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    PROJECT_VENV_DIR="/nonexistent"
    resolve_test_gate_python
  ' _ "$root"

  [ "$status" -eq 0 ]
  [[ "$output" == *"/python3" ]]
  rm -rf "$tmpdir"
}

@test "check_python_version succeeds on a system with only python3 on PATH (no bare 'python')" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  _write_fake_bin_with_only_python3 "$tmpdir/bin"

  run env -i "PATH=$tmpdir/bin" "HOME=$HOME" bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    PROJECT_VENV_DIR="/nonexistent"
    check_python_version
  ' _ "$root"

  [ "$status" -eq 0 ]
  rm -rf "$tmpdir"
}

@test "check_python_version fails with a diagnostic message when neither python3 nor python exist" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  ln -s "$(command -v bash)" "$tmpdir/bin/bash"

  run env -i "PATH=$tmpdir/bin" "HOME=$HOME" bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    PROJECT_VENV_DIR="/nonexistent"
    check_python_version
  ' _ "$root"

  [ "$status" -eq 1 ]
  [[ "$output" == *"Python bulunamadı"* ]]
  [[ "$output" == *"terminali kapatıp yeniden açın"* ]]
  rm -rf "$tmpdir"
}

@test "render_generated_secret_sentinels works on a system with only python3 on PATH" {
  local root tmpdir target
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  _write_fake_bin_with_only_python3 "$tmpdir/bin"
  target="$tmpdir/.env.test"
  cat > "$target" <<'ENV'
SIDAR_ENV=test
POSTGRES_PASSWORD=__GENERATE__
ENV

  run env -i "PATH=$tmpdir/bin" "HOME=$HOME" POSTGRES_PASSWORD='ci-service-password' bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    PROJECT_VENV_DIR="/nonexistent"
    render_generated_secret_sentinels "$2"
  ' _ "$root" "$target"

  [ "$status" -eq 0 ]
  grep -q '^POSTGRES_PASSWORD=ci-service-password$' "$target"
  rm -rf "$tmpdir"
}

@test "validate_coverage_ratchet_state works on a system with only python3 on PATH" {
  local root tmpdir statefile
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/bin"
  _write_fake_bin_with_only_python3 "$tmpdir/bin"
  statefile="$tmpdir/coverage_ratchet.toml"
  cat > "$statefile" <<'TOML'
[tool.coverage.report]
fail_under = 42
TOML

  run env -i "PATH=$tmpdir/bin" "HOME=$HOME" bash -c '
    source "$1/scripts/test_gates/environment_helpers.sh"
    PROJECT_VENV_DIR="/nonexistent"
    COVERAGE_RATCHET_STATE_FILE="$2"
    COVERAGE_RATCHET_MIN_EXISTING_GATE=0
    validate_coverage_ratchet_state
  ' _ "$root" "$statefile"

  [ "$status" -eq 0 ]
  [[ "$output" == "42" ]]
  rm -rf "$tmpdir"
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
