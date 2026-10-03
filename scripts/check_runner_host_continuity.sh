#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Sidar — Self-hosted runner host süreklilik teşhisi (salt okunur)
#
# GPU/benchmark runner'ını taşıyan host'ta (native Linux veya WSL2) çalıştırılır;
# runner'ın 7/24 online kalması için gereken ayarları denetler ve son kesintinin
# izini (reboot/shutdown kaydı, runner servis günlüğü) raporlar. Hiçbir ayarı
# DEĞİŞTİRMEZ; düzeltme adımları docs/runbooks/gpu-runner-continuity.md →
# "Host'u 7/24 açık tutma" bölümündedir.
#
# Çıkış kodları:
#   0 → FAIL yok (WARN olabilir)
#   1 → En az bir FAIL bulgusu var
#
# Kullanım:
#   ./scripts/check_runner_host_continuity.sh
#   ./scripts/check_runner_host_continuity.sh --since "3 days ago"
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

SINCE="3 days ago"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --since)
      SINCE="${2:?--since bir değer ister}"
      shift 2
      ;;
    -h | --help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *)
      echo "Bilinmeyen argüman: $1" >&2
      exit 2
      ;;
  esac
done

FAILS=0
pass() { printf '[PASS] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; }
fail() {
  printf '[FAIL] %s\n' "$1"
  FAILS=$((FAILS + 1))
}

IS_WSL=0
if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  IS_WSL=1
  pass "Platform: WSL2 (${WSL_DISTRO_NAME:-dağıtım adı bilinmiyor})"
else
  pass "Platform: native Linux"
fi

# 1) Runner servisleri systemd altında, açılışta otomatik başlamalı.
if [[ "$(ps -p 1 -o comm= 2>/dev/null)" != "systemd" ]]; then
  fail "PID 1 systemd değil; runner servisi (svc.sh) açılışta kendiliğinden başlayamaz."
else
  pass "PID 1 systemd"
  mapfile -t units < <(systemctl list-unit-files --no-legend 'actions.runner.*' 2>/dev/null | awk '{print $1}')
  if [[ ${#units[@]} -eq 0 ]]; then
    fail "actions.runner.* servisi yok; runner klasöründe 'sudo ./svc.sh install && sudo ./svc.sh start' çalıştırın."
  fi
  for unit in "${units[@]}"; do
    enabled="$(systemctl is-enabled "$unit" 2>/dev/null)"
    active="$(systemctl is-active "$unit" 2>/dev/null)"
    if [[ "$enabled" == "enabled" && "$active" == "active" ]]; then
      pass "$unit: enabled + active"
    else
      fail "$unit: is-enabled=$enabled is-active=$active"
    fi
  done
fi

# 2) WSL2'ye özgü: systemd açık olmalı, Windows uyumamalı, WSL açılışta kalkmalı.
if [[ $IS_WSL -eq 1 ]]; then
  if grep -Eqs '^[[:space:]]*systemd[[:space:]]*=[[:space:]]*true' /etc/wsl.conf; then
    pass "/etc/wsl.conf: [boot] systemd=true"
  else
    fail "/etc/wsl.conf içinde '[boot] systemd=true' yok."
  fi

  powercfg="/mnt/c/Windows/System32/powercfg.exe"
  if [[ -x "$powercfg" ]]; then
    for setting in STANDBYIDLE HIBERNATEIDLE; do
      # powercfg çıktısı Windows diline göre yerelleşir; son iki "0x…" satırı
      # her dilde sırasıyla AC ve DC güç ayarı dizinidir.
      ac="$("$powercfg" /query SCHEME_CURRENT SUB_SLEEP "$setting" 2>/dev/null |
        tr -d '\r' | grep -Eo '0x[0-9a-fA-F]+$' | tail -n 2 | head -n 1)"
      if [[ -z "$ac" ]]; then
        warn "Windows $setting (AC) okunamadı."
      elif ((ac == 0)); then
        pass "Windows $setting (AC): kapalı"
      else
        fail "Windows $setting (AC): $((ac / 60)) dk sonra devreye giriyor; host uykuya geçince runner offline olur."
      fi
    done
  else
    warn "powercfg.exe erişilemedi (WSL interop kapalı olabilir); Windows uyku ayarlarını elle doğrulayın."
  fi

  schtasks="/mnt/c/Windows/System32/schtasks.exe"
  task_list=""
  [[ -x "$schtasks" ]] && task_list="$("$schtasks" /query /fo csv /v 2>/dev/null | tr -d '\r')"
  if grep -qi 'wsl\.exe' <<<"$task_list"; then
    pass "wsl.exe çalıştıran bir Windows zamanlanmış görevi var (açılışta WSL'i kaldırma)."
  else
    warn "wsl.exe çalıştıran zamanlanmış görev bulunamadı; Windows yeniden başladığında WSL (ve runner) biri oturum açana kadar kapalı kalır."
  fi
fi

# 3) Son kesintinin izi: neden offline kaldığını ayırt etmek için.
echo
echo "── Kesinti kanıtı (since: $SINCE) ──"
echo "Host açılış zamanı: $(uptime -s 2>/dev/null || echo bilinmiyor)"
if command -v journalctl >/dev/null 2>&1; then
  echo "Açılışlar (journalctl --list-boots, son 5):"
  journalctl --list-boots --no-pager 2>/dev/null | tail -n 5
  echo "Runner servis olayları:"
  journalctl --no-pager --since "$SINCE" -u 'actions.runner.*' 2>/dev/null |
    grep -Ei 'connect error|listening for jobs|exiting|stopp|started|failed' | tail -n 20 ||
    echo "(eşleşen kayıt yok veya journal okuma yetkisi yok; sudo ile tekrar deneyin)"
fi

echo
if [[ $FAILS -gt 0 ]]; then
  echo "$FAILS FAIL bulgusu var. Düzeltme: docs/runbooks/gpu-runner-continuity.md → \"Host'u 7/24 açık tutma\"."
  exit 1
fi
echo "FAIL bulgusu yok."
