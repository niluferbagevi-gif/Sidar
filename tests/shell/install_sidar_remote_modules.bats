#!/usr/bin/env bats

bats_require_minimum_version 1.5.0

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

run_remote_module_snippet() {
  local snippet="$1"
  local root
  root="$(repo_root)"
  export -f write_fake_curl
  run bash -c '
    set -Eeuo pipefail
    repo_root="$1"
    test_snippet="$2"
    cd "$repo_root"
    export SIDAR_INSTALL_TEST_MODE=1
    export SIDAR_INSTALL_SKIP_RETRY_SLEEP=1
    export ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1
    set --
    source ./install_sidar.sh
    eval "$test_snippet"
  ' _ "$root" "$snippet"
}

write_fake_curl() {
  local bin_dir="$1"
  local mode="$2"

  mkdir -p "$bin_dir"
  cat > "$bin_dir/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
set -Eeuo pipefail

out=""
headers=""
url=""

while (($#)); do
  case "$1" in
    -o)
      out="$2"
      shift 2
      ;;
    -D)
      headers="$2"
      shift 2
      ;;
    -w)
      shift 2
      ;;
    --retry|--retry-delay|--connect-timeout|--max-time)
      shift 2
      ;;
    -fsSL)
      shift
      ;;
    --*)
      shift
      ;;
    *)
      url="$1"
      shift
      ;;
  esac
done

mkdir -p "$FAKE_CURL_STATE"
: "${headers:=$FAKE_CURL_STATE/headers}"
printf '%s\n' "$url" >> "$FAKE_CURL_STATE/urls.log"

case "${FAKE_CURL_MODE:-success}" in
  retry429)
    count_file="$FAKE_CURL_STATE/count"
    count="$(cat "$count_file" 2>/dev/null || printf '0')"
    count=$((count + 1))
    printf '%s' "$count" > "$count_file"
    if (( count <= 2 )); then
      printf 'HTTP/2 429\r\nRetry-After: 0\r\n' > "$headers"
      printf '429'
      exit 22
    fi
    printf 'HTTP/2 200\r\n' > "$headers"
    printf 'module payload from %s\n' "$url" > "$out"
    printf '200'
    ;;
  fail_bad_module)
    if [[ "$url" == */bad.sh ]]; then
      printf 'HTTP/2 429\r\nRetry-After: 0\r\n' > "$headers"
      printf '429'
      exit 22
    fi
    printf 'HTTP/2 200\r\n' > "$headers"
    printf 'ok module from %s\n' "$url" > "$out"
    printf '200'
    ;;
  always429)
    printf 'HTTP/2 429\r\nRetry-After: 0\r\n' > "$headers"
    printf '429'
    exit 22
    ;;
  success|*)
    printf 'HTTP/2 200\r\n' > "$headers"
    printf 'module payload from %s\n' "$url" > "$out"
    printf '200'
    ;;
esac
FAKE_CURL
  chmod +x "$bin_dir/curl"
  printf '%s' "$mode" > "$bin_dir/.mode"
}

@test "fallback module cache default is mktemp uid-scoped" {
  run_remote_module_snippet '
    [[ -z "${SIDAR_INSTALL_MODULE_CACHE_ROOT:-}" ]]
    prepare_install_module_cache_root
    expected_prefix="${TMPDIR:-/tmp}/sidar_install_modules_cache_$(id -u 2>/dev/null || printf unknown)."
    [[ "$SIDAR_INSTALL_MODULE_CACHE_ROOT" == "$expected_prefix"* ]]
    [[ -d "$SIDAR_INSTALL_MODULE_CACHE_ROOT" ]]
    [[ "$SIDAR_INSTALL_MODULE_CACHE_ROOT_AUTO" == "1" ]]
  '
  [ "$status" -eq 0 ]
}

@test "fallback module cache rejects symlink root" {
  run_remote_module_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/real"
    ln -s "$tmpdir/real" "$tmpdir/cache-link"
    export SIDAR_INSTALL_MODULE_CACHE_ROOT="$tmpdir/cache-link"

    ! ( prepare_install_module_cache_root )
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Fallback modül cache dizini sembolik link olamaz"* ]]
}

@test "download_remote_install_module retries HTTP 429" {
  run_remote_module_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    write_fake_curl "$tmpdir/bin" retry429
    export PATH="$tmpdir/bin:$PATH"
    export FAKE_CURL_STATE="$tmpdir/curl-state"
    export FAKE_CURL_MODE="$(cat "$tmpdir/bin/.mode")"
    export SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES=2
    export SIDAR_INSTALL_MODULE_RETRY_DELAY=0
    export SIDAR_INSTALL_MODULE_CACHE_ROOT="$tmpdir/cache"

    download_remote_install_module "install_helpers.sh" "https://mirror.example/install_modules" "$tmpdir/dest"

    [[ "$(cat "$FAKE_CURL_STATE/count")" == "3" ]]
    grep -q "module payload from https://mirror.example/install_modules/install_helpers.sh" "$tmpdir/dest/install_helpers.sh"
    test -f "$(remote_install_module_cached_path "install_helpers.sh" "https://mirror.example/install_modules").ok"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"http_status=429"* ]]
  [[ "$output" == *"Fallback modül indirildi: install_helpers.sh"* ]]
}

@test "download_remote_install_modules reports failed module name" {
  run_remote_module_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    write_fake_curl "$tmpdir/bin" fail_bad_module
    export PATH="$tmpdir/bin:$PATH"
    export FAKE_CURL_STATE="$tmpdir/curl-state"
    export FAKE_CURL_MODE="$(cat "$tmpdir/bin/.mode")"
    export SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES=0
    export SIDAR_INSTALL_MODULE_CACHE_ROOT="$tmpdir/cache"
    INSTALL_REMOTE_MODULES=("ok.sh" "bad.sh")

    ! download_remote_install_modules "https://mirror.example/install_modules" "$tmpdir/dest"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Fallback modül indirme başarısız (bad.sh)"* ]]
  [[ "$output" == *"Fallback modül indirme akışı bad.sh dosyasında durdu"* ]]
}

@test "download_install_modules_to_temp resumes already downloaded modules" {
  run_remote_module_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    write_fake_curl "$tmpdir/bin" success
    export PATH="$tmpdir/bin:$PATH"
    export FAKE_CURL_STATE="$tmpdir/curl-state"
    export FAKE_CURL_MODE="$(cat "$tmpdir/bin/.mode")"
    export SIDAR_INSTALL_MODULE_CACHE_ROOT="$tmpdir/cache"
    base_url="https://mirror.example/install_modules"
    INSTALL_REMOTE_MODULES=("install_helpers.sh" "utils/install_remediation.sh")

    cached_helper="$(remote_install_module_cached_path "install_helpers.sh" "$base_url")"
    mkdir -p "$(dirname "$cached_helper")"
    printf "cached helper\n" > "$cached_helper"
    printf "module=install_helpers.sh\nsource=%s\n" "$base_url" > "${cached_helper}.ok"

    download_install_modules_to_temp "$base_url"

    grep -q "cached helper" "$INSTALL_MODULE_DIR/install_helpers.sh"
    ! grep -q "/install_helpers.sh$" "$FAKE_CURL_STATE/urls.log"
    grep -q "/utils/install_remediation.sh$" "$FAKE_CURL_STATE/urls.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Fallback modül cache'den kullanıldı: install_helpers.sh"* ]]
}

@test "fallback raw downloader honors SIDAR_INSTALL_MODULE_BASE_URL" {
  run_remote_module_snippet '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    write_fake_curl "$tmpdir/bin" success
    export PATH="$tmpdir/bin:$PATH"
    export FAKE_CURL_STATE="$tmpdir/curl-state"
    export FAKE_CURL_MODE="$(cat "$tmpdir/bin/.mode")"
    export SIDAR_INSTALL_MODULE_BASE_URL="https://mirror.internal/sidar/install_modules"
    export SIDAR_INSTALL_MODULE_CACHE_ROOT="$tmpdir/cache"
    INSTALL_REMOTE_MODULES=("install_helpers.sh")

    download_install_modules_to_temp "$(resolve_remote_module_base)"

    grep -qx "https://mirror.internal/sidar/install_modules/install_helpers.sh" "$FAKE_CURL_STATE/urls.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Fallback modülleri geçici dizine indirildi"* ]]
}
