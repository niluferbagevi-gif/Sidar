#!/usr/bin/env bats

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

@test "check_empty_test_artifacts accepts populated tests" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/tests/unit"
  printf 'def test_example():\n    assert True\n' > "$tmpdir/tests/unit/test_example.py"

  run bash -c 'cd "$1" && bash "$2/scripts/check_empty_test_artifacts.sh"' _ "$tmpdir" "$root"

  rm -rf "$tmpdir"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Hatalı (boş) test dosyası bulunamadı"* ]]
}

@test "check_empty_test_artifacts rejects empty tests" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/tests/unit"
  : > "$tmpdir/tests/unit/test_empty.py"

  run bash -c 'cd "$1" && bash "$2/scripts/check_empty_test_artifacts.sh"' _ "$tmpdir" "$root"

  rm -rf "$tmpdir"
  [ "$status" -eq 1 ]
  [[ "$output" == *"Boş test dosyası/dosyaları bulundu"* ]]
  [[ "$output" == *"tests/unit/test_empty.py"* ]]
}

@test "audit_metrics emits deterministic JSON totals outside a git repository" {
  local root tmpdir
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/src"
  printf 'print("sidar")\n' > "$tmpdir/src/example.py"
  printf 'line one\nline two\n' > "$tmpdir/README.md"

  run bash "$root/scripts/audit_metrics.sh" "$tmpdir" json

  rm -rf "$tmpdir"
  [ "$status" -eq 0 ]
  [[ "$output" == *'"tracked":false'* ]]
  [[ "$output" != *"fatal: not a git repository"* ]]
  [[ "$output" == *'"py":{"files":1,"lines":1}'* ]]
  [[ "$output" == *'"md":{"files":1,"lines":2}'* ]]
  [[ "$output" == *'"totals":{"files":2,"lines":3}'* ]]
}

@test "install_ci_system_deps exits before apt when dependencies already exist" {
  local root tmpdir log
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  log="$tmpdir/apt.log"

  cat > "$tmpdir/apt-get" <<'SH'
#!/usr/bin/env bash
printf 'unexpected apt-get call: %s\n' "$*" >> "${SIDAR_TEST_APT_LOG}"
exit 99
SH
  cat > "$tmpdir/dpkg-query" <<'SH'
#!/usr/bin/env bash
printf 'Status: install ok installed\n'
SH
  chmod +x "$tmpdir/apt-get" "$tmpdir/dpkg-query"

  run env SIDAR_TEST_APT_LOG="$log" PATH="$tmpdir:/usr/bin:/bin" bash "$root/scripts/install_ci_system_deps.sh"

  [ "$status" -eq 0 ]
  [[ "$output" == *"System dependencies already installed"* ]]
  [ ! -e "$log" ]
  rm -rf "$tmpdir"
}
