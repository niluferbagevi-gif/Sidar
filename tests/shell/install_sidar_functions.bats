#!/usr/bin/env bats

bats_require_minimum_version 1.5.0

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

run_installer_function() {
  local snippet="$1"
  local root
  root="$(repo_root)"
  run bash -c '
    set -Eeuo pipefail
    repo_root="$1"
    test_snippet="$2"
    cd "$repo_root"
    test_summary_tmpdir="$(mktemp -d)"
    trap "rm -rf \"$test_summary_tmpdir\"" EXIT
    export TEST_SUMMARY_JSON="$test_summary_tmpdir/nonexistent-test-summary.json"
    export SIDAR_INSTALL_TEST_MODE=1
    unset DATABASE_URL TEST_DATABASE_URL POSTGRES_PASSWORD
    set --
    source ./install_sidar.sh
    eval "$test_snippet"
  ' _ "$root" "$snippet"
}

@test "normalize_bool maps accepted true/false values and rejects unknown input" {
  run_installer_function '
    [[ "$(normalize_bool yes)" == "true" ]]
    [[ "$(normalize_bool EVET)" == "true" ]]
    [[ "$(normalize_bool 0)" == "false" ]]
    [[ "$(normalize_bool hayır)" == "false" ]]
    [[ -z "$(normalize_bool maybe)" ]]
  '
  [ "$status" -eq 0 ]
}

@test "Playwright Ubuntu override helpers detect Ubuntu 25+ and normalize the synthetic os-release" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/ubuntu26" <<EOF
ID=ubuntu
VERSION_ID="26.04"
EOF
    cat > "$tmpdir/ubuntu24" <<EOF
ID=ubuntu
VERSION_ID="24.04"
EOF
    cat > "$tmpdir/debian26" <<EOF
ID=debian
VERSION_ID="26"
EOF

    is_playwright_ubuntu_override_recommended "$tmpdir/ubuntu26"
    ! is_playwright_ubuntu_override_recommended "$tmpdir/ubuntu24"
    ! is_playwright_ubuntu_override_recommended "$tmpdir/debian26"
    prepare_playwright_ubuntu_override_file "$tmpdir/ubuntu26" "$tmpdir/override"
    grep -q "^ID=ubuntu$" "$tmpdir/override"
    grep -q "^VERSION_ID=\\\"24.04\\\"$" "$tmpdir/override"
  '
  [ "$status" -eq 0 ]
}

@test "resolve_playwright_python_spec reads the pyproject dependency-group and has a safe fallback" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/pyproject.toml" <<EOF
[dependency-groups]
dev = [
  "playwright>=1.60,<1.62",
]
EOF

    [[ "$(resolve_playwright_python_spec "$tmpdir/pyproject.toml")" == "playwright>=1.60,<1.62" ]]
    [[ "$(resolve_playwright_python_spec "$tmpdir/missing.toml")" == "playwright>=1.60,<1.62" ]]
  '
  [ "$status" -eq 0 ]
}

@test "install_playwright_browsers skips uv add when installed Playwright satisfies the repo spec" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=debian
VERSION_ID="13"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
printf "%s|%s\\n" "\$*" "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" >> "$tmpdir/python.log"
case "\$*" in
  "-c import playwright") exit 0 ;;
  "-m playwright install --with-deps chromium") echo "ERROR: Playwright does not support chromium on debian13-x64" >&2; exit 1 ;;
  "-m playwright install chromium")
    if [[ "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" == "ubuntu24.04-x64" ]]; then
      echo "BEWARE: your OS is not officially supported by Playwright; downloading fallback build for ubuntu24.04-x64." >&2
      exit 0
    fi
    echo "ERROR: Playwright does not support chromium on debian13-x64" >&2
    exit 1
    ;;
  "-m playwright install-deps chromium") exit 0 ;;
  "- playwright>=1.60,<1.62") exit 1 ;;
esac
exit 1
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
touch "$tmpdir/uv-called"
exit 99
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always
    playwright_linux_dependencies_ready() { return 0; }

    install_playwright_browsers

    [[ ! -e "$tmpdir/uv-called" ]]
    grep -q "^- playwright>=1.60,<1.62|$" "$tmpdir/python.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"gereksiz uv add upgrade fallback atlanıyor"* ]]
  [[ "$output" == *"OS override fallback ile tamamlandı"* ]]
  [[ "$output" != *"BEWARE: your OS is not officially supported"* ]]
}

@test "install_playwright_browsers upgrades outdated Playwright with the repo spec" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=debian
VERSION_ID="13"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
printf "%s|%s\\n" "\$*" "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" >> "$tmpdir/python.log"
case "\$*" in
  "-c import playwright") exit 0 ;;
  "-m playwright install --with-deps chromium") echo "ERROR: Playwright does not support chromium on debian13-x64" >&2; exit 1 ;;
  "-m playwright install chromium")
    if [[ -e "$tmpdir/upgraded" ]]; then exit 0; fi
    echo "ERROR: Playwright does not support chromium on debian13-x64" >&2
    exit 1
    ;;
  "- playwright>=1.60,<1.62") exit 0 ;;
esac
exit 1
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "%s\\n" "\$*" >> "$tmpdir/uv.log"
touch "$tmpdir/upgraded"
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    grep -q "^add --dev playwright>=1.60,<1.62$" "$tmpdir/uv.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"playwright>=1.60,<1.62 şartını sağlamıyor"* ]]
  [[ "$output" == *"upgrade fallback ile tamamlandı"* ]]
}

@test "install_playwright_browsers starts with the OS override on Ubuntu 25+" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=ubuntu
VERSION_ID="26.04"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
printf "%s|%s|%s\\n" "\$*" "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" "\${OS_RELEASE_PATH:-}" >> "$tmpdir/python.log"
if [[ "\$*" == "-" ]]; then
  exit 1
fi
if [[ "\$*" == "-m playwright install chromium" ]]; then
  echo "BEWARE: your OS is not officially supported by Playwright; downloading fallback build for ubuntu24.04-x64." >&2
  echo "Chromium override browser downloaded"
fi
if [[ "\$*" == "-m playwright install-deps chromium" ]]; then
  echo "Reading package lists..."
  echo "Solving dependencies..."
  echo "0 upgraded, 0 newly installed, 0 to remove and 4 not upgraded."
fi
EOF
    cat > "$tmpdir/bin/apt" <<EOF
#!/usr/bin/env bash
echo "Listing..."
EOF
    cat > "$tmpdir/bin/dpkg-query" <<EOF
#!/usr/bin/env bash
printf "ii "
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/apt" "$tmpdir/bin/dpkg-query"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    # playwright_linux_dependencies_ready() consults the mocked apt (which
    # reports nothing installed) and falls through to the mocked dpkg-query
    # (which reports every package as "ii", i.e. installed) so the apt
    # pre-check short-circuits before install-deps chromium ever runs; only
    # -c import playwright, the host-support probe, the latest-supported
    # Ubuntu probe and the override chromium install invoke python.
    [[ "$(wc -l < "$tmpdir/python.log")" -eq 4 ]]
    sed -n "1p" "$tmpdir/python.log" | grep -q "^-c import playwright||$tmpdir/os-release$"
    sed -n "2p" "$tmpdir/python.log" | grep -q "^-||$tmpdir/os-release$"
    sed -n "3p" "$tmpdir/python.log" | grep -q "^-||$tmpdir/os-release$"
    sed -n "4p" "$tmpdir/python.log" | grep -q "^-m playwright install chromium|ubuntu24.04-x64|"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"en yakın desteklenen Ubuntu OS override kurulumu doğrudan deneniyor"* ]]
  [[ "$output" == *"Chromium override browser downloaded"* ]]
  [[ "$output" == *"apt ön taramasında hazır görünüyor"* ]]
  [[ "$output" == *"proaktif OS override ile tamamlandı"* ]]
  [[ "$output" != *"0 upgraded, 0 newly installed, 0 to remove and 4 not upgraded"* ]]
  [[ "$output" != *"Solving dependencies"* ]]
  [[ "$output" != *"BEWARE: your OS is not officially supported"* ]]
  [[ "$output" != *"--with-deps"* ]]
}

@test "install_playwright_browsers installs the fixed apt dependency list when Ubuntu override install-deps fails" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=ubuntu
VERSION_ID="26.04"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "-c import playwright") exit 0 ;;
  "-m playwright install chromium") exit 0 ;;
  "-m playwright install-deps chromium") echo "install-deps unsupported" >&2; exit 1 ;;
esac
exit 1
EOF
    cat > "$tmpdir/bin/apt" <<EOF
#!/usr/bin/env bash
echo "Listing..."
EOF
    cat > "$tmpdir/bin/dpkg-query" <<EOF
#!/usr/bin/env bash
exit 1
EOF
    cat > "$tmpdir/bin/apt-cache" <<EOF
#!/usr/bin/env bash
[[ "\$*" == "show libgtk-3-0t64" ]]
EOF
    cat > "$tmpdir/bin/sudo" <<EOF
#!/usr/bin/env bash
count=0
[[ -f "$tmpdir/sudo-count" ]] && count="\$(cat "$tmpdir/sudo-count")"
count=\$((count + 1))
printf "%s" "\$count" > "$tmpdir/sudo-count"
printf "%s\\n" "\$*" >> "$tmpdir/sudo.log"
[[ "\$count" -eq 1 ]] && exit 1
exit 0
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/apt" "$tmpdir/bin/dpkg-query" "$tmpdir/bin/apt-cache" "$tmpdir/bin/sudo"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    # apt/dpkg-query report every dependency missing, so the apt pre-check
    # is not ready; the proactive fixed apt-list attempt (1st sudo call)
    # deliberately fails so install-deps chromium actually runs, fails, and
    # the fixed apt dependency list is retried (2nd sudo call) and succeeds.
    [[ "$(cat "$tmpdir/sudo-count")" -eq 2 ]]
    grep -q "^DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxshmfence1 libgbm1 libgtk-3-0t64 libpango-1.0-0 libcairo2 libasound2t64$" "$tmpdir/sudo.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"apt ön taraması eksik Chromium bağımlılıkları buldu"* ]]
  [[ "$output" == *"Ubuntu 26.04 için sabit Chromium apt bağımlılık listesi deneniyor"* ]]
  [[ "$output" == *"sabit apt fallback ile kuruldu"* ]]
  [[ "$output" == *"proaktif OS override ile tamamlandı"* ]]
}

@test "install_playwright_browsers treats unsupported install-deps output with exit zero as a fallback signal" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=ubuntu
VERSION_ID="26.04"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "-c import playwright") exit 0 ;;
  "-m playwright install chromium") exit 0 ;;
  "-m playwright install-deps chromium")
    echo "BEWARE: your OS is not officially supported by Playwright." >&2
    echo "Cannot install dependencies for ubuntu26.04-x64 with Playwright 1.60.0!" >&2
    exit 0
    ;;
esac
exit 1
EOF
    cat > "$tmpdir/bin/apt" <<EOF
#!/usr/bin/env bash
echo "Listing..."
EOF
    cat > "$tmpdir/bin/dpkg-query" <<EOF
#!/usr/bin/env bash
exit 1
EOF
    cat > "$tmpdir/bin/apt-cache" <<EOF
#!/usr/bin/env bash
[[ "\$*" == "show libgtk-3-0t64" ]]
EOF
    cat > "$tmpdir/bin/sudo" <<EOF
#!/usr/bin/env bash
count=0
[[ -f "$tmpdir/sudo-count" ]] && count="\$(cat "$tmpdir/sudo-count")"
count=\$((count + 1))
printf "%s" "\$count" > "$tmpdir/sudo-count"
printf "%s\\n" "\$*" >> "$tmpdir/sudo.log"
[[ "\$count" -eq 1 ]] && exit 1
exit 0
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/apt" "$tmpdir/bin/dpkg-query" "$tmpdir/bin/apt-cache" "$tmpdir/bin/sudo"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    # apt pre-check is forced not-ready, the proactive fixed apt-list attempt
    # (1st sudo call) deliberately fails so install-deps chromium actually
    # runs and returns its exit-zero-but-actually-failed BEWARE/Cannot output,
    # which must still be treated as a failure requiring the fixed apt list
    # fallback (2nd sudo call, which succeeds).
    [[ "$(cat "$tmpdir/sudo-count")" -eq 2 ]]
    grep -q "libnss3 libnspr4" "$tmpdir/sudo.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" != *"BEWARE: your OS is not officially supported"* ]]
  [[ "$output" != *"Cannot install dependencies for ubuntu26.04-x64"* ]]
  [[ "$output" == *"Ubuntu 26.04 için sabit Chromium apt bağımlılık listesi deneniyor"* ]]
  [[ "$output" == *"sabit apt fallback ile kuruldu"* ]]
}

@test "install_playwright_browsers verifies critical libraries after a silent install-deps success" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=ubuntu
VERSION_ID="26.04"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "-c import playwright") exit 0 ;;
  "-m playwright install chromium") exit 0 ;;
  "-m playwright install-deps chromium") exit 0 ;;
esac
exit 1
EOF
    cat > "$tmpdir/bin/apt" <<EOF
#!/usr/bin/env bash
echo "Listing..."
EOF
    cat > "$tmpdir/bin/dpkg-query" <<EOF
#!/usr/bin/env bash
exit 1
EOF
    cat > "$tmpdir/bin/apt-cache" <<EOF
#!/usr/bin/env bash
[[ "\$*" == "show libgtk-3-0t64" ]]
EOF
    cat > "$tmpdir/bin/sudo" <<EOF
#!/usr/bin/env bash
count=0
[[ -f "$tmpdir/sudo-count" ]] && count="\$(cat "$tmpdir/sudo-count")"
count=\$((count + 1))
printf "%s" "\$count" > "$tmpdir/sudo-count"
printf "%s\\n" "\$*" >> "$tmpdir/sudo.log"
[[ "\$count" -eq 1 ]] && exit 1
exit 0
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/apt" "$tmpdir/bin/dpkg-query" "$tmpdir/bin/apt-cache" "$tmpdir/bin/sudo"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    # apt pre-check is forced not-ready throughout (both before and after
    # install-deps), the proactive fixed apt-list attempt (1st sudo call)
    # deliberately fails so install-deps chromium actually runs; it exits 0
    # silently but the post-install readiness re-check still reports missing
    # libraries, so the fixed apt list is retried (2nd sudo call) and succeeds.
    [[ "$(cat "$tmpdir/sudo-count")" -eq 2 ]]
    grep -q "libnss3 libnspr4" "$tmpdir/sudo.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"kritik Chromium bağımlılıkları doğrulanamadı"* ]]
  [[ "$output" == *"sabit apt fallback ile kuruldu"* ]]
}

@test "install_playwright_browsers keeps the Ubuntu override warning visible when the proactive attempt fails" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=ubuntu
VERSION_ID="26.04"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
case "\$*" in
  "-c import playwright") exit 0 ;;
  "-m playwright install chromium")
    echo "BEWARE: your OS is not officially supported by Playwright; downloading fallback build for ubuntu24.04-x64." >&2
    exit 1
    ;;
  "-m playwright install --with-deps chromium") exit 0 ;;
esac
exit 1
EOF
    chmod +x "$tmpdir/bin/python"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"BEWARE: your OS is not officially supported"* ]]
  [[ "$output" == *"proaktif OS override kurulumu başarısız oldu"* ]]
  [[ "$output" == *"Playwright kurulumu tamamlandı (chromium, --with-deps)"* ]]
}

@test "install_playwright_browsers preserves the standard with-deps path on Ubuntu 24.04" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=ubuntu
VERSION_ID="24.04"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
printf "%s|%s|%s\\n" "\$*" "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" "\${OS_RELEASE_PATH:-}" >> "$tmpdir/python.log"
EOF
    chmod +x "$tmpdir/bin/python"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    [[ "$(wc -l < "$tmpdir/python.log")" -eq 2 ]]
    sed -n "2p" "$tmpdir/python.log" | grep -q "^-m playwright install --with-deps chromium||$tmpdir/os-release$"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"yalnızca Chromium (--with-deps) kuruluyor"* ]]
  [[ "$output" == *"Playwright kurulumu tamamlandı (chromium, --with-deps)"* ]]
  [[ "$output" != *"proaktif OS override"* ]]
}

@test "resolve_runtime_mode_choice normalizes local/docker aliases and falls back to ask" {
  run_installer_function '
    [[ "$(resolve_runtime_mode_choice 1)" == "local" ]]
    [[ "$(resolve_runtime_mode_choice geliştirici)" == "local" ]]
    [[ "$(resolve_runtime_mode_choice full-docker)" == "docker" ]]
    [[ "$(resolve_runtime_mode_choice unexpected)" == "ask" ]]
  '
  [ "$status" -eq 0 ]
}

@test "is_weak_secret_value rejects placeholders and accepts high entropy tokens" {
  run_installer_function '
    is_weak_secret_value postgres
    is_weak_secret_value change-me-please
    is_weak_secret_value Password1
    if is_weak_secret_value N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
}

@test "harden_database_credentials rewrites weak DATABASE_URL and syncs postgres env values" {
  local tmpdir env_file
  tmpdir="$(mktemp -d)"
  env_file="$tmpdir/.env"
  cat > "$env_file" <<'ENV'
SIDAR_ENV=development
DATABASE_URL=postgresql+asyncpg://sidar:postgres@localhost:5432/sidar?ssl=disable
POSTGRES_PASSWORD=postgres
ENV

  run_installer_function "
    generate_secure_token() { printf '%s\\n' 'GeneratedStrongDbToken_1234567890'; }
    harden_database_credentials '$env_file'
    grep -q '^DATABASE_URL=postgresql+asyncpg://sidar:GeneratedStrongDbToken_1234567890@localhost:5432/sidar?ssl=disable$' '$env_file'
    grep -q '^POSTGRES_PASSWORD=GeneratedStrongDbToken_1234567890$' '$env_file'
    grep -q '^POSTGRES_USER=sidar$' '$env_file'
    grep -q '^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:GeneratedStrongDbToken_1234567890@postgres:5432/sidar$' '$env_file'
  "
  rm -rf "$tmpdir"
  [ "$status" -eq 0 ]
}

@test "harden_database_credentials leaves strong DATABASE_URL passwords unchanged" {
  local tmpdir env_file
  tmpdir="$(mktemp -d)"
  env_file="$tmpdir/.env"
  cat > "$env_file" <<'ENV'
SIDAR_ENV=production
DATABASE_URL=postgresql+asyncpg://sidar:N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh@localhost:5432/sidar
POSTGRES_PASSWORD=N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh
ENV

  run_installer_function "
    harden_database_credentials '$env_file'
    grep -q '^DATABASE_URL=postgresql+asyncpg://sidar:N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh@localhost:5432/sidar$' '$env_file'
    grep -q '^POSTGRES_PASSWORD=N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh$' '$env_file'
    if grep -q '^SIDAR_CONTAINER_DATABASE_URL=' '$env_file'; then
      exit 1
    fi
  "
  rm -rf "$tmpdir"
  [ "$status" -eq 0 ]
}


@test "propagate_shared_secrets_to_env_variants always syncs PostgreSQL credentials" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    master_pw="MasterStrongDbToken_1234567890"
    stale_pw="sidar_test_secure_pw"
    preserved_api_key="N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh"

    cat > "$tmpdir/.env" <<ENV
POSTGRES_PASSWORD=${master_pw}
DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@postgres:5432/sidar
API_KEY=MasterApiKeyValue_1234567890
ENV

    for variant in .env.development .env.test .env.advanced; do
      cat > "$tmpdir/$variant" <<ENV
POSTGRES_PASSWORD=${stale_pw}
DATABASE_URL=postgresql+asyncpg://sidar:${stale_pw}@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${stale_pw}@postgres:5432/sidar
API_KEY=${preserved_api_key}
ENV
      cat > "$tmpdir/${variant}.example" <<ENV
POSTGRES_PASSWORD=example_password
DATABASE_URL=postgresql+asyncpg://sidar:example_password@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:example_password@postgres:5432/sidar
API_KEY=example_api_key
ENV
    done

    # PostgreSQL credential rewriting itself is delegated to the idempotent
    # scripts.sync_database_passwords Python helper (see
    # tests/unit/scripts/test_sync_database_passwords.py for its coverage),
    # invoked unconditionally via sync_database_env_chain_after_setup at the
    # end of propagate_shared_secrets_to_env_variants. Stub that call out
    # here so this bats test stays hermetic (no real uv/python invocation
    # against a fake SCRIPT_DIR) while still asserting the delegation always
    # happens exactly once, alongside the direct bash-level shared secret
    # (API_KEY etc.) propagation.
    sync_database_env_chain_after_setup() {
      echo "called" >> "$tmpdir/db-sync-calls"
    }

    SCRIPT_DIR="$tmpdir"
    propagate_shared_secrets_to_env_variants "$tmpdir/.env"

    [[ "$(wc -l < "$tmpdir/db-sync-calls")" -eq 1 ]]

    for variant in .env.development .env.test .env.advanced; do
      grep -q "^API_KEY=${preserved_api_key}$" "$tmpdir/$variant"
    done
  '
  [ "$status" -eq 0 ]
}


@test "modular harden_database_credentials syncs explicit env variants" {
  run_installer_function '
    source ./scripts/install_modules/utils/db_credentials.sh
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    env_file="$tmpdir/.env"
    variant_file="$tmpdir/.env.test"

    cat > "$env_file" <<ENV
SIDAR_ENV=development
DATABASE_URL=postgresql+asyncpg://sidar:postgres@127.0.0.1:5432/sidar?ssl=disable
POSTGRES_PASSWORD=postgres
ENV
    cat > "$variant_file" <<ENV
POSTGRES_PASSWORD=sidar_test_secure_pw
DATABASE_URL=postgresql+asyncpg://sidar:sidar_test_secure_pw@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:sidar_test_secure_pw@postgres:5432/sidar
ENV

    generate_secure_token() { printf "%s\n" "GeneratedStrongDbToken_1234567890"; }
    harden_database_credentials "$env_file" "$variant_file"

    grep -q "^POSTGRES_PASSWORD=GeneratedStrongDbToken_1234567890$" "$variant_file"
    grep -q "^DATABASE_URL=postgresql+asyncpg://sidar:GeneratedStrongDbToken_1234567890@127.0.0.1:5432/sidar?ssl=disable$" "$variant_file"
    grep -q "^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:GeneratedStrongDbToken_1234567890@postgres:5432/sidar$" "$variant_file"
  '
  [ "$status" -eq 0 ]
}

@test "modular sync_postgres_env_with_database_url forces default env variant consistency" {
  run_installer_function '
    source ./scripts/install_modules/utils/db_credentials.sh
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    env_file="$tmpdir/.env"
    master_pw="MasterStrongDbToken_1234567890"
    stale_pw="sidar_test_secure_pw"

    cat > "$env_file" <<ENV
DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@127.0.0.1:5432/sidar?ssl=disable
POSTGRES_PASSWORD=old_value_that_should_be_replaced
ENV
    for variant in .env.development .env.test .env.advanced; do
      cat > "$tmpdir/${variant}.example" <<ENV
POSTGRES_PASSWORD=example_password
DATABASE_URL=postgresql+asyncpg://sidar:example_password@127.0.0.1:5432/sidar
ENV
      cat > "$tmpdir/$variant" <<ENV
POSTGRES_PASSWORD=${stale_pw}
DATABASE_URL=postgresql+asyncpg://sidar:${stale_pw}@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${stale_pw}@postgres:5432/sidar
ENV
    done

    SCRIPT_DIR="$tmpdir"
    sync_postgres_env_with_database_url "$env_file"

    for variant in .env.development .env.test .env.advanced; do
      grep -q "^POSTGRES_USER=sidar$" "$tmpdir/$variant"
      grep -q "^POSTGRES_PASSWORD=${master_pw}$" "$tmpdir/$variant"
      grep -q "^POSTGRES_DB=sidar$" "$tmpdir/$variant"
      grep -q "^DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@127.0.0.1:5432/sidar?ssl=disable$" "$tmpdir/$variant"
      grep -q "^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@postgres:5432/sidar$" "$tmpdir/$variant"
    done
  '
  [ "$status" -eq 0 ]
}

@test "SIDAR_LOCALE=en renders installer help in English" {
  local root
  root="$(repo_root)"
  run env SIDAR_INSTALL_TEST_MODE=1 SIDAR_LOCALE=en bash "$root/install_sidar.sh" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage:"* ]]
  [[ "$output" == *"Select installer message language"* ]]
  [[ "$output" == *"--with-integration"* ]]
  [[ "$output" == *"--ci-full"* ]]
  [[ "$output" == *"--enable-autonomous-cron"* ]]
  [[ "$output" != *"Kullanım:"* ]]
}

@test "LANG=en_US renders invalid argument warnings in English" {
  local root
  root="$(repo_root)"
  run env -u SIDAR_LOCALE SIDAR_INSTALL_TEST_MODE=1 LANG=en_US.UTF-8 bash "$root/install_sidar.sh" --not-a-real-flag
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown argument: --not-a-real-flag"* ]]
  [[ "$output" != *"Bilinmeyen argüman"* ]]
}

@test "default installer help remains Turkish" {
  local root
  root="$(repo_root)"
  run env SIDAR_INSTALL_TEST_MODE=1 SIDAR_LOCALE=tr bash "$root/install_sidar.sh" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Kullanım:"* ]]
  [[ "$output" == *"Kurulum mesaj dilini seçer"* ]]
  [[ "$output" == *"--with-integration"* ]]
  [[ "$output" == *"--ci-full"* ]]
  [[ "$output" == *"--enable-autonomous-cron"* ]]
}

@test "installer finish guidance highlights full integration verification command" {
  local root
  root="$(repo_root)"

  # Kurulum özeti/kapanış rehberliği scripts/install_modules/phases/07_finish.sh
  # ve tam doğrulama kapsamı özeti scripts/install_modules/phases/10_validation.sh
  # içine modülerize edildi; install_sidar.sh yalnızca bu fazları yükler.
  grep -q "bash run_tests.sh --stage all" "$root/scripts/install_modules/phases/07_finish.sh"
  grep -q "bash run_tests.sh --stage integration" "$root/scripts/install_modules/phases/07_finish.sh"
  grep -q "bash run_tests.sh --stage e2e" "$root/scripts/install_modules/phases/07_finish.sh"
  grep -q "RUN_BENCHMARKS=required bash run_tests.sh" "$root/scripts/install_modules/phases/07_finish.sh"
  grep -q "./install_sidar.sh --ci-full" "$root/scripts/install_modules/phases/10_validation.sh"
  grep -q "📊 Kurulum doğrulama kapsamı" "$root/scripts/install_modules/phases/10_validation.sh"
  grep -q "scripts/install_modules/phases/07_finish.sh" "$root/install_sidar.sh"
  grep -q "scripts/install_modules/phases/10_validation.sh" "$root/install_sidar.sh"
}

@test "Playwright browser installer lives in a dedicated phase module" {
  local root
  root="$(repo_root)"

  grep -q '"phases/13_playwright.sh"' "$root/install_sidar.sh"
  grep -q "scripts/install_modules/phases/13_playwright.sh" "$root/install_sidar.sh"
  grep -q "^install_playwright_browsers()" "$root/scripts/install_modules/phases/13_playwright.sh"
  ! grep -q "^install_playwright_browsers()" "$root/install_sidar.sh"
}

@test "Alembic migration helpers live in a dedicated phase module" {
  local root
  root="$(repo_root)"

  grep -q '"phases/12_alembic.sh"' "$root/install_sidar.sh"
  grep -q "scripts/install_modules/phases/12_alembic.sh" "$root/install_sidar.sh"
  grep -q "^run_migrations()" "$root/scripts/install_modules/phases/12_alembic.sh"
  grep -q "^is_alembic_at_head()" "$root/scripts/install_modules/phases/12_alembic.sh"
  grep -q "^ensure_postgres_databases_exist()" "$root/scripts/install_modules/phases/12_alembic.sh"
  run ! grep -q "^run_migrations()" "$root/install_sidar.sh"
  ! grep -q "^is_alembic_at_head()" "$root/install_sidar.sh"
}

@test "React frontend setup lives in a dedicated phase module" {
  local root
  root="$(repo_root)"

  grep -q '"phases/14_react.sh"' "$root/install_sidar.sh"
  grep -q "scripts/install_modules/phases/14_react.sh" "$root/install_sidar.sh"
  grep -q "^setup_react_frontend()" "$root/scripts/install_modules/phases/14_react.sh"
  grep -q "setup_react_frontend" "$root/scripts/install_modules/phases/05_frontend.sh"
  ! grep -q "^setup_react_frontend()" "$root/install_sidar.sh"
}

@test "React build summary warns that frontend QA was not run" {
  run_installer_function '
    FRONTEND_QUALITY_STATUS="atlandi_bayrak"
    print_react_frontend_qa_status_block
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"FRONTEND QA ÇALIŞTIRILMADI"* ]]
  [[ "$output" == *"React build geçti ≠ frontend QA geçti"* ]]
  [[ "$output" == *"npm run lint && npm run typecheck && npm run test:coverage && npm run test:e2e:smoke"* ]]
}

@test "React build summary uses red block when frontend QA failed" {
  run_installer_function '
    FRONTEND_QUALITY_STATUS="hata"
    print_react_frontend_qa_status_block
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"FRONTEND QA BAŞARISIZ"* ]]
  [[ "$output" == *"build geçti ≠ frontend QA geçti"* ]]
}

@test "DATABASE_URL defaults live in a dedicated utility module" {
  local root
  root="$(repo_root)"

  grep -q '"utils/database_url.sh"' "$root/install_sidar.sh"
  grep -q "scripts/install_modules/utils/database_url.sh" "$root/install_sidar.sh"
  grep -q "database_url.sh" "$root/scripts/install_modules/phases/04_workspace.sh"
  grep -q "^ensure_database_url_defaults()" "$root/scripts/install_modules/utils/database_url.sh"
  grep -q "^write_generated_default_database_url()" "$root/scripts/install_modules/utils/database_url.sh"
  grep -q "^sync_postgres_env_with_database_url()" "$root/scripts/install_modules/utils/database_url.sh"
  run ! grep -q "^ensure_database_url_defaults()" "$root/install_sidar.sh"
  ! grep -q "^sync_postgres_env_with_database_url()" "$root/scripts/install_modules/utils/db_credentials.sh"
}

@test "ensure_database_url_defaults preserves existing strong PostgreSQL password when composing missing DSNs" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    env_file="$tmpdir/.env"
    existing_password="N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh"
    cat > "$env_file" <<EOF
POSTGRES_USER=sidar_user
POSTGRES_PASSWORD=$existing_password
POSTGRES_DB=sidar_db
EOF
    generate_secure_token() {
      printf "%s\n" "SHOULD_NOT_BE_USED_1234567890"
    }

    ensure_database_url_defaults "$env_file"

    grep -q "^POSTGRES_USER=sidar_user$" "$env_file"
    grep -q "^POSTGRES_PASSWORD=$existing_password$" "$env_file"
    grep -q "^POSTGRES_DB=sidar_db$" "$env_file"
    grep -q "^DATABASE_URL=postgresql+asyncpg://sidar_user:$existing_password@127.0.0.1:5432/sidar_db$" "$env_file"
    grep -q "^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar_user:$existing_password@postgres:5432/sidar_db$" "$env_file"
    ! grep -q "SHOULD_NOT_BE_USED" "$env_file"
  '
  [ "$status" -eq 0 ]
}

@test "ensure_database_url_defaults rotates weak PostgreSQL password when composing missing DSNs" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    env_file="$tmpdir/.env"
    generated_password="R9mKq2pT7vXc5aHj6sDf4Gh8N"
    cat > "$env_file" <<EOF
POSTGRES_PASSWORD=postgres
EOF
    generate_secure_token() {
      printf "%s\n" "$generated_password"
    }

    ensure_database_url_defaults "$env_file"

    grep -q "^POSTGRES_USER=sidar$" "$env_file"
    grep -q "^POSTGRES_PASSWORD=$generated_password$" "$env_file"
    grep -q "^POSTGRES_DB=sidar$" "$env_file"
    grep -q "^DATABASE_URL=postgresql+asyncpg://sidar:$generated_password@127.0.0.1:5432/sidar$" "$env_file"
    grep -q "^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:$generated_password@postgres:5432/sidar$" "$env_file"
    [[ "${DB_PASSWORD_HARDENED:-}" == "true" ]]
  '
  [ "$status" -eq 0 ]
}

@test "sync_database_env_chain_after_setup reruns helper even when prior sync marker exists" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    mkdir -p "$tmpdir/bin" "$tmpdir/scripts"
    touch "$tmpdir/scripts/sync_database_passwords.py"
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/uv.log"
exit 0
EOF
    chmod +x "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"
    export SIDAR_DATABASE_ENV_CHAIN_SYNCED=1

    sync_database_env_chain_after_setup
    sync_database_env_chain_after_setup

    [[ "$(wc -l < "$tmpdir/uv.log")" -eq 4 ]]
    [[ "$(grep -c -- "-m scripts.sync_database_passwords --all-envs" "$tmpdir/uv.log")" -eq 2 ]]
    [[ "$(grep -c -- "-m scripts.sync_database_passwords --remove-explicit-urls" "$tmpdir/uv.log")" -eq 2 ]]
  '
  [ "$status" -eq 0 ]
  [[ "$output" != *"zaten eşitlendi; tekrar yazım atlandı"* ]]
}

@test "installer validation coverage summary calls out skipped full suites" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/pyproject.toml" <<EOF
[tool.coverage.report]
fail_under = 87
EOF

    SMOKE_TEST_STATUS="tamamlandi"
    INTEGRATION_TEST_STATUS="atlandi_bayrak"
    CI_FULL_VALIDATION_STATUS="atlandi_bayrak"
    print_install_validation_coverage
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Smoke:"*"TAMAMLANDI"* ]]
  [[ "$output" == *"Integration:"*"ATLANDI"*"run_tests.sh --stage integration"* ]]
  [[ "$output" == *"E2E:"*"ATLANDI"*"run_tests.sh --stage e2e"* ]]
  [[ "$output" == *"Benchmark:"*"ATLANDI"* ]]
  [[ "$output" == *"Coverage ratchet / fail-under notu"* ]]
  [[ "$output" == *"pyproject.toml coverage fail-under eşiği: 87%"* ]]
  [[ "$output" == *"Local/CI gate:"*"ratchet baseline 87%"* ]]
  [[ "$output" == *"Coverage campaign hedefi: 100%"*"coverage-campaign opt-in"* ]]
  [[ "$output" == *"tam doğrulama çalışmadıysa coverage fail-under ve ratchet devreye girmiş sayılmaz"* ]]
  [[ "$output" == *"Test rehberi: docs/TESTING.md"* ]]
  [[ "$output" == *"GitHub Actions CI parite haritası"* ]]
  [[ "$output" == *"CI step: Run frontend lint/type-check/audit gate"*"bash run_tests.sh --stage frontend"* ]]
  [[ "$output" == *"CI step: Run test suite + coverage + benchmark"*"bash run_tests.sh --stage all"* ]]
  [[ "$output" == *"./install_sidar.sh --production-readiness"* ]]
  [[ "$output" == *"bash run_tests.sh --stage all"* ]]
}


@test "installer source exposes validation and GPU functions from modular files" {
  run_installer_function '
    shopt -s extdebug
    validation_source="$(declare -F run_install_ci_full_validation)"
    gpu_source="$(declare -F detect_gpu)"
    [[ "$validation_source" == *"scripts/install_modules/phases/10_validation.sh" ]]
    [[ "$gpu_source" == *"scripts/install_modules/utils/gpu_utils.sh" ]]
  '
  [ "$status" -eq 0 ]
}

@test "ci-full validation runs canonical production-readiness make target" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    RUN_CI_FULL_VALIDATION=true
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/Makefile" <<EOF
production-readiness:
	@true
EOF
    cat > "$tmpdir/bin/make" <<EOF
#!/usr/bin/env bash
printf "%s|%s|%s|%s|%s\\n" "\${TEST_PROFILE:-}" "\${RUN_BENCHMARKS:-}" "\${RUN_FRONTEND_E2E:-}" "\${AUTO_OPEN_ARTIFACTS:-}" "\$*" > "$tmpdir/make.log"
EOF
    chmod +x "$tmpdir/bin/make"
    export PATH="$tmpdir/bin:$PATH"
    cat > "$tmpdir/run_tests.sh" <<EOF
#!/usr/bin/env bash
exit 99
EOF
    chmod +x "$tmpdir/run_tests.sh"

    run_install_ci_full_validation

    [[ "$CI_FULL_VALIDATION_STATUS" == "tamamlandi" ]]
    grep -q "^|||0|production-readiness$" "$tmpdir/make.log"
  '
  [ "$status" -eq 0 ]
}


@test "development full validation prompt runs GPU stress full gate when accepted" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    RUN_CI_FULL_VALIDATION=false
    GPU_AVAILABLE=true
    SMOKE_TEST_STATUS="tamamlandi"
    NO_INTERACTION=false
    AUTO_INSTALL=false
    SILENT_MODE=false
    prompt_yes_no_with_timeout_default_no() { printf "e"; }
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/Makefile" <<EOF
dev-full:
	@true
EOF
    cat > "$tmpdir/bin/make" <<EOF
#!/usr/bin/env bash
printf "%s|%s\\n" "\${AUTO_OPEN_ARTIFACTS:-}" "\$*" > "$tmpdir/make.log"
mkdir -p "$tmpdir/artifacts"
cat > "$tmpdir/artifacts/test-summary.json" <<JSON
{"frontend_lint":"passed","frontend_typecheck":"passed","frontend_coverage":"passed","frontend_e2e":"passed"}
JSON
EOF
    chmod +x "$tmpdir/bin/make"
    export PATH="$tmpdir/bin:$PATH"
    cat > "$tmpdir/run_tests.sh" <<EOF
#!/usr/bin/env bash
exit 99
EOF
    chmod +x "$tmpdir/run_tests.sh"
    TEST_PROFILE=local
    SIDAR_PRODUCTION_READINESS=0
    PRODUCTION_READINESS=0
    RUN_BENCHMARKS=""
    RUN_FRONTEND_E2E=""
    export TEST_SUMMARY_JSON="$tmpdir/artifacts/test-summary.json"

    run_install_ci_full_validation

    [[ "$CI_FULL_VALIDATION_STATUS" == "tamamlandi" ]]
    [[ "$FRONTEND_QUALITY_STATUS" == "tamamlandi" ]]
    grep -q "^0|dev-full$" "$tmpdir/make.log"
  '
  [ "$status" -eq 0 ]
}

@test "development full validation prompt is skipped unless GPU and smoke service gate are ready" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    RUN_CI_FULL_VALIDATION=false
    GPU_AVAILABLE=false
    SMOKE_TEST_STATUS="tamamlandi"
    NO_INTERACTION=false
    AUTO_INSTALL=false
    SILENT_MODE=false
    prompt_yes_no_with_timeout_default_no() { exit 99; }
    touch "$tmpdir/run_tests.sh"
    TEST_PROFILE=local
    SIDAR_PRODUCTION_READINESS=0
    PRODUCTION_READINESS=0
    RUN_BENCHMARKS=""
    RUN_FRONTEND_E2E=""

    run_install_ci_full_validation

    [[ "$CI_FULL_VALIDATION_STATUS" == "atlandi_bayrak" ]]
  '
  [ "$status" -eq 0 ]
}

@test "run_smoke_tests defensively repairs private key and session file permissions after pytest" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin" "$tmpdir/tests/smoke"
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
exit 0
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "%s\\n" "\$*" > "$tmpdir/uv.args"
exit 0
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/uv"
    printf "OPENAI_API_KEY=x\\n" > "$tmpdir/keys.env"
    printf "{\"token\":\"x\"}\\n" > "$tmpdir/session.json"
    chmod 644 "$tmpdir/keys.env" "$tmpdir/session.json"

    export PATH="$tmpdir/bin:$PATH"
    export SIDAR_KEYS_FILE="$tmpdir/keys.env"
    export SIDAR_SESSION_FILE="$tmpdir/session.json"
    SCRIPT_DIR="$tmpdir"
    RUN_SMOKE_TESTS_MODE=always
    WSL2=false
    WSLCONFIG_CHANGED=false
    GPU_AVAILABLE=false
    wait_for_redis_before_smoke_tests() { return 0; }
    wait_for_core_docker_health_before_smoke_tests() { :; }

    run_smoke_tests

    [[ "$SMOKE_TEST_STATUS" == "tamamlandi" ]]
    [[ "$(stat -c %a "$SIDAR_KEYS_FILE")" == "600" ]]
    [[ "$(stat -c %a "$SIDAR_SESSION_FILE")" == "600" ]]
  '
  [ "$status" -eq 0 ]
}

@test "sidar_configure_autonomous_cron is opt-in and suggests the flag by default" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    mkdir -p "$tmpdir/scripts"
    touch "$tmpdir/autonomous_loop.sh" "$tmpdir/scripts/auto_heal.py"

    ENABLE_AUTONOMOUS_CRON=false
    sidar_configure_autonomous_cron

    [[ "$AUTONOMOUS_CRON_STATUS" == "atlandi_bayrak" ]]
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"--enable-autonomous-cron"* ]]
}

@test "sidar_configure_autonomous_cron installs a crontab fallback when enabled" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin" "$tmpdir/scripts"
    cat > "$tmpdir/bin/systemctl" <<EOF
#!/usr/bin/env bash
exit 1
EOF
    cat > "$tmpdir/bin/crontab" <<EOF
#!/usr/bin/env bash
if [[ "\${1:-}" == "-l" ]]; then
  [[ -f "$tmpdir/current.cron" ]] && cat "$tmpdir/current.cron"
  exit 0
fi
cat > "$tmpdir/installed.cron"
EOF
    chmod +x "$tmpdir/bin/systemctl" "$tmpdir/bin/crontab"
    export PATH="$tmpdir/bin:$PATH"
    HOME="$tmpdir/home"
    SCRIPT_DIR="$tmpdir"
    touch "$tmpdir/autonomous_loop.sh" "$tmpdir/scripts/auto_heal.py"
    chmod +x "$tmpdir/autonomous_loop.sh"

    ENABLE_AUTONOMOUS_CRON=true
    sidar_configure_autonomous_cron

    [[ "$AUTONOMOUS_CRON_STATUS" == "crontab" ]]
    grep -q "Sidar autonomous loop" "$tmpdir/installed.cron"
    grep -q "autonomous_loop.sh" "$tmpdir/installed.cron"
    grep -q "flock -n" "$tmpdir/installed.cron"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"crontab satırı olarak kuruldu"* ]]
}

@test "run_install_integration_api_tests is opt-in and runs full integration gate with service env" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    touch "$tmpdir/run_tests.sh"
    cat > "$tmpdir/.env" <<EOF
DATABASE_URL=postgresql+asyncpg://sidar:secret@127.0.0.1:5432/sidar
POSTGRES_PASSWORD=secret
SIDAR_REDIS_URL=redis://127.0.0.1:6379/0
EOF
    cat > "$tmpdir/bin/bash" <<EOF
#!/bin/bash
printf "%s\n" "\$*" > "$tmpdir/bash.args"
printf "AUTO_OPEN_ARTIFACTS=%s\nDATABASE_URL=%s\nPOSTGRES_PASSWORD=%s\nREDIS_URL=%s\n" "\${AUTO_OPEN_ARTIFACTS:-}" "\${DATABASE_URL:-}" "\${POSTGRES_PASSWORD:-}" "\${REDIS_URL:-}" > "$tmpdir/bash.env"
exit 0
EOF
    chmod +x "$tmpdir/bin/bash"
    export PATH="$tmpdir/bin:$PATH"
    SCRIPT_DIR="$tmpdir"
    wait_for_redis_before_smoke_tests() { return 0; }
    wait_for_core_docker_health_before_smoke_tests() { :; }

    RUN_INSTALL_INTEGRATION_TESTS=false
    run_install_integration_api_tests
    [[ "$INTEGRATION_TEST_STATUS" == "atlandi_bayrak" ]]
    [[ ! -e "$tmpdir/bash.args" ]]

    RUN_INSTALL_INTEGRATION_TESTS=true
    run_install_integration_api_tests
    [[ "$INTEGRATION_TEST_STATUS" == "tamamlandi" ]]
    grep -q "run_tests.sh" "$tmpdir/bash.args"
    grep -q -- "--stage" "$tmpdir/bash.args"
    grep -q "integration" "$tmpdir/bash.args"
    grep -q "AUTO_OPEN_ARTIFACTS=0" "$tmpdir/bash.env"
    grep -q "DATABASE_URL=postgresql+asyncpg://sidar:secret@127.0.0.1:5432/sidar" "$tmpdir/bash.env"
    grep -q "POSTGRES_PASSWORD=secret" "$tmpdir/bash.env"
    grep -q "REDIS_URL=redis://127.0.0.1:6379/0" "$tmpdir/bash.env"
  '
  [ "$status" -eq 0 ]
}

@test "run_install_frontend_quality_validation uses run_tests frontend stage with e2e enabled" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    touch "$tmpdir/run_tests.sh"
    cat > "$tmpdir/bin/bash" <<EOF
#!/bin/bash
printf "%s\n" "\$*" > "$tmpdir/bash.args"
printf "RUN_FRONTEND_E2E=%s\nAUTO_OPEN_ARTIFACTS=%s\n" "\${RUN_FRONTEND_E2E:-}" "\${AUTO_OPEN_ARTIFACTS:-}" > "$tmpdir/bash.env"
exit 0
EOF
    chmod +x "$tmpdir/bin/bash"
    export PATH="$tmpdir/bin:$PATH"
    SCRIPT_DIR="$tmpdir"

    RUN_INSTALL_INTEGRATION_TESTS=false
    run_install_frontend_quality_validation
    [[ "$FRONTEND_QUALITY_STATUS" == "atlandi_bayrak" ]]
    [[ ! -e "$tmpdir/bash.args" ]]

    RUN_INSTALL_INTEGRATION_TESTS=true
    run_install_frontend_quality_validation
    [[ "$FRONTEND_QUALITY_STATUS" == "tamamlandi" ]]
    grep -q "run_tests.sh" "$tmpdir/bash.args"
    grep -q -- "--stage" "$tmpdir/bash.args"
    grep -q "frontend" "$tmpdir/bash.args"
    grep -q "RUN_FRONTEND_E2E=1" "$tmpdir/bash.env"
    grep -q "AUTO_OPEN_ARTIFACTS=0" "$tmpdir/bash.env"
  '
  [ "$status" -eq 0 ]
}

@test "01_context phase runs environment detection before WSL GPU preflight" {
  run_installer_function '
    events=()
    banner() { events+=(banner); }
    report_repo_lookup_context() { events+=(repo_context); }
    detect_environment() { events+=(detect_environment); WSL2=false; }
    sidar_source_install_utils() { events+=("source:$*"); }
    run_wsl2_gpu_preflight() { events+=(wsl_preflight); }
    verify_offline_bundle_manifest() { events+=(offline_manifest); }
    OFFLINE_MODE=false

    sidar_phase_initialize_context
    [[ "${events[*]}" == "banner repo_context detect_environment source:wsl_gpu_preflight.sh source:wsl_integration_autofix.sh wsl_preflight" ]]
  '
  [ "$status" -eq 0 ]
}

@test "01_context phase fails offline quality gate when bundle directory is missing" {
  run_installer_function '
    banner() { :; }
    report_repo_lookup_context() { :; }
    detect_environment() { WSL2=false; }
    sidar_source_install_utils() { :; }
    run_wsl2_gpu_preflight() { :; }
    resolve_offline_packages_dir() { return 1; }
    OFFLINE_MODE=true

    sidar_phase_initialize_context
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Çevrimdışı mod etkin ancak offline_packages dizini bulunamadı."* ]]
}

@test "03_runtime phase performs hardware/runtime gates but never provisions uv workspace" {
  run_installer_function '
    events=()
    sidar_source_install_utils() { events+=("source:$*"); }
    ensure_prerequisites() { events+=(ensure_prerequisites); }
    select_runtime_mode() { events+=(select_runtime_mode); APP_RUNTIME_MODE_SELECTED=local; }
    select_dependency_profile() { events+=(select_dependency_profile); DEPENDENCY_PROFILE=dev-light; }
    detect_gpu() { events+=(detect_gpu); }
    setup_nvidia_docker() { events+=(setup_nvidia_docker); }
    install_uv_cli() { events+=(unexpected_uv); return 99; }
    create_uv_venv() { events+=(unexpected_venv); return 99; }
    install_python_deps() { events+=(unexpected_deps); return 99; }

    sidar_phase_runtime_prerequisites
    [[ "${events[*]}" == "source:gpu_utils.sh python_env.sh ensure_prerequisites select_runtime_mode select_dependency_profile detect_gpu setup_nvidia_docker" ]]
  '
  [ "$status" -eq 0 ]
}

@test "04_workspace local mode enforces uv venv and uv sync quality gate ordering" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=local
    sidar_source_install_utils() { events+=("source:$*"); }
    install_uv_cli() { events+=(install_uv_cli); }
    create_uv_venv() { events+=(create_uv_venv); }
    install_python_deps() { events+=(install_python_deps); }
    install_pre_commit_hooks() { events+=(install_pre_commit_hooks); }
    install_pyright_lsp_tool() { events+=(install_pyright_lsp_tool); }
    verify_torch_cuda() { events+=(verify_torch_cuda); }
    create_directories() { events+=(create_directories); }
    setup_vscode_workspace() { events+=(setup_vscode_workspace); }
    setup_env_file() { events+=(setup_env_file); }

    sidar_phase_workspace_config
    [[ "${events[*]}" == "source:python_env.sh database_url.sh db_credentials.sh env_utils.sh install_uv_cli create_uv_venv install_python_deps install_pre_commit_hooks install_pyright_lsp_tool verify_torch_cuda create_directories setup_vscode_workspace setup_env_file" ]]
  '
  [ "$status" -eq 0 ]
}

@test "04_workspace docker mode skips local uv provisioning but still prepares workspace files" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=docker
    sidar_source_install_utils() { events+=("source:$*"); }
    install_uv_cli() { events+=(unexpected_uv); return 99; }
    create_uv_venv() { events+=(unexpected_venv); return 99; }
    install_python_deps() { events+=(unexpected_deps); return 99; }
    install_pyright_lsp_tool() { events+=(unexpected_pyright); return 99; }
    verify_torch_cuda() { events+=(unexpected_torch); return 99; }
    create_directories() { events+=(create_directories); }
    setup_vscode_workspace() { events+=(setup_vscode_workspace); }
    setup_env_file() { events+=(setup_env_file); }

    sidar_phase_workspace_config
    [[ "${events[*]}" == "source:python_env.sh database_url.sh db_credentials.sh env_utils.sh create_directories setup_vscode_workspace setup_env_file" ]]
  '
  [ "$status" -eq 0 ]
}

@test "select_dependency_profile defaults noninteractive installer to dev-full" {
  run_installer_function '
    DEPENDENCY_PROFILE=ask
    NO_INTERACTION=true
    AUTO_INSTALL=false
    RUN_CI_FULL_VALIDATION=false

    select_dependency_profile

    [[ "$DEPENDENCY_PROFILE" == "dev-full" ]]
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"varsayılan tam geliştirici bağımlılık profili seçildi (developer-full)"* ]]
}

@test "select_dependency_profile promotes production readiness validation to dev-full" {
  run_installer_function '
    DEPENDENCY_PROFILE=ask
    NO_INTERACTION=true
    AUTO_INSTALL=false
    RUN_CI_FULL_VALIDATION=true

    select_dependency_profile

    [[ "$DEPENDENCY_PROFILE" == "dev-full" ]]
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"developer-full"* ]]
}

@test "install_python_deps custom profile syncs only selected extras" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf -- \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    UPGRADE_LOCK=false
    DEPENDENCY_PROFILE=custom
    SIDAR_DEPENDENCY_EXTRAS="dev openai postgres"
    touch "$tmpdir/uv.lock"
    ensure_env_file_secrets_after_uv_sync() { :; }
    validate_runtime_env_loading() { :; }
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/uv.log"
exit 0
EOF
    chmod +x "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"

    install_python_deps

    grep -q "^sync --frozen --extra dev --extra openai --extra postgres$" "$tmpdir/uv.log"
  '
  [ "$status" -eq 0 ]
}

@test "install_python_deps skips PortAudio apt install when portaudio19-dev is already installed" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    UPGRADE_LOCK=false
    DEPENDENCY_PROFILE=dev-full
    touch "$tmpdir/uv.lock"
    ensure_env_file_secrets_after_uv_sync() { :; }
    validate_runtime_env_loading() { :; }
    cat > "$tmpdir/bin/dpkg-query" <<EOF
#!/usr/bin/env bash
printf "Status: install ok installed\n"
EOF
    cat > "$tmpdir/bin/apt-get" <<EOF
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/apt.log"
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/uv.log"
case "\$1" in
  sync) exit 0 ;;
  run) exit 0 ;;
esac
exit 0
EOF
    chmod +x "$tmpdir/bin/dpkg-query" "$tmpdir/bin/apt-get" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"

    install_python_deps

    [[ ! -e "$tmpdir/apt.log" ]]
    grep -q "^sync --frozen --all-extras$" "$tmpdir/uv.log"
  '
  [ "$status" -eq 0 ]
}

@test "install_sidar keeps python_env helpers single-sourced from the module" {
  local root
  root="$(repo_root)"
  run bash -c '
    set -Eeuo pipefail
    repo_root="$1"
    cd "$repo_root"
    for helper in \
      install_uv_cli \
      create_uv_venv \
      install_python_deps \
      install_pyright_lsp_tool \
      select_pytorch_cuda_wheel_tag
    do
      ! grep -Eq "^${helper}\\(\\)[[:space:]]*\\{" install_sidar.sh
      grep -Eq "^${helper}\\(\\)[[:space:]]*\\{" scripts/install_modules/utils/python_env.sh
    done
  ' _ "$root"
  [ "$status" -eq 0 ]
}

@test "install_python_deps installs PortAudio with apt-get directly for root installs" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    UPGRADE_LOCK=false
    DEPENDENCY_PROFILE=dev-full
    SIDAR_INSTALL_EFFECTIVE_UID=0
    touch "$tmpdir/uv.lock"
    ensure_env_file_secrets_after_uv_sync() { :; }
    validate_runtime_env_loading() { :; }
    cat > "$tmpdir/bin/dpkg-query" <<EOF
#!/usr/bin/env bash
exit 1
EOF
    cat > "$tmpdir/bin/apt-get" <<EOF
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/apt.log"
exit 0
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/uv.log"
exit 0
EOF
    chmod +x "$tmpdir/bin/dpkg-query" "$tmpdir/bin/apt-get" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"

    install_python_deps

    grep -q "^update$" "$tmpdir/apt.log"
    grep -q "^install -y --no-install-recommends portaudio19-dev$" "$tmpdir/apt.log"
    grep -q "^sync --frozen --all-extras$" "$tmpdir/uv.log"
  '
  [ "$status" -eq 0 ]
}

@test "install_python_deps installs PortAudio through passwordless sudo for non-root installs" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    UPGRADE_LOCK=false
    DEPENDENCY_PROFILE=dev-full
    SIDAR_INSTALL_EFFECTIVE_UID=1000
    touch "$tmpdir/uv.lock"
    ensure_env_file_secrets_after_uv_sync() { :; }
    validate_runtime_env_loading() { :; }
    cat > "$tmpdir/bin/dpkg-query" <<EOF
#!/usr/bin/env bash
exit 1
EOF
    cat > "$tmpdir/bin/apt-get" <<EOF
#!/usr/bin/env bash
printf "unexpected apt-get without sudo\n" >> "$tmpdir/apt.log"
exit 99
EOF
    cat > "$tmpdir/bin/sudo" <<EOF
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/sudo.log"
if [[ "\$*" == "-n true" ]]; then
  exit 0
fi
exit 0
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "%s\n" "\$*" >> "$tmpdir/uv.log"
exit 0
EOF
    chmod +x "$tmpdir/bin/dpkg-query" "$tmpdir/bin/apt-get" "$tmpdir/bin/sudo" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"

    install_python_deps

    [[ ! -s "$tmpdir/apt.log" ]]
    grep -q "^-n true$" "$tmpdir/sudo.log"
    grep -q "^-n apt-get update$" "$tmpdir/sudo.log"
    grep -q "^-n env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends portaudio19-dev$" "$tmpdir/sudo.log"
    grep -q "^sync --frozen --all-extras$" "$tmpdir/uv.log"
  '
  [ "$status" -eq 0 ]
}

@test "install_python_deps fails with actionable PortAudio guidance when apt install cannot be authorized" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    UPGRADE_LOCK=false
    DEPENDENCY_PROFILE=dev-full
    SIDAR_INSTALL_EFFECTIVE_UID=1000
    touch "$tmpdir/uv.lock"
    ensure_env_file_secrets_after_uv_sync() { :; }
    validate_runtime_env_loading() { :; }
    cat > "$tmpdir/bin/dpkg-query" <<EOF
#!/usr/bin/env bash
exit 1
EOF
    cat > "$tmpdir/bin/apt-get" <<EOF
#!/usr/bin/env bash
exit 99
EOF
    cat > "$tmpdir/bin/sudo" <<EOF
#!/usr/bin/env bash
if [[ "\$*" == "-n true" ]]; then
  exit 1
fi
exit 1
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "uv should not run\n" >> "$tmpdir/uv.log"
exit 99
EOF
    chmod +x "$tmpdir/bin/dpkg-query" "$tmpdir/bin/apt-get" "$tmpdir/bin/sudo" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"

    install_python_deps
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"sudo apt-get install -y portaudio19-dev"* ]]
}

@test "is_alembic_at_head compares current and heads with the configured DATABASE_URL" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    unset DATABASE_URL
    touch "$tmpdir/alembic.ini"
    cat > "$tmpdir/.env" <<EOF
DATABASE_URL=postgresql+asyncpg://sidar:secret@localhost:5432/sidar
EOF
    cat > "$tmpdir/bin/python3" <<EOF
#!/usr/bin/env bash
printf "%s|%s\n" "\${DATABASE_URL:-}" "\$*" >> "$tmpdir/python.log"
case "\$*" in
  "-m alembic current --check-heads") exit 2 ;;
  "-m alembic current")
    echo "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl." >&2
    echo "  0006_access_control_schema (head)"
    ;;
  "-m alembic heads") echo "    0006_access_control_schema (head)" ;;
esac
EOF
    chmod +x "$tmpdir/bin/python3"
    export PATH="$tmpdir/bin:$PATH"

    is_alembic_at_head

    [[ "$(wc -l < "$tmpdir/python.log")" -eq 3 ]]
    grep -q "^postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic current --check-heads$" "$tmpdir/python.log"
    grep -q "^postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic current$" "$tmpdir/python.log"
    grep -q "^postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic heads$" "$tmpdir/python.log"
  '
  [ "$status" -eq 0 ]
}

@test "is_alembic_at_head derives DATABASE_URL from POSTGRES parts when explicit URL is absent" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    unset DATABASE_URL
    touch "$tmpdir/alembic.ini"
    cat > "$tmpdir/.env" <<EOF
POSTGRES_USER=sidar
POSTGRES_PASSWORD=secret
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=sidar
EOF
    cat > "$tmpdir/bin/python3" <<EOF
#!/usr/bin/env bash
printf "%s|%s\n" "\${DATABASE_URL:-}" "\$*" >> "$tmpdir/python.log"
case "\$*" in
  "-m alembic current --check-heads") exit 2 ;;
  "-m alembic current") echo "  0006_access_control_schema (head)" ;;
  "-m alembic heads") echo "    0006_access_control_schema (head)" ;;
esac
EOF
    chmod +x "$tmpdir/bin/python3"
    export PATH="$tmpdir/bin:$PATH"

    is_alembic_at_head

    grep -q "^postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic current$" "$tmpdir/python.log"
    grep -q "^postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic heads$" "$tmpdir/python.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Alembic DB URL kaynağı:"* ]]
}

@test "is_alembic_at_head prefers the project venv Python over system python3" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/.venv/bin" "$tmpdir/bin"
    SCRIPT_DIR="$tmpdir"
    unset DATABASE_URL
    touch "$tmpdir/alembic.ini"
    cat > "$tmpdir/.env" <<EOF
DATABASE_URL=postgresql+asyncpg://sidar:secret@localhost:5432/sidar
EOF
    cat > "$tmpdir/.venv/bin/python" <<EOF
#!/usr/bin/env bash
printf "venv|%s|%s\n" "\${DATABASE_URL:-}" "\$*" >> "$tmpdir/python.log"
case "\$*" in
  "-m alembic current --check-heads") exit 2 ;;
  "-m alembic current") echo "  0006_access_control_schema (head)" ;;
  "-m alembic heads") echo "    0006_access_control_schema (head)" ;;
esac
EOF
    cat > "$tmpdir/bin/python3" <<EOF
#!/usr/bin/env bash
printf "system|%s|%s\n" "\${DATABASE_URL:-}" "\$*" >> "$tmpdir/python.log"
exit 42
EOF
    chmod +x "$tmpdir/.venv/bin/python" "$tmpdir/bin/python3"
    export PATH="$tmpdir/bin:$PATH"

    is_alembic_at_head

    [[ "$(wc -l < "$tmpdir/python.log")" -eq 3 ]]
    grep -q "^venv|postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic current --check-heads$" "$tmpdir/python.log"
    grep -q "^venv|postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic current$" "$tmpdir/python.log"
    grep -q "^venv|postgresql+asyncpg://sidar:secret@localhost:5432/sidar|-m alembic heads$" "$tmpdir/python.log"
    ! grep -q "^system|" "$tmpdir/python.log"
  '
  [ "$status" -eq 0 ]
}

@test "post-install SIDAR_ENV change skips redundant Alembic upgrade when current is head" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/.env" <<EOF
SIDAR_ENV=production
DATABASE_URL=postgresql+asyncpg://sidar:secret@localhost:5432/sidar
EOF
    AUTO_ENV_TYPE=development
    NO_INTERACTION=true
    migration_calls=0
    is_alembic_at_head() { return 0; }
    run_migrations() { migration_calls=$((migration_calls + 1)); }

    prompt_post_install_sidar_env_mode

    [[ "$migration_calls" -eq 0 ]]
    grep -q "^SIDAR_ENV=development$" "$tmpdir/.env"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"SIDAR_ENV değişti (production -> development) ancak Alembic current=head; tekrar migrasyon atlandı."* ]]
}

@test "post-install SIDAR_ENV change reruns Alembic upgrade when current is behind head" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/.env" <<EOF
SIDAR_ENV=production
DATABASE_URL=postgresql+asyncpg://sidar:secret@localhost:5432/sidar
EOF
    AUTO_ENV_TYPE=development
    NO_INTERACTION=true
    migration_calls=0
    is_alembic_at_head() { return 1; }
    run_migrations() { migration_calls=$((migration_calls + 1)); }

    prompt_post_install_sidar_env_mode

    [[ "$migration_calls" -eq 1 ]]
    grep -q "^SIDAR_ENV=development$" "$tmpdir/.env"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"SIDAR_ENV değişti (production -> development) ve Alembic current/head uyuşmuyor; veritabanı migrasyonu tekrar doğrulanıyor..."* ]]
}

@test "production environment selection requires production-readiness before persisting SIDAR_ENV" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/.env" <<EOF
SIDAR_ENV=development
EOF
    AUTO_ENV_TYPE=production
    NO_INTERACTION=true
    summary_production_ready=false
    validation_calls=0
    sidar_ensure_autonomy_scripts_executable() { :; }
    sidar_configure_autonomous_cron() { :; }
    print_summary() { :; }
    relocate_log_file_if_needed() { :; }
    cleanup_bootstrap_script_copy() { :; }
    launch_ide() { :; }
    sidar_install_summary_field_or_empty() {
      [[ "$1" == "production_ready" ]] && printf "%s" "$summary_production_ready"
    }
    is_alembic_at_head() { return 0; }
    run_migrations() { return 0; }
    run_install_ci_full_validation() {
      validation_calls=$((validation_calls + 1))
      [[ "$SIDAR_SELECTED_ENV_TYPE" == "production" ]]
      sidar_install_production_gate_required
      summary_production_ready=true
    }

    sidar_phase_finish

    [[ "$validation_calls" -eq 1 ]]
    grep -q "^SIDAR_ENV=production$" "$tmpdir/.env"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Production seçimi kaydedildi; production-readiness gate geçmeden SIDAR_ENV=production kalıcılaştırılmayacak."* ]]
  [[ "$output" == *"production-readiness gate ve migration doğrulaması tamamlandı"* ]]
}

@test "production gate failure does not leave .env in production mode" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/.env" <<EOF
SIDAR_ENV=development
EOF
    AUTO_ENV_TYPE=production
    NO_INTERACTION=true
    sidar_ensure_autonomy_scripts_executable() { :; }
    sidar_configure_autonomous_cron() { :; }
    print_summary() { :; }
    relocate_log_file_if_needed() { :; }
    cleanup_bootstrap_script_copy() { :; }
    launch_ide() { :; }
    sidar_install_summary_field_or_empty() {
      [[ "$1" == "production_ready" ]] && printf "false"
    }
    run_install_ci_full_validation() { return 23; }

    sidar_phase_finish
  '
  [ "$status" -eq 23 ]
  [[ "$output" == *"Production seçimi kaydedildi; production-readiness gate geçmeden SIDAR_ENV=production kalıcılaştırılmayacak."* ]]
}

@test "production gate failure keeps persisted SIDAR_ENV out of production" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/.env" <<EOF
SIDAR_ENV=development
EOF
    AUTO_ENV_TYPE=production
    NO_INTERACTION=true
    sidar_install_summary_field_or_empty() {
      [[ "$1" == "production_ready" ]] && printf "false"
    }

    prompt_post_install_sidar_env_mode

    grep -q "^SIDAR_ENV=development$" "$tmpdir/.env"
    ! grep -q "^SIDAR_ENV=production$" "$tmpdir/.env"
    rm -rf "$tmpdir"
  '
  [ "$status" -eq 0 ]
}

@test "development environment selection preserves current validation behavior" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    cat > "$tmpdir/.env" <<EOF
SIDAR_ENV=development
EOF
    AUTO_ENV_TYPE=development
    NO_INTERACTION=true
    validation_calls=0
    sidar_ensure_autonomy_scripts_executable() { :; }
    sidar_configure_autonomous_cron() { :; }
    print_summary() { :; }
    relocate_log_file_if_needed() { :; }
    cleanup_bootstrap_script_copy() { :; }
    launch_ide() { :; }
    is_alembic_at_head() { return 0; }
    run_migrations() { return 0; }
    run_install_ci_full_validation() {
      validation_calls=$((validation_calls + 1))
      ! sidar_install_production_gate_required
    }

    sidar_phase_finish

    [[ "$validation_calls" -eq 1 ]]
    grep -q "^SIDAR_ENV=development$" "$tmpdir/.env"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Ortam değişkenleri 'Development'"* ]]
}

@test "06 services phases gate local migrations models smoke and audit in order" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=local
    sidar_source_install_utils() { events+=("source:$*"); }
    phase06_docker_daemon_gate_or_fail() { events+=(phase06_docker_daemon_gate_or_fail); }
    run_pre_service_installer_smoke_gate() { events+=(run_pre_service_installer_smoke_gate); }
    prepare_docker_for_migrations() { events+=(prepare_docker_for_migrations); }
    ensure_postgres_databases_exist() { events+=(ensure_postgres_databases_exist); }
    run_migrations() { events+=(run_migrations); }
    download_ollama_models() { events+=(download_ollama_models); }
    launch_docker_services() { events+=(launch_docker_services); }
    run_smoke_tests() { events+=(run_smoke_tests); }
    run_install_integration_api_tests() { events+=(run_install_integration_api_tests); }
    run_install_frontend_quality_validation() { events+=(run_install_frontend_quality_validation); }
    run_test_artifact_audit() { events+=(run_test_artifact_audit); }

    sidar_phase_local_migrations_and_models
    sidar_phase_services_and_validation
    [[ "${events[*]}" == "source:ollama_models.sh prepare_docker_for_migrations ensure_postgres_databases_exist run_migrations download_ollama_models phase06_docker_daemon_gate_or_fail run_pre_service_installer_smoke_gate launch_docker_services run_smoke_tests run_install_integration_api_tests run_install_frontend_quality_validation run_test_artifact_audit" ]]
  '
  [ "$status" -eq 0 ]
}

@test "06 services stops before Docker launch when pre-service installer smoke fails" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=local
    phase06_docker_daemon_gate_or_fail() { events+=(phase06_docker_daemon_gate_or_fail); }
    run_pre_service_installer_smoke_gate() { events+=(run_pre_service_installer_smoke_gate); return 42; }
    launch_docker_services() { events+=(unexpected_launch); return 99; }
    run_smoke_tests() { events+=(unexpected_smoke); return 99; }

    if sidar_phase_services_and_validation; then
      exit 1
    fi
    [[ "${events[*]}" == "phase06_docker_daemon_gate_or_fail run_pre_service_installer_smoke_gate" ]]
  '
  [ "$status" -eq 0 ]
}

@test "06 services docker mode marks local-only gates as skipped" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=docker
    sidar_source_install_utils() { events+=("source:$*"); }
    phase06_docker_daemon_gate_or_fail() { events+=(phase06_docker_daemon_gate_or_fail); }
    prepare_docker_for_migrations() { events+=(unexpected_prepare); return 99; }
    run_migrations() { events+=(unexpected_migration); return 99; }
    download_ollama_models() { events+=(unexpected_models); return 99; }
    launch_docker_services() { events+=(launch_docker_services); }
    run_smoke_tests() { events+=(unexpected_smoke); return 99; }
    run_install_integration_api_tests() { events+=(unexpected_integration); return 99; }
    run_install_frontend_quality_validation() { events+=(unexpected_frontend); return 99; }
    run_test_artifact_audit() { events+=(unexpected_audit); return 99; }

    sidar_phase_local_migrations_and_models
    sidar_phase_services_and_validation
    [[ "${events[*]}" == "source:ollama_models.sh phase06_docker_daemon_gate_or_fail launch_docker_services" ]]
    [[ "$MIGRATION_STATUS" == "tam_docker_modu_nedeniyle_atlandi" ]]
    [[ "$SMOKE_TEST_STATUS" == "tam_docker_modu_nedeniyle_atlandi" ]]
    [[ "$INTEGRATION_TEST_STATUS" == "tam_docker_modu_nedeniyle_atlandi" ]]
    [[ "$AUDIT_STATUS" == "tam_docker_modu_nedeniyle_atlandi" ]]
  '
  [ "$status" -eq 0 ]
}

@test "06 services docker mode honors disabled RAG warmup without local side effects" {
  run_installer_function '
    events=()
    unset SIDAR_INSTALL_TEST_MODE
    APP_RUNTIME_MODE_SELECTED=docker
    AUTO_SEED_RAG_DOCKER_WARMUP=false
    SCRIPT_DIR="/tmp/unused-sidar-script-dir"
    sidar_source_install_utils() { events+=("source:$*"); }
    prepare_docker_for_migrations() { events+=(unexpected_prepare); return 99; }
    ensure_postgres_databases_exist() { events+=(unexpected_database_bootstrap); return 99; }
    run_migrations() { events+=(unexpected_migration); return 99; }
    download_ollama_models() { events+=(unexpected_models); return 99; }
    command() { events+=("unexpected_command:$*"); return 99; }
    info() { events+=("info:$*"); }

    sidar_phase_local_migrations_and_models

    [[ "${events[*]}" == "source:ollama_models.sh info:Tam Docker modu: lokal migrasyon/model indirme adımları atlanıyor. info:AUTO_SEED_RAG_DOCKER_WARMUP=false; Docker RAG warmup seed atlandı." ]]
    [[ "$MIGRATION_STATUS" == "tam_docker_modu_nedeniyle_atlandi" ]]
  '
  [ "$status" -eq 0 ]
}

@test "WSL GPU preflight supports explicit off and CPU skip modes" {
  run_installer_function '
    sidar_source_install_utils wsl_gpu_preflight.sh
    WSL2=true
    FORCE_CPU=false
    SIDAR_WSL_GPU_PREFLIGHT=off
    run_wsl2_gpu_preflight
    FORCE_CPU=true
    SIDAR_WSL_GPU_PREFLIGHT=strict
    run_wsl2_gpu_preflight
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"SIDAR_WSL_GPU_PREFLIGHT=off"* ]]
  [[ "$output" == *"--cpu etkin"* ]]
}

@test "auto-heal resume skips completed phases and reruns failed phase" {
  run_installer_function '
    SIDAR_INSTALL_RESUME_FROM_PHASE=04_workspace
    called=0
    phase_fn() { called=$((called + 1)); }

    sidar_run_install_phase 03_runtime phase_fn
    [[ "$called" -eq 0 ]]
    sidar_run_install_phase 04_workspace phase_fn
    [[ "$called" -eq 1 ]]
  '
  [ "$status" -eq 0 ]
}

@test "auto-heal strategy routes uv sync workspace failures to remediation" {
  run_installer_function '
    sidar_remediate_uv_sync_failure() { printf "%s\n" "uv-remediation-called"; return 0; }
    sidar_phase_remediation_strategy 04_workspace "uv sync --frozen --all-extras" ""
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"uv-remediation-called"* ]]
}

@test "auto-heal can be disabled for deterministic fail-fast installer runs" {
  run_installer_function '
    SIDAR_INSTALL_AUTO_HEAL=0
    SIDAR_CURRENT_INSTALL_PHASE=04_workspace
    if sidar_handle_install_failure 1 10 "uv sync" "uv sync"; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
}

@test "auto-heal suppression env disables remediation for installer smoke gates" {
  run_installer_function '
    SIDAR_INSTALL_SUPPRESS_AUTO_HEAL=1
    SIDAR_CURRENT_INSTALL_PHASE=04_workspace
    sidar_resume_after_remediation() {
      echo "unexpected-resume"
      return 1
    }
    if sidar_install_auto_heal_enabled; then
      exit 1
    fi
    if sidar_handle_install_failure 1 10 "uv sync" "uv sync"; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" != *"unexpected-resume"* ]]
}

@test "auto-heal fails fast for learned non-retryable installer failures" {
  run_installer_function '
    SIDAR_CURRENT_INSTALL_PHASE=06_services
    SIDAR_INSTALL_REMEDIATION_ATTEMPT=0
    sidar_resume_after_remediation() {
      echo "unexpected-resume"
      return 1
    }
    if sidar_handle_install_failure 1 20 "pytest smoke" "EnvironmentFileNotFound: environment.yml"; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"öğrenilmiş kalıcı hata imzası"* ]]
  [[ "$output" != *"unexpected-resume"* ]]
}

@test "auto-heal cuts off repeated failure signatures before transient retry budget" {
  run_installer_function '
    SIDAR_CURRENT_INSTALL_PHASE=06_services
    SIDAR_INSTALL_REMEDIATION_ATTEMPT=1
    SIDAR_INSTALL_LAST_FAILURE_PHASE=06_services
    SIDAR_INSTALL_LAST_FAILURE_SIGNATURE="$(sidar_failure_signature 06_services "docker compose up" "service still starting" 1)"
    sidar_resume_after_remediation() {
      echo "unexpected-resume"
      return 1
    }
    if sidar_handle_install_failure 1 20 "docker compose up" "service still starting"; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"aynı failure imzası tekrarlandı"* ]]
  [[ "$output" != *"unexpected-resume"* ]]
}

@test "postgres volume discovery catches Sidar volumes after project directory mismatch" {
  run_installer_function '
    docker() {
      if [[ "$1" == "volume" && "$2" == "ls" ]]; then
        printf "%s\n" "oldproj_postgres_data" "sidar_postgres_data" "other_postgres_data"
        return 0
      fi
      if [[ "$1" == "volume" && "$2" == "inspect" ]]; then
        printf "%s\n" "<no value>|<no value>"
        return 0
      fi
      return 0
    }

    mapfile -t discovered < <(sidar_discover_postgres_volumes "freshclone" postgres_data)
    [[ "${#discovered[@]}" -eq 1 ]]
    [[ "${discovered[0]}" == "sidar_postgres_data" ]]
  '
  [ "$status" -eq 0 ]
}

@test "postgres password hardening reset runs compose down fallback when no volume is directly detected" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    echo "SIDAR_ENV=development" > "$tmpdir/.env"
    SCRIPT_DIR="$tmpdir"

    down_called=false
    fake_compose() {
      case "$1" in
        config)
          if [[ "${2:-}" == "--volumes" ]]; then
            printf "%s\n" "postgres_data"
          fi
          ;;
        down)
          down_called=true
          [[ "$*" == *"--volumes"* ]]
          [[ "$*" == *"--remove-orphans"* ]]
          ;;
        ps)
          return 0
          ;;
      esac
      return 0
    }
    docker() {
      if [[ "$1" == "volume" && "$2" == "ls" ]]; then
        return 0
      fi
      if [[ "$1" == "volume" && "$2" == "inspect" ]]; then
        return 1
      fi
      return 0
    }

    DB_PASSWORD_HARDENED=true
    POSTGRES_VOLUME_RESET_DONE=false
    AUTO_RESET_POSTGRES_VOLUME_ON_PASSWORD_CHANGE=1
    AUTO_RESET_POSTGRES_VOLUMES=true
    NO_INTERACTION=true

    maybe_reset_postgres_volume_after_password_hardening fake_compose -- postgres redis
    [[ "$down_called" == true ]]
    [[ "$POSTGRES_VOLUME_RESET_DONE" == true ]]
  '
  [ "$status" -eq 0 ]
}

@test "ensure_postgres_databases_exist reads password and creates only missing DBs" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    psql_calls="$tmpdir/psql_calls.log"
    psql_create="$tmpdir/psql_create.log"
    cat > "$tmpdir/psql" <<"EOF"
#!/usr/bin/env bash
printf "%s\n" "$*" >> "__CALLS__"
[[ "${PGPASSWORD:-}" == "super-secret" ]] || exit 9
[[ "$*" == *"-w -h 127.0.0.1 -p 5432 -U sidar -d postgres"* ]] || exit 8
if [[ "$*" == *"-tAc SELECT 1 FROM pg_database WHERE datname = '\''sidar'\''"* ]]; then
  echo "1"
  exit 0
fi
if [[ "$*" == *"-tAc SELECT 1 FROM pg_database"* ]]; then
  exit 0
fi
if [[ "$*" == *"-v ON_ERROR_STOP=1 -c CREATE DATABASE"* ]]; then
  printf "%s\n" "$*" >> "__CREATE__"
  exit 0
fi
printf "%s\n" "unexpected psql invocation: $*" >&2
exit 7
EOF
    sed -i "s#__CALLS__#$psql_calls#g" "$tmpdir/psql"
    sed -i "s#__CREATE__#$psql_create#g" "$tmpdir/psql"
    chmod +x "$tmpdir/psql"
    PATH="$tmpdir:$PATH"
    hash -r

    ensure_postgres_databases_exist "127.0.0.1" "5432" "sidar" "super-secret" "sidar"

    grep -q -- "-h 127.0.0.1 -p 5432 -U sidar -d postgres" "$psql_calls"
    grep -q -- "CREATE DATABASE \"sidar_development\" OWNER \"sidar\";" "$psql_create"
    grep -q -- "CREATE DATABASE \"sidar_test\" OWNER \"sidar\";" "$psql_create"
    if grep -q -- "CREATE DATABASE \"sidar\" OWNER \"sidar\";" "$psql_create"; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
}

@test "ensure_postgres_databases_exist fails closed when the database existence query fails" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/psql" <<"EOF"
#!/usr/bin/env bash
if [[ "$*" == *"-tAc SELECT 1 FROM pg_database"* ]]; then
  printf "%s\n" "psql: error: connection refused" >&2
  exit 2
fi
if [[ "$*" == *"CREATE DATABASE"* ]]; then
  printf "%s\n" "unexpected CREATE DATABASE call" >&2
fi
exit 0
EOF
    chmod +x "$tmpdir/psql"
    PATH="$tmpdir:$PATH"
    hash -r

    ensure_postgres_databases_exist "127.0.0.1" "5432" "sidar" "super-secret" "sidar"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"PostgreSQL veritabanı varlık sorgusu başarısız: sidar"* ]]
  [[ "$output" != *"unexpected CREATE DATABASE call"* ]]
}

@test "ensure_postgres_databases_exist fails closed on psql password authentication errors" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/psql" <<"EOF"
#!/usr/bin/env bash
printf "%s\n" "psql: error: password authentication failed for user sidar" >&2
exit 2
EOF
    chmod +x "$tmpdir/psql"
    PATH="$tmpdir:$PATH"
    hash -r

    ensure_postgres_databases_exist "127.0.0.1" "5432" "sidar" "wrong-password" "sidar"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"PostgreSQL auth başarısız"* ]]
}

@test "detect_cuda_driver_capability prefers nvidia-smi cuda_version query output" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/nvidia-smi" <<SMI
#!/usr/bin/env bash
if [[ "\$*" == "--query-gpu=cuda_version --format=csv,noheader" ]]; then
  printf "12.9\\n"
  exit 0
fi
printf "unexpected nvidia-smi args: %s\\n" "\$*" >&2
exit 1
SMI
    chmod +x "$tmpdir/nvidia-smi"
    [[ "$(detect_cuda_driver_capability "$tmpdir/nvidia-smi")" == "12.9" ]]
  '
  [ "$status" -eq 0 ]
}

@test "detect_cuda_driver_capability falls back to banner parsing when query field is unavailable" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/nvidia-smi" <<SMI
#!/usr/bin/env bash
if [[ "\$*" == "--query-gpu=cuda_version --format=csv,noheader" ]]; then
  echo "Field \"cuda_version\" is not a valid field to query" >&2
  exit 1
fi
cat <<BANNER
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 610.62                 Driver Version: 610.62     CUDA Version: 13.0 |
+-----------------------------------------------------------------------------+
BANNER
SMI
    chmod +x "$tmpdir/nvidia-smi"
    [[ "$(detect_cuda_driver_capability "$tmpdir/nvidia-smi")" == "13.0" ]]
  '
  [ "$status" -eq 0 ]
}

@test "detect_cuda_driver_capability falls back to libcuda cuDriverGetVersion when nvidia-smi lacks CUDA banner info" {
  if ! command -v cc &>/dev/null; then
    skip "cc derleyicisi mevcut değil"
  fi
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/nvidia-smi" <<SMI
#!/usr/bin/env bash
if [[ "\$*" == "--query-gpu=cuda_version --format=csv,noheader" ]]; then
  echo "Field \"cuda_version\" is not a valid field to query" >&2
  exit 1
fi
echo "NVIDIA-SMI banner without CUDA token (WSL2 N/A case)"
SMI
    chmod +x "$tmpdir/nvidia-smi"

    cat > "$tmpdir/libcuda_stub.c" <<CSRC
int cuInit(unsigned int flags) { return 0; }
int cuDriverGetVersion(int *version) { *version = 12040; return 0; }
CSRC
    cc -shared -fPIC -o "$tmpdir/libcuda.so.1" "$tmpdir/libcuda_stub.c"
    export LD_LIBRARY_PATH="$tmpdir:${LD_LIBRARY_PATH:-}"

    [[ "$(detect_cuda_driver_capability "$tmpdir/nvidia-smi")" == "12.4" ]]
  '
  [ "$status" -eq 0 ]
}

@test "detect_cuda_driver_capability_via_libcuda returns empty when libcuda is unavailable" {
  run_installer_function '
    unset LD_LIBRARY_PATH
    [[ -z "$(detect_cuda_driver_capability_via_libcuda)" ]]
  '
  [ "$status" -eq 0 ]
}

@test "detect_gpu reports CUDA Driver Cap from query fallback on changed nvidia-smi banners" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/nvidia-smi" <<SMI
#!/usr/bin/env bash
case "\$*" in
  "-L") echo "GPU 0: Test GPU (UUID: GPU-test)" ;;
  "--query-gpu=name --format=csv,noheader") echo "Test GPU" ;;
  "--query-gpu=memory.total --format=csv,noheader,nounits") echo "24576" ;;
  "--query-gpu=compute_cap --format=csv,noheader") echo "8.9" ;;
  "--query-gpu=cuda_version --format=csv,noheader") echo "12.9" ;;
  "--query-gpu=driver_version --format=csv,noheader") echo "610.62" ;;
  *) echo "NVIDIA-SMI changed banner without CUDA token" ;;
esac
SMI
    chmod +x "$tmpdir/nvidia-smi"
    cat > "$tmpdir/.env.development.example" <<ENV
SIDAR_ENV=development
RUN_GPU_STRESS=0
ENV
    export PATH="$tmpdir:$PATH"
    SCRIPT_DIR="$tmpdir"
    FORCE_CPU=false
    WSL2=false
    RUN_GPU_STRESS=0
    unset SIDAR_GPU_PREFLIGHT_NAME
    unset SIDAR_GPU_PREFLIGHT_DRIVER_VERSION
    unset SIDAR_GPU_PREFLIGHT_CUDA_DRIVER_CAPABILITY
    unset SIDAR_GPU_PREFLIGHT_COMPUTE_CAPABILITY
    unset SIDAR_GPU_PREFLIGHT_VRAM_MB
    unset SIDAR_WSL_CUDA_PASSTHROUGH_ACTIVE
    unset SIDAR_USE_GPU_PREFLIGHT_FACTS

    detect_gpu
    [[ "$GPU_AVAILABLE" == "true" ]]
    [[ "$CUDA_VERSION" == "12.9" ]]
    [[ "$GPU_COMPUTE_CAPABILITY" == "8.9" ]]
    grep -q "^RUN_GPU_STRESS=1$" "$tmpdir/.env.development"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Driver CUDA API Capability : 12.9"* ]]
}

@test "detect_gpu reports unknown CUDA driver cap and separate WSL runtime CUDA" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf -- \"$tmpdir\"" EXIT
    cat > "$tmpdir/nvidia-smi" <<SMI
#!/usr/bin/env bash
case "\$*" in
  "-L") echo "GPU 0: WSL Test GPU (UUID: GPU-test)" ;;
  "--query-gpu=name --format=csv,noheader") echo "WSL Test GPU" ;;
  "--query-gpu=memory.total --format=csv,noheader,nounits") echo "24576" ;;
  "--query-gpu=compute_cap --format=csv,noheader") echo "8.9" ;;
  "--query-gpu=cuda_version --format=csv,noheader") exit 1 ;;
  "--query-gpu=driver_version --format=csv,noheader") echo "610.62" ;;
  *) echo "NVIDIA-SMI WSL banner without CUDA token" ;;
esac
SMI
    cat > "$tmpdir/uv" <<UV
#!/usr/bin/env bash
if [[ "\${1:-} \${2:-}" == "run python" ]]; then
  echo "13.0"
fi
UV
    chmod +x "$tmpdir/nvidia-smi" "$tmpdir/uv"
    cat > "$tmpdir/.env.development.example" <<ENV
SIDAR_ENV=development
RUN_GPU_STRESS=0
ENV
    export PATH="$tmpdir:$PATH"
    SCRIPT_DIR="$tmpdir"
    FORCE_CPU=false
    WSL2=true
    RUN_GPU_STRESS=0

    unset SIDAR_GPU_PREFLIGHT_NAME
    unset SIDAR_GPU_PREFLIGHT_DRIVER_VERSION
    unset SIDAR_GPU_PREFLIGHT_CUDA_DRIVER_CAPABILITY
    unset SIDAR_GPU_PREFLIGHT_COMPUTE_CAPABILITY
    unset SIDAR_GPU_PREFLIGHT_VRAM_MB
    unset SIDAR_WSL_CUDA_PASSTHROUGH_ACTIVE
    unset SIDAR_USE_GPU_PREFLIGHT_FACTS

    detect_gpu

    [[ "$GPU_AVAILABLE" == "true" ]]
    [[ -z "$CUDA_VERSION" ]]
    [[ "$PYTORCH_RUNTIME_CUDA_VERSION" == "13.0" ]]
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Driver CUDA API Capability : bilinmiyor"* ]]
  [[ "$output" == *"NVIDIA Windows Driver : 610.62"* ]]
  [[ "$output" == *"WSL CUDA Passthrough : bilinmiyor"* ]]
  [[ "$output" == *"PyTorch Runtime CUDA : 13.0"* ]]
}

@test "detect_gpu reuses WSL preflight GPU facts when available" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf -- \"$tmpdir\"" EXIT
    cat > "$tmpdir/nvidia-smi" <<SMI
#!/usr/bin/env bash
case "\$*" in
  "-L") echo "GPU 0: Runtime GPU (UUID: GPU-runtime)" ;;
  "--query-gpu=name --format=csv,noheader") echo "Runtime GPU" ;;
  "--query-gpu=memory.total --format=csv,noheader,nounits") echo "1024" ;;
  "--query-gpu=compute_cap --format=csv,noheader") echo "7.5" ;;
  "--query-gpu=cuda_version --format=csv,noheader") echo "12.1" ;;
  "--query-gpu=driver_version --format=csv,noheader") echo "500.00" ;;
  *) echo "unexpected nvidia-smi args: \$*" >&2; exit 1 ;;
esac
SMI
    chmod +x "$tmpdir/nvidia-smi"
    cat > "$tmpdir/.env.development.example" <<ENV
SIDAR_ENV=development
RUN_GPU_STRESS=0
ENV
    export PATH="$tmpdir:$PATH"
    SCRIPT_DIR="$tmpdir"
    FORCE_CPU=false
    WSL2=true
    RUN_GPU_STRESS=0
    SIDAR_GPU_PREFLIGHT_NAME="Preflight GPU"
    SIDAR_GPU_PREFLIGHT_DRIVER_VERSION="610.62"
    SIDAR_GPU_PREFLIGHT_CUDA_DRIVER_CAPABILITY="13.0"
    SIDAR_GPU_PREFLIGHT_COMPUTE_CAPABILITY="8.6"
    SIDAR_GPU_PREFLIGHT_VRAM_MB="8192"
    SIDAR_WSL_CUDA_PASSTHROUGH_ACTIVE=true
    SIDAR_USE_GPU_PREFLIGHT_FACTS=true

    detect_gpu

    [[ "$GPU_NAME" == "Preflight GPU" ]]
    [[ "$DRIVER_VER" == "610.62" ]]
    [[ "$CUDA_VERSION" == "13.0" ]]
    [[ "$GPU_COMPUTE_CAPABILITY" == "8.6" ]]
    [[ "$VRAM_MB" == "8192" ]]
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"GPU     : Preflight GPU"* ]]
  [[ "$output" == *"NVIDIA Windows Driver : 610.62"* ]]
  [[ "$output" == *"Driver CUDA API Capability : 13.0"* ]]
  [[ "$output" == *"WSL CUDA Passthrough : aktif"* ]]
  [[ "$output" == *"Compute : 8.6"* ]]
}

@test "persist_run_gpu_stress_dotenv creates development dotenv from example" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/.env.development.example" <<ENV
SIDAR_ENV=development
RUN_GPU_STRESS=0
ENV
    SCRIPT_DIR="$tmpdir"
    RUN_GPU_STRESS=1
    persist_run_gpu_stress_dotenv
    grep -q "^SIDAR_ENV=development$" "$tmpdir/.env.development"
    grep -q "^RUN_GPU_STRESS=1$" "$tmpdir/.env.development"
  '
  [ "$status" -eq 0 ]
}

@test "verify_sidar_keys_file_permissions accepts 600 and 400 modes" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SIDAR_KEYS_FILE="$tmpdir/.sidar_keys.env"
    printf "OPENAI_API_KEY=test\\n" > "$SIDAR_KEYS_FILE"

    chmod 600 "$SIDAR_KEYS_FILE"
    verify_sidar_keys_file_permissions

    chmod 400 "$SIDAR_KEYS_FILE"
    verify_sidar_keys_file_permissions
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"mode=600"* ]]
  [[ "$output" == *"mode=400"* ]]
  [[ "$output" != *"izinleri güvenli değil"* ]]
}

@test "verify_sidar_keys_file_permissions repairs generated env secret file permissions" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    SIDAR_KEYS_FILE="$tmpdir/.sidar_keys.env"
    for env_name in .env .env.advanced .env.development .env.test .env.production; do
      printf "API_KEY=secret_%s\\n" "$env_name" > "$tmpdir/$env_name"
      chmod 644 "$tmpdir/$env_name"
    done

    verify_sidar_keys_file_permissions

    for env_name in .env .env.advanced .env.development .env.test .env.production; do
      [[ "$(stat -c %a "$tmpdir/$env_name")" == "600" ]]
    done
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *".env izinleri güvenli değil"* ]]
  [[ "$output" == *".env.production izinleri 600 olarak düzeltildi"* ]]
}

@test "collect_api_keys_interactive warns once when real keys are not synced to .env.test" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    HOME="$tmpdir"
    NO_INTERACTION=true
    SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=0
    SIDAR_KEYS_FILE="$tmpdir/.sidar_keys.env"
    env_file="$tmpdir/.env"
    : > "$env_file"
    : > "$tmpdir/.env.test"
    valid_user_api_value() {
      case "$1" in
        SLACK_WEBHOOK_URL) printf "https://hooks.slack.com/services/test/%s" "$2" ;;
        JIRA_URL) printf "https://example-%s.atlassian.net" "$2" ;;
        TEAMS_WEBHOOK_URL) printf "https://example.invalid/teams/%s" "$2" ;;
        *) printf "value_%s" "$1" ;;
      esac
    }
    idx=0
    while IFS= read -r key; do
      idx=$((idx + 1))
      printf "%s=%s\\n" "$key" "$(valid_user_api_value "$key" "$idx")" >> "$env_file"
    done < <(sidar_user_api_key_names)

    collect_api_keys_interactive "$env_file"

    grep -q "^OPENAI_API_KEY=value_OPENAI_API_KEY$" "$SIDAR_KEYS_FILE"
    grep -q "^OPENAI_API_KEY=value_OPENAI_API_KEY$" "$env_file"
    ! grep -q "^OPENAI_API_KEY=value_OPENAI_API_KEY$" "$tmpdir/.env.test"
  '
  [ "$status" -eq 0 ]
  [[ "$(grep -c "SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV" <<<"$output")" -eq 1 ]]
  [[ "$(grep -c "SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV" <<<"$output")" -eq 0 ]]
}

@test "collect_api_keys_interactive materializes real keys to env files only with explicit opt-in" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SCRIPT_DIR="$tmpdir"
    HOME="$tmpdir"
    NO_INTERACTION=true
    SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV=1
    SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=0
    SIDAR_KEYS_FILE="$tmpdir/.sidar_keys.env"
    env_file="$tmpdir/.env"
    : > "$env_file"
    : > "$tmpdir/.env.development"
    : > "$tmpdir/.env.test"
    printf "OPENAI_API_KEY=from_env\\n" >> "$env_file"

    collect_api_keys_interactive "$env_file"

    grep -q "^OPENAI_API_KEY=from_env$" "$env_file"
    grep -q "^OPENAI_API_KEY=from_env$" "$tmpdir/.env.development"
    ! grep -q "^OPENAI_API_KEY=from_env$" "$tmpdir/.env.test"
  '
  [ "$status" -eq 0 ]
  [[ "$(grep -c "SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV" <<<"$output")" -eq 1 ]]
}

@test "ensure_auto_secrets preserves existing MEMORY_ENCRYPTION_KEY and logs reuse" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    for _attempt in {1..20}; do
      memory_key="$(openssl rand -base64 32 | tr "+/" "-_")"
      if ! is_weak_secret_value "$memory_key"; then
        break
      fi
    done
    ! is_weak_secret_value "$memory_key"
    env_file="$tmpdir/.env"
    printf "MEMORY_ENCRYPTION_KEY=%s\\n" "$memory_key" > "$env_file"

    ensure_auto_secrets "$env_file"

    [[ "$(read_env_value_from_file MEMORY_ENCRYPTION_KEY "$env_file")" == "$memory_key" ]]
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"MEMORY_ENCRYPTION_KEY mevcut ve güvenli; yeniden üretilmedi"* ]]
  [[ "$output" != *"MEMORY_ENCRYPTION_KEY (Fernet) otomatik üretildi"* ]]
}

@test "ensure_auto_secrets retries generated tokens that match weak placeholder patterns" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    env_file="$tmpdir/.env"
    printf "JWT_SECRET_KEY=replace-with-a-local-development-jwt-secret-32-plus-chars\\n" > "$env_file"
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/bin/python3" <<EOF
#!/usr/bin/env bash
count_file="$tmpdir/python3.count"
count=0
if [[ -f "\$count_file" ]]; then
  count=\$(cat "\$count_file")
fi
count=\$((count + 1))
printf "%s\\n" "\$count" > "\$count_file"
if [[ "\$*" == "-c import secrets; print(secrets.token_urlsafe(64))" ]]; then
  jwt_count_file="$tmpdir/python3.jwt.count"
  jwt_count=0
  if [[ -f "\$jwt_count_file" ]]; then
    jwt_count=\$(cat "\$jwt_count_file")
  fi
  jwt_count=\$((jwt_count + 1))
  printf "%s\\n" "\$jwt_count" > "\$jwt_count_file"
  if [[ "\$jwt_count" -eq 1 ]]; then
    printf "%s\\n" "GeneratedTESTTokenThatShouldBeRejectedBecauseItContainsTest1234567890"
  else
    printf "%s\\n" "GnrtdStrongToknWithoutPlacehldrWords_QwE9RtY8UiO7PaS6DfG5HjK4LmN3"
  fi
  exit 0
fi
exit 1
EOF
    chmod +x "$tmpdir/bin/python3"
    export PATH="$tmpdir/bin:$PATH"
    secret_strength_script_file() { return 0; }

    ensure_auto_secrets "$env_file"

    grep -q "^JWT_SECRET_KEY=GnrtdStrongToknWithoutPlacehldrWords_QwE9RtY8UiO7PaS6DfG5HjK4LmN3$" "$env_file"
    ! grep -q "GeneratedTESTToken" "$env_file"
  '
  [ "$status" -eq 0 ]
}

@test "verify_sidar_keys_file_permissions warns when secret file is group-readable" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    SIDAR_KEYS_FILE="$tmpdir/.sidar_keys.env"
    printf "OPENAI_API_KEY=test\\n" > "$SIDAR_KEYS_FILE"
    chmod 640 "$SIDAR_KEYS_FILE"

    verify_sidar_keys_file_permissions
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"SIDAR_KEYS_FILE izinleri güvenli değil"* ]]
  [[ "$output" == *"chmod 600"* ]]
}

@test "finish summary prefers run_tests all summary for integration e2e and frontend status" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    TEST_SUMMARY_JSON="$tmpdir/test-summary.json"
    cat > "$TEST_SUMMARY_JSON" <<JSON
{"integration":"passed","e2e":"passed","frontend_lint":"passed","frontend_typecheck":"passed","frontend_coverage":"passed","frontend_e2e":"passed"}
JSON
    INTEGRATION_TEST_STATUS="atlandi_bayrak"
    FRONTEND_QUALITY_STATUS="atlandi_bayrak"
    print_install_summary_extended_test_statuses
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"Entegrasyon testleri: başarılı (run_tests.sh --stage all içinde doğrulandı)."* ]]
  [[ "$output" == *"E2E testleri: başarılı (run_tests.sh --stage all içinde doğrulandı)."* ]]
  [[ "$output" == *"Frontend kalite kapısı: başarılı (run_tests.sh --stage all içinde lint/typecheck/coverage/e2e doğrulandı)."* ]]
  [[ "$output" != *"Entegrasyon testleri: atlandı"* ]]
}
