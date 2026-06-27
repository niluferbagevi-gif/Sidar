#!/usr/bin/env bats

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

run_python_env_module() {
  local snippet="$1"
  local root
  root="$(repo_root)"
  run bash -c '
    set -Eeuo pipefail
    repo_root="$1"
    test_snippet="$2"
    cd "$repo_root"
    eval "$test_snippet"
  ' _ "$root" "$snippet"
}

@test "python_env module install_python_deps uses all-extras without conflicting extra dev" {
  run_python_env_module '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    UPGRADE_LOCK=false
    PYTHON_VERSION="3.11"
    touch "$tmpdir/uv.lock"
    step() { :; }
    info() { :; }
    ok() { :; }
    warn() { :; }
    fail() { printf "%s\n" "$*" >&2; exit 1; }
    ensure_env_file_secrets_after_uv_sync() { :; }
    validate_runtime_env_loading() { :; }
    source ./scripts/install_modules/install_helpers.sh
    source ./scripts/install_modules/utils/python_env.sh
    cat > "$tmpdir/bin/dpkg-query" <<STUB
#!/usr/bin/env bash
printf "Status: install ok installed\n"
STUB
    cat > "$tmpdir/bin/uv" <<STUB
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/uv.log"
case "\$*" in
  "sync --frozen --all-extras") exit 0 ;;
  "run python -c import pydantic, pydantic_settings") exit 0 ;;
esac
exit 99
STUB
    chmod +x "$tmpdir/bin/dpkg-query" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"

    install_python_deps

    grep -q "^sync --frozen --all-extras$" "$tmpdir/uv.log"
    ! grep -q -- "--extra dev" "$tmpdir/uv.log"
  '
  [ "$status" -eq 0 ]
}

@test "python_env module create_uv_venv recreates mismatched Python venv" {
  run_python_env_module '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin" "$tmpdir/.venv/bin"
    SCRIPT_DIR="$tmpdir"
    PYTHON_VERSION="3.11"
    step() { :; }
    info() { :; }
    ok() { :; }
    warn() { printf "%s\n" "$*" >> "$tmpdir/warn.log"; }
    fail() { printf "%s\n" "$*" >&2; exit 1; }
    cat > "$tmpdir/.venv/bin/python" <<STUB
#!/usr/bin/env bash
printf "3.10\n"
STUB
    cat > "$tmpdir/bin/uv" <<STUB
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/uv.log"
if [[ "\$*" == "python install 3.11" ]]; then
  exit 0
fi
if [[ "\$*" == "venv --python 3.11 $tmpdir/.venv" ]]; then
  mkdir -p "$tmpdir/.venv/bin"
  cat > "$tmpdir/.venv/bin/activate" <<ACTIVATE
#!/usr/bin/env bash
export VIRTUAL_ENV="$tmpdir/.venv"
ACTIVATE
  cat > "$tmpdir/.venv/bin/python" <<PYTHON
#!/usr/bin/env bash
printf "3.11\\n"
PYTHON
  chmod +x "$tmpdir/.venv/bin/python"
  exit 0
fi
exit 99
STUB
    chmod +x "$tmpdir/.venv/bin/python" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"
    source ./scripts/install_modules/utils/python_env.sh

    create_uv_venv

    grep -q "^python install 3.11$" "$tmpdir/uv.log"
    grep -q "^venv --python 3.11 $tmpdir/.venv$" "$tmpdir/uv.log"
    [[ "$("$tmpdir/.venv/bin/python")" == "3.11" ]]
    grep -q "zorunlu sürüm 3.11" "$tmpdir/warn.log"
  '
  [ "$status" -eq 0 ]
}
