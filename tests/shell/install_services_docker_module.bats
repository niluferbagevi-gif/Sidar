#!/usr/bin/env bats

bats_require_minimum_version 1.5.0

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

@test "services_docker module materializes missing monitoring bind-mount paths" {
  root="$(repo_root)"
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT

  run bash -c '
    set -Eeuo pipefail
    export SCRIPT_DIR="$1"
    warn() { printf "WARN:%s\n" "$*"; }
    fail() { printf "FAIL:%s\n" "$*"; exit 1; }
    source "$2/scripts/install_modules/utils/services_docker.sh"
    validate_monitoring_mount_paths
    test -f "$SCRIPT_DIR/docker_setup/prometheus/prometheus.yml"
    test -d "$SCRIPT_DIR/docker_setup/grafana/provisioning"
    test -d "$SCRIPT_DIR/docker_setup/grafana/dashboards"
    test -f "$SCRIPT_DIR/docker_setup/grafana/provisioning/datasources/prometheus.yml"
  ' _ "$tmpdir" "$root"

  [ "$status" -eq 0 ]
  [[ "$output" == *"Prometheus konfigürasyon dosyası bulunamadı"* ]]
  [[ "$output" == *"Grafana provisioning dizini bulunamadı"* ]]
}
