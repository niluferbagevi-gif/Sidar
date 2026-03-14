#!/usr/bin/env bash
# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

set -euo pipefail

# SİDAR Host Sandbox Installer
# - gVisor (runsc) veya Kata Containers runtime kurar
# - Docker daemon runtime ayarlarını /etc/docker/daemon.json içinde günceller
#
# Örnek:
#   sudo bash scripts/install_host_sandbox.sh --mode gvisor
#   sudo bash scripts/install_host_sandbox.sh --mode kata
#   sudo bash scripts/install_host_sandbox.sh --mode both
#   sudo bash scripts/install_host_sandbox.sh --mode gvisor --dry-run

MODE="gvisor"
DRY_RUN="0"
NO_RESTART="0"

usage() {
  cat <<USAGE
Usage: $0 [--mode gvisor|kata|both] [--dry-run] [--no-restart]

Options:
  --mode         Kurulacak runtime (default: gvisor)
  --dry-run      Komutları çalıştırmadan sadece planı yazdır
  --no-restart   Docker servisini yeniden başlatma
  -h, --help     Yardım
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
      ;;
    --no-restart)
      NO_RESTART="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
 done

if [[ "$MODE" != "gvisor" && "$MODE" != "kata" && "$MODE" != "both" ]]; then
  echo "--mode yalnızca gvisor|kata|both olabilir" >&2
  exit 1
fi

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] $*"
  else
    eval "$*"
  fi
}

require_root() {
  if [[ "$EUID" -ne 0 ]]; then
    echo "Bu script root/sudo ile çalıştırılmalıdır." >&2
    exit 1
  fi
}

install_gvisor() {
  echo "==> gVisor (runsc) kurulumu"
  run "ARCH=\$(dpkg --print-architecture); \
  curl -fsSL -o /usr/local/bin/runsc https://storage.googleapis.com/gvisor/releases/release/latest/\${ARCH}/runsc; \
  curl -fsSL -o /usr/local/bin/containerd-shim-runsc-v1 https://storage.googleapis.com/gvisor/releases/release/latest/\${ARCH}/containerd-shim-runsc-v1; \
  chmod a+rx /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1"
}

install_kata() {
  echo "==> Kata Containers kurulumu"
  run "apt-get update"
  run "DEBIAN_FRONTEND=noninteractive apt-get install -y kata-containers"

  # Bazı dağıtımlarda binary adı/container yolu farklı olabiliyor.
  if [[ "$DRY_RUN" == "0" ]]; then
    if ! command -v kata-runtime >/dev/null 2>&1; then
      if [[ -x /usr/bin/kata-runtime ]]; then
        ln -sf /usr/bin/kata-runtime /usr/local/bin/kata-runtime
      elif [[ -x /usr/bin/kata-qemu ]]; then
        ln -sf /usr/bin/kata-qemu /usr/local/bin/kata-runtime
      fi
    fi
  else
    echo "[dry-run] kata-runtime binary kontrol/bağlantı adımı"
  fi
}

configure_docker_runtimes() {
  echo "==> Docker runtime konfigürasyonu (/etc/docker/daemon.json)"
  local daemon_file="/etc/docker/daemon.json"

  if [[ "$DRY_RUN" == "0" ]]; then
    mkdir -p /etc/docker
    if [[ -f "$daemon_file" ]]; then
      cp "$daemon_file" "${daemon_file}.bak.$(date +%Y%m%d%H%M%S)"
    fi

    MODE_ENV="$MODE" python3 - <<'PY'
import json
import os
from pathlib import Path

mode = os.environ.get("MODE_ENV", "gvisor")
path = Path("/etc/docker/daemon.json")
if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"daemon.json parse edilemedi: {exc}")
else:
    data = {}

runtimes = data.get("runtimes") or {}
if mode in ("gvisor", "both"):
    runtimes["runsc"] = {"path": "/usr/local/bin/runsc"}
if mode in ("kata", "both"):
    runtimes["kata-runtime"] = {"path": "kata-runtime"}

data["runtimes"] = runtimes

if mode == "gvisor":
    data["default-runtime"] = "runsc"
elif mode == "kata":
    data["default-runtime"] = "kata-runtime"

path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(path)
PY
  else
    echo "[dry-run] daemon.json runtimes alanına mode=${MODE} eklenecek"
  fi
}

restart_and_verify() {
  if [[ "$NO_RESTART" == "1" ]]; then
    echo "==> Docker restart atlandı (--no-restart)"
    return
  fi

  echo "==> Docker servisi yeniden başlatılıyor"
  run "systemctl restart docker"

  echo "==> Runtime doğrulaması"
  run "docker info | sed -n '/Runtimes:/,/Default Runtime:/p'"

  if [[ "$MODE" == "gvisor" || "$MODE" == "both" ]]; then
    run "docker run --rm --runtime=runsc hello-world >/dev/null"
  fi
  if [[ "$MODE" == "kata" || "$MODE" == "both" ]]; then
    run "docker run --rm --runtime=kata-runtime hello-world >/dev/null"
  fi
}

print_env_hint() {
  cat <<HINT

✅ Kurulum tamamlandı.

SİDAR için önerilen .env:
  DOCKER_MICROVM_MODE=${MODE}

Not:
- gVisor için: DOCKER_MICROVM_MODE=gvisor
- Kata için:   DOCKER_MICROVM_MODE=kata
- Override gerekirse: DOCKER_RUNTIME=runsc|kata-runtime
HINT
}

main() {
  require_root

  if [[ "$MODE" == "gvisor" || "$MODE" == "both" ]]; then
    install_gvisor
  fi

  if [[ "$MODE" == "kata" || "$MODE" == "both" ]]; then
    install_kata
  fi

  configure_docker_runtimes
  restart_and_verify
  print_env_hint
}

main "$@"