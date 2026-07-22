#!/usr/bin/env bash
# `-e` kasıtlı olarak KULLANILMIYOR (run_tests.sh'deki aynı kararla tutarlı,
# bkz. o dosyadaki "set -uo pipefail" yorumu ve run_checked() deseni): bu
# betiğin ana amacı ./run_tests.sh / mutasyon testi / coverage kontrolü gibi
# adımların BAŞARISIZ OLMASINI algılayıp auto-heal/remediation akışını
# tetiklemektir. Her çağrı sonrası `$?` elle yakalanıp if/case ile ele
# alınıyor; `-e` eklenirse örn. `run_full_quality_tests` testler kırıldığında
# (asıl beklenen ve ele alınması gereken durum) betiği anında sonlandırır ve
# otonom onarım döngüsü hiç çalışmaz. Yeni bir komut eklerken exit kodunu
# `$?` ile yakalayıp açıkça kontrol edin; `-e`'ye güvenmeyin.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || exit 1

# Codespaces overlay dosya sisteminde uv hardlink denemesi pahalı uyarılara neden olur.
if [ -z "${UV_LINK_MODE:-}" ] && { [ "${CODESPACES:-}" = "true" ] || [ "${GITHUB_CODESPACES:-}" = "true" ]; }; then
  export UV_LINK_MODE=copy
fi

is_truthy_flag() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|y|Y|evet|EVET|Evet|e|E)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

ITERATIONS="${AUTONOMOUS_LOOP_ITERATIONS:-15}"
AUTO_REMEDIATION_MAX_RETRIES="${AUTONOMOUS_LOOP_REMEDIATION_RETRIES:-2}"
AUTONOMOUS_COVERAGE_PROFILE="${AUTONOMOUS_LOOP_COVERAGE_PROFILE:-short}"
AUTONOMOUS_OPERATION_PROFILE="${AUTONOMOUS_LOOP_OPERATION_PROFILE:-autonomous-improvement}"
AUTONOMOUS_COVERAGE_TARGET_FILE="${AUTONOMOUS_LOOP_COVERAGE_TARGET_FILE:-}"
AUTONOMOUS_COVERAGE_JSON="${AUTONOMOUS_LOOP_COVERAGE_JSON:-coverage.json}"
AUTONOMOUS_COVERAGE_XML="${AUTONOMOUS_LOOP_COVERAGE_XML:-coverage.xml}"
AUTONOMOUS_COVERAGE_AGENT_LIMIT="${AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT:-3}"
AUTONOMOUS_COVERAGE_AGENT_BATCH_SIZE="${AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE:-1}"
AUTONOMOUS_COVERAGE_MAX_MISSING_LINES="${AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_LINES:-25}"
AUTONOMOUS_COVERAGE_MAX_MISSING_BRANCHES="${AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_BRANCHES:-10}"
AUTONOMOUS_EXCLUDE_FILES="${AUTONOMOUS_LOOP_EXCLUDE_FILES:-${AUTONOMOUS_LOOP_COVERAGE_EXCLUDE_FILES:-web_server.py,main.py,gui_launcher.py,cli.py}}"
AUTONOMOUS_MUTATION_ENABLED="${AUTONOMOUS_LOOP_MUTATION_ENABLED:-true}"
AUTONOMOUS_MUTATION_MAX_CHILDREN="${AUTONOMOUS_LOOP_MUTATION_MAX_CHILDREN:-8}"
AUTONOMOUS_MUTATION_COMMAND="${AUTONOMOUS_LOOP_MUTATION_COMMAND:-uv run --with mutmut mutmut run --max-children ${AUTONOMOUS_MUTATION_MAX_CHILDREN}}"
AUTONOMOUS_MUTATION_RESULTS_COMMAND="${AUTONOMOUS_LOOP_MUTATION_RESULTS_COMMAND:-uv run --with mutmut mutmut results}"
AUTONOMOUS_MUTATION_STATS_COMMAND="${AUTONOMOUS_LOOP_MUTATION_STATS_COMMAND:-uv run --with mutmut mutmut export-cicd-stats}"
AUTONOMOUS_MUTATION_STATS_PATH="${AUTONOMOUS_LOOP_MUTATION_STATS_PATH:-artifacts/mutmut-stats.json}"
AUTONOMOUS_REMEDIATION_MODE="${AUTONOMOUS_LOOP_REMEDIATION_MODE:-hybrid}"
AUTONOMOUS_TEST_STATIC_ANALYSIS="${AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS:-0}"
AUTONOMOUS_SKIP_UPLOAD="${AUTONOMOUS_LOOP_SKIP_UPLOAD:-0}"
AUTONOMOUS_AUTO_HEAL_ENABLED="${AUTONOMOUS_LOOP_AUTO_HEAL_ENABLED:-1}"
AUTONOMOUS_AUTO_HEAL_HITL_APPROVE="${AUTONOMOUS_LOOP_AUTO_HEAL_HITL_APPROVE:-prompt}"
AUTONOMOUS_TEST_FAILURE_LOG="${AUTONOMOUS_LOOP_TEST_FAILURE_LOG:-artifacts/autonomous_loop_test_failure.log}"
AUTONOMOUS_AUTO_HEAL_RESULT_PATH="${AUTONOMOUS_LOOP_AUTO_HEAL_RESULT_PATH:-artifacts/autonomous_loop_auto_heal_result.json}"
AUTONOMOUS_REPORTS_DIR="${AUTONOMOUS_LOOP_REPORTS_DIR:-reports}"
AUTONOMOUS_RUN_LINTER_PHASES="${AUTONOMOUS_LOOP_RUN_LINTER_PHASES:-1}"
AUTONOMOUS_MYPY_REPORT="${AUTONOMOUS_LOOP_MYPY_REPORT:-${AUTONOMOUS_REPORTS_DIR}/mypy_report.txt}"
AUTONOMOUS_BANDIT_REPORT="${AUTONOMOUS_LOOP_BANDIT_REPORT:-${AUTONOMOUS_REPORTS_DIR}/bandit_report.json}"

resolve_local_coverage_gate() {
  python - <<'PY_LOCAL_COVERAGE_GATE'
from pathlib import Path
import tomllib

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
print(data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under", 5))
PY_LOCAL_COVERAGE_GATE
}

resolve_autonomous_coverage_target() {
  if [ -n "${AUTONOMOUS_LOOP_COVERAGE_TARGET+x}" ]; then
    echo "${AUTONOMOUS_LOOP_COVERAGE_TARGET}"
    return 0
  fi

  case "${AUTONOMOUS_COVERAGE_PROFILE}" in
    short)
      echo "99.8"
      ;;
    full)
      echo "100"
      ;;
    file)
      if [ -z "${AUTONOMOUS_COVERAGE_TARGET_FILE}" ]; then
        echo "[HATA] AUTONOMOUS_LOOP_COVERAGE_PROFILE=file için AUTONOMOUS_LOOP_COVERAGE_TARGET_FILE verilmelidir." >&2
        return 2
      fi
      echo "100"
      ;;
    *)
      echo "[HATA] AUTONOMOUS_LOOP_COVERAGE_PROFILE short/full/file olmalı. Verilen: ${AUTONOMOUS_COVERAGE_PROFILE}" >&2
      return 2
      ;;
  esac
}

LOCAL_COVERAGE_GATE="${COVERAGE_FAIL_UNDER:-$(resolve_local_coverage_gate)}"
AUTONOMOUS_COVERAGE_TARGET="$(resolve_autonomous_coverage_target)"
resolve_target_exit=$?
if [ "${resolve_target_exit}" -ne 0 ]; then
  exit "${resolve_target_exit}"
fi
case "${AUTONOMOUS_OPERATION_PROFILE}" in
  daily-local|autonomous-improvement|ci-required|coverage-campaign)
    ;;
  *)
    echo "[UYARI] Geçersiz AUTONOMOUS_LOOP_OPERATION_PROFILE='${AUTONOMOUS_OPERATION_PROFILE}'. 'autonomous-improvement' kullanılacak."
    AUTONOMOUS_OPERATION_PROFILE="autonomous-improvement"
    ;;
esac

if ! [[ "$AUTO_REMEDIATION_MAX_RETRIES" =~ ^[0-9]+$ ]] || [ "$AUTO_REMEDIATION_MAX_RETRIES" -lt 1 ]; then
  AUTO_REMEDIATION_MAX_RETRIES=2
fi
if [ "$AUTO_REMEDIATION_MAX_RETRIES" -gt 2 ]; then
  echo "[UYARI] Sonsuz döngü riskini sınırlamak için AUTO_REMEDIATION_MAX_RETRIES=2 olarak sınırlandı."
  AUTO_REMEDIATION_MAX_RETRIES=2
fi

if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [ "$ITERATIONS" -lt 1 ]; then
  echo "[HATA] AUTONOMOUS_LOOP_ITERATIONS pozitif bir tamsayı olmalı. Verilen: $ITERATIONS"
  exit 2
fi

if ! [[ "$AUTONOMOUS_COVERAGE_TARGET" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "[HATA] AUTONOMOUS_LOOP_COVERAGE_TARGET sayısal bir yüzde olmalı. Verilen: $AUTONOMOUS_COVERAGE_TARGET"
  exit 2
fi
if ! [[ "$LOCAL_COVERAGE_GATE" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "[UYARI] Yerel coverage gate değeri sayısal değil: '${LOCAL_COVERAGE_GATE}'. 90 kullanılacak."
  LOCAL_COVERAGE_GATE="90"
fi
if ! [[ "$AUTONOMOUS_MUTATION_MAX_CHILDREN" =~ ^[0-9]+$ ]] || [ "$AUTONOMOUS_MUTATION_MAX_CHILDREN" -lt 1 ]; then
  echo "[UYARI] AUTONOMOUS_LOOP_MUTATION_MAX_CHILDREN pozitif tamsayı değil: '${AUTONOMOUS_MUTATION_MAX_CHILDREN}'. 8 kullanılacak."
  AUTONOMOUS_MUTATION_MAX_CHILDREN="8"
fi
case "${AUTONOMOUS_MUTATION_ENABLED}" in
  true|TRUE|True)
    AUTONOMOUS_MUTATION_ENABLED="true"
    ;;
  false|FALSE|False|"")
    AUTONOMOUS_MUTATION_ENABLED="false"
    ;;
  *)
    echo "[UYARI] AUTONOMOUS_LOOP_MUTATION_ENABLED true/false olmalı. Alınan: '${AUTONOMOUS_MUTATION_ENABLED}'. Mutasyon kalite kapısı devre dışı bırakılacak."
    AUTONOMOUS_MUTATION_ENABLED="false"
    ;;
esac
case "${AUTONOMOUS_REMEDIATION_MODE}" in
  hybrid|full-static)
    ;;
  *)
    echo "[UYARI] AUTONOMOUS_LOOP_REMEDIATION_MODE hybrid veya full-static olmalı. Hibrit mod kullanılacak."
    AUTONOMOUS_REMEDIATION_MODE="hybrid"
    ;;
esac
case "${AUTONOMOUS_TEST_STATIC_ANALYSIS}" in
  0|1)
    ;;
  *)
    echo "[UYARI] AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS 0 veya 1 olmalı. Otonom döngü için 0 kullanılacak."
    AUTONOMOUS_TEST_STATIC_ANALYSIS="0"
    ;;
esac
if [ "${AUTONOMOUS_REMEDIATION_MODE}" = "hybrid" ] && [ "${AUTONOMOUS_TEST_STATIC_ANALYSIS}" != "0" ]; then
  echo "[UYARI] Hibrit otonom döngüde tekrar eden mypy/statik analiz kapalıdır; AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS=1 yok sayıldı."
  AUTONOMOUS_TEST_STATIC_ANALYSIS="0"
fi
case "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}" in
  yes|no|y|n|evet|hayır|e|h|true|false|1|0|prompt|ask|interactive)
    ;;
  *)
    echo "[UYARI] AUTONOMOUS_LOOP_AUTO_HEAL_HITL_APPROVE anlaşılamadı: '${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}'. Fail-closed için 'no' kullanılacak."
    AUTONOMOUS_AUTO_HEAL_HITL_APPROVE="no"
    ;;
esac
if [ -z "${AUTONOMOUS_LOOP_MUTATION_COMMAND+x}" ]; then
  AUTONOMOUS_MUTATION_COMMAND="uv run --with mutmut mutmut run --max-children ${AUTONOMOUS_MUTATION_MAX_CHILDREN}"
fi

run_config_preflight() {
  echo "[PREFLIGHT 0/3] Config: uv run python ile dotenv zinciri ve kritik anahtarlar doğrulanıyor"
  uv run python - <<'PY_CONFIG_PREFLIGHT'
from __future__ import annotations

import config

print("[CONFIG] Runtime dotenv yükleme zinciri:")
for event in config.get_dotenv_load_report():
    label = event.get("label", "unknown")
    path = event.get("path") or event.get("raw_path") or "-"
    status = "loaded" if event.get("loaded") else f"skipped:{event.get('reason') or 'not_loaded'}"
    override = "override" if event.get("override") else "no-override"
    print(f"[CONFIG] - {label}: {status} ({override}) {path}")

missing = config.Config.get_missing_critical_runtime_keys()
if missing:
    print("[CONFIG][HATA] Kritik runtime anahtarları çözülemedi: " + ", ".join(missing))
    print("[CONFIG][HATA] Yükleme zinciri: .env, .env.advanced, .env.${SIDAR_ENV}, DOTENV_FILE, SIDAR_KEYS_FILE")
    raise SystemExit(2)

print("[CONFIG][OK] Config importu ve kritik runtime anahtar kontrolü başarılı.")
PY_CONFIG_PREFLIGHT
}


if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "[INFO] Otonom döngü başlıyor. Toplam tekrar: $ITERATIONS"
echo "[INFO] Coverage operasyon profili: ${AUTONOMOUS_OPERATION_PROFILE}."
echo "[INFO] Günlük local kalite kapısı: run_tests.sh / pyproject.toml / COVERAGE_FAIL_UNDER => %${LOCAL_COVERAGE_GATE}."
echo "[INFO] Otonom coverage iyileştirme hedefi: AUTONOMOUS_LOOP_COVERAGE_PROFILE=${AUTONOMOUS_COVERAGE_PROFILE} => %${AUTONOMOUS_COVERAGE_TARGET}."
echo "[INFO] CoverageAgent mikro kapsamı: limit=${AUTONOMOUS_COVERAGE_AGENT_LIMIT}, batch_size=${AUTONOMOUS_COVERAGE_AGENT_BATCH_SIZE}, max_missing_lines=${AUTONOMOUS_COVERAGE_MAX_MISSING_LINES}, max_missing_branches=${AUTONOMOUS_COVERAGE_MAX_MISSING_BRANCHES}."
echo "[INFO] CI zorunlu gate ayrı profildir: CI=true TEST_PROFILE=ci ./run_tests.sh (AUTONOMOUS_LOOP hedefi CI gate değildir)."
echo "[INFO] Coverage kampanyası manuel/planlı çalışmadır: AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign ile görünür etiketlenebilir."
if [ -n "${AUTONOMOUS_COVERAGE_TARGET_FILE}" ]; then
  echo "[INFO] Otonom coverage hedef dosyası: ${AUTONOMOUS_COVERAGE_TARGET_FILE}."
fi
echo "[INFO] Otonom remediation modu: AUTONOMOUS_LOOP_REMEDIATION_MODE=${AUTONOMOUS_REMEDIATION_MODE}."
echo "[INFO] Otonom coverage metriği '${AUTONOMOUS_COVERAGE_JSON}' üzerinden okunacak."
echo "[INFO] CoverageAgent exclude listesi: AUTONOMOUS_LOOP_EXCLUDE_FILES='${AUTONOMOUS_EXCLUDE_FILES}'."
echo "[INFO] Mutasyon kalite kapısı: AUTONOMOUS_LOOP_MUTATION_ENABLED=${AUTONOMOUS_MUTATION_ENABLED}; max_children=${AUTONOMOUS_MUTATION_MAX_CHILDREN}; komut='${AUTONOMOUS_MUTATION_COMMAND}'."
echo "[INFO] Otonom test tekrarlarında RUN_STATIC_ANALYSIS=${AUTONOMOUS_TEST_STATIC_ANALYSIS}; hibrit modda mypy yalnız ön kontrol run_tests.sh kalite kapısında çalışır."
echo "[INFO] Upload adımı: AUTONOMOUS_LOOP_SKIP_UPLOAD=${AUTONOMOUS_SKIP_UPLOAD}."
echo "[INFO] Auto-heal adımı: AUTONOMOUS_LOOP_AUTO_HEAL_ENABLED=${AUTONOMOUS_AUTO_HEAL_ENABLED}; HITL=${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}; log=${AUTONOMOUS_TEST_FAILURE_LOG}."

# Artifact yolu arayan kontrol adımlarında (örn. rg --files artifacts/...) gereksiz uyarı
# üretmemek için otonom döngünün kullandığı temel dizinleri baştan oluştur.
mkdir -p "$(dirname "${AUTONOMOUS_TEST_FAILURE_LOG}")"
mkdir -p "$(dirname "${AUTONOMOUS_AUTO_HEAL_RESULT_PATH}")"
mkdir -p "$(dirname "${AUTONOMOUS_MUTATION_STATS_PATH}")"

run_config_preflight
config_preflight_exit=$?
if [ "${config_preflight_exit}" -ne 0 ]; then
  echo "[HATA] Config preflight başarısız oldu (exit code: ${config_preflight_exit}); otonom kalite kapıları başlatılmadı."
  exit "${config_preflight_exit}"
fi
if [ "${AUTONOMOUS_LOOP_PRINT_CONFIG:-0}" = "1" ]; then
  echo "[INFO] AUTONOMOUS_LOOP_PRINT_CONFIG=1 verildi; otonom döngü başlatılmadan yapılandırma doğrulaması tamamlandı."
  exit 0
fi
read_coverage_percent() {
  local coverage_json="${1:-coverage.json}"
  local target_file="${2:-}"

  if [ ! -f "${coverage_json}" ]; then
    echo "[UYARI] ${coverage_json} bulunamadı; coverage hedefi değerlendirilemiyor." >&2
    return 2
  fi

  python - "${coverage_json}" "${target_file}" <<'PY_COVERAGE_PERCENT'
import json
import sys
from pathlib import Path

coverage_path = Path(sys.argv[1])
target_file = (sys.argv[2] if len(sys.argv) > 2 else "").strip().lstrip("./")
try:
    payload = json.loads(coverage_path.read_text(encoding="utf-8"))
    if target_file:
        files = payload.get("files") or {}
        normalized_files = {str(path).lstrip("./"): data for path, data in files.items()}
        file_payload = normalized_files[target_file]
        percent = file_payload["summary"]["percent_covered"]
    else:
        percent = payload["totals"]["percent_covered"]
except KeyError as exc:
    scope = f"files[{target_file!r}].summary.percent_covered" if target_file else "totals.percent_covered"
    print(f"[UYARI] {coverage_path} {scope} içermiyor: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc
except Exception as exc:  # noqa: BLE001 - shell kullanıcılarına net hata vermek için geniş yakalanır.
    print(f"[UYARI] {coverage_path} okunamadı: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

try:
    print(f"{float(percent):.2f}")
except (TypeError, ValueError) as exc:
    print(f"[UYARI] {coverage_path} içindeki percent_covered sayısal değil: {percent!r}", file=sys.stderr)
    raise SystemExit(2) from exc
PY_COVERAGE_PERCENT
}

coverage_target_reached() {
  local current_percent="$1"
  local target_percent="$2"

  python - "${current_percent}" "${target_percent}" <<'PY_COVERAGE_COMPARE'
from decimal import Decimal, InvalidOperation
import sys

try:
    current = Decimal(sys.argv[1])
    target = Decimal(sys.argv[2])
except (InvalidOperation, IndexError) as exc:
    print(f"[UYARI] Coverage karşılaştırması için geçersiz değer: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc

if current >= target:
    raise SystemExit(0)
raise SystemExit(1)
PY_COVERAGE_COMPARE
}

is_true_flag() {
  case "${1:-}" in
    true|TRUE|True)
      return 0
      ;;
    false|FALSE|False|"")
      return 1
      ;;
    *)
      echo "[UYARI] Boolean bayrak true/false olmalı. Alınan: '${1:-}'" >&2
      return 1
      ;;
  esac
}

run_mutation_quality_gate() {
  local mutation_exit
  local results_exit
  local stats_exit

  if ! is_true_flag "${AUTONOMOUS_MUTATION_ENABLED}"; then
    echo "[MUTATION] Mutasyon testi kalite kapısı devre dışı (AUTONOMOUS_LOOP_MUTATION_ENABLED=${AUTONOMOUS_MUTATION_ENABLED})."
    return 0
  fi

  mkdir -p "$(dirname "${AUTONOMOUS_MUTATION_STATS_PATH}")"
  echo "[MUTATION] Mutasyon testi başlatılıyor: ${AUTONOMOUS_MUTATION_COMMAND}"
  bash -lc "${AUTONOMOUS_MUTATION_COMMAND}"
  mutation_exit=$?

  echo "[MUTATION] Mutasyon sonuç özeti: ${AUTONOMOUS_MUTATION_RESULTS_COMMAND}"
  bash -lc "${AUTONOMOUS_MUTATION_RESULTS_COMMAND}"
  results_exit=$?
  if [ "${results_exit}" -ne 0 ]; then
    echo "[MUTATION] Sonuç özeti alınamadı (exit code: ${results_exit}); ana mutasyon sonucu korunacak."
  fi

  echo "[MUTATION] CI istatistikleri yazılıyor: ${AUTONOMOUS_MUTATION_STATS_PATH}"
  bash -lc "${AUTONOMOUS_MUTATION_STATS_COMMAND}" > "${AUTONOMOUS_MUTATION_STATS_PATH}"
  stats_exit=$?
  if [ "${stats_exit}" -ne 0 ]; then
    echo "[MUTATION] Mutasyon istatistik artefaktı üretilemedi (exit code: ${stats_exit}); ana mutasyon sonucu korunacak."
  fi

  if [ "${mutation_exit}" -ne 0 ]; then
    echo "[HATA] Mutasyon testi başarısız oldu (exit code: ${mutation_exit}). Coverage yüksek olsa bile testler davranış değişikliklerini yakalayamıyor."
    return 1
  fi

  echo "[OK] Mutasyon testi kalite kapısı geçti."
  return 0
}

check_autonomous_quality_gate() {
  local test_exit="$1"
  local current_percent
  local coverage_status

  if [ "${test_exit}" -ne 0 ]; then
    echo "[UYARI] Test adımı başarısız oldu (exit code: ${test_exit})."
    return 1
  fi

  current_percent="$(read_coverage_percent "${AUTONOMOUS_COVERAGE_JSON}" "${AUTONOMOUS_COVERAGE_TARGET_FILE}")"
  coverage_status=$?
  if [ "${coverage_status}" -ne 0 ]; then
    echo "[UYARI] Testler geçti fakat otonom coverage metriği okunamadı; iyileştirme döngüsü tetiklenecek."
    return 2
  fi

  if coverage_target_reached "${current_percent}" "${AUTONOMOUS_COVERAGE_TARGET}"; then
    echo "[OK] Otonom coverage iyileştirme hedefi sağlandı: %${current_percent} >= %${AUTONOMOUS_COVERAGE_TARGET}."
    if run_mutation_quality_gate; then
      return 0
    fi
    echo "[UYARI] Coverage hedefi sağlandı fakat mutasyon kalite kapısı başarısız oldu; daha güçlü davranış odaklı testler gerekiyor."
    return 4
  fi

  echo "[INFO] Günlük local kalite kapısı geçti (run_tests.sh exit=0; gate=%${LOCAL_COVERAGE_GATE})."
  echo "[INFO] Otonom coverage iyileştirme hedefi ayrı bir operasyon hedefidir ve henüz sağlanmadı: %${current_percent} < %${AUTONOMOUS_COVERAGE_TARGET}."
  return 3
}

run_coverage_agent() {
  if [ ! -f "${AUTONOMOUS_COVERAGE_XML}" ]; then
    echo "[HEAL] ${AUTONOMOUS_COVERAGE_XML} bulunamadı; CoverageAgent adımı atlandı."
    return 0
  fi

  echo "[HEAL] CoverageAgent tetikleniyor (coverage analizi + test önerisi)..."
  AUTONOMOUS_LOOP_COVERAGE_XML="${AUTONOMOUS_COVERAGE_XML}" \
  AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT="${AUTONOMOUS_COVERAGE_AGENT_LIMIT}" \
  AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE="${AUTONOMOUS_COVERAGE_AGENT_BATCH_SIZE}" \
  AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_LINES="${AUTONOMOUS_COVERAGE_MAX_MISSING_LINES}" \
  AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_BRANCHES="${AUTONOMOUS_COVERAGE_MAX_MISSING_BRANCHES}" \
  AUTONOMOUS_LOOP_EXCLUDE_FILES="${AUTONOMOUS_EXCLUDE_FILES}" \
    uv run python - <<'PY_COVERAGE_AGENT'
import asyncio
import json
import os
from pathlib import Path

from agent.roles.coverage_agent import CoverageAgent
from agent.roles.reviewer_agent import ReviewerAgent
from config import Config


def _static_candidate_rejection_reason(code: str, finding: dict | None = None) -> str:
    return CoverageAgent._candidate_rejection_reason(code, finding=finding or {})


def _looks_trivial_test(code: str) -> bool:
    return bool(_static_candidate_rejection_reason(code))


REJECTION_STATE_PATH = Path(os.getenv("AUTONOMOUS_LOOP_REVIEWER_BLOCK_STATE", "artifacts/coverage_reviewer_rejections.json"))
REVIEWER_GATE_SEMANTIC_CRITERIA = (
    "eksik exception path'i",
    "tautolojik mock kontrolü",
    "hedef modül davranışına bağlanmayan assertion",
    "import-only veya sabit/trivial coverage testi",
)
REVIEWER_GATE_MISSING_REASON = "(neden belirtilmedi)"


def _rejection_signatures(result: dict) -> list[str]:
    signatures: list[str] = []
    for item in result.get("results", []) or []:
        if not isinstance(item, dict) or item.get("status") != "review_rejected":
            continue
        target_path = str(item.get("target_path") or "<unknown>").strip() or "<unknown>"
        review_reason = str(item.get("review_reason") or "<unknown>").strip() or "<unknown>"
        signatures.append(f"{target_path}|{review_reason}")
    return sorted(set(signatures))


def _update_reviewer_block_state(result: dict) -> dict:
    """Aynı hedef+red tipi tekrar ederse otonom döngüyü reviewer blokajı olarak işaretler."""
    signatures = _rejection_signatures(result)
    has_success = any(
        bool(item.get("success")) for item in result.get("results", []) or [] if isinstance(item, dict)
    )
    if has_success:
        if REJECTION_STATE_PATH.exists():
            REJECTION_STATE_PATH.unlink(missing_ok=True)
        return result
    if not signatures:
        return result

    previous_signatures: set[str] = set()
    repeat_count = 1
    if REJECTION_STATE_PATH.exists():
        try:
            previous = json.loads(REJECTION_STATE_PATH.read_text(encoding="utf-8"))
            previous_signatures = set(str(item) for item in previous.get("signatures", []) or [])
            repeat_count = int(previous.get("repeat_count", 1) or 1)
        except Exception as exc:  # noqa: BLE001 - bozuk state dosyası döngüyü kırmamalı.
            print(f"[CoverageAgent] reviewer block state okunamadı; sıfırlanıyor: {exc}")
            previous_signatures = set()
            repeat_count = 1

    repeated = sorted(set(signatures) & previous_signatures)
    if repeated:
        repeat_count += 1
        result["status"] = "blocked_by_reviewer"
        result["success"] = False
        result["blocked_reason"] = "same_target_same_rejection_repeated"
        result["manual_action"] = "Manuel test yazılması gerekiyor; aynı hedef dosya aynı red tipiyle tekrar reddedildi."
        result["repeated_rejections"] = repeated
    else:
        repeat_count = 1

    REJECTION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REJECTION_STATE_PATH.write_text(
        json.dumps(
            {
                "signatures": signatures,
                "repeat_count": repeat_count,
                "status": result.get("status"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


async def _review_with_reviewer_agent(cfg: Config, candidate: str, finding: dict) -> bool:
    reviewer = ReviewerAgent(config=cfg)
    candidate_path = str(finding.get("suggested_test_path") or "")
    result = await reviewer.review_test_candidate(
        candidate,
        finding,
        candidate_path=candidate_path,
    )
    approved = bool(result.get("approved", False))
    reason = str(result.get("reason", "") or "").strip()
    reason_display = reason or REVIEWER_GATE_MISSING_REASON
    weaknesses = list(result.get("weaknesses") or [])[:2]
    candidate_preview = str(result.get("candidate_preview") or "").strip() or "<empty>"
    print(f"[ReviewerAgent] semantic_criteria={REVIEWER_GATE_SEMANTIC_CRITERIA}")
    print(
        "[ReviewerAgent] "
        f"approved={approved} reason={reason_display} attempts={result.get('attempts', 1)} "
        f"target_path={result.get('target_path') or finding.get('target_path', '<unknown>')} "
        f"suggested_test_path={result.get('suggested_test_path') or candidate_path or '<unknown>'} "
        f"finding_index={result.get('finding_index') or finding.get('finding_index', '<unknown>')} "
        f"candidate_preview={candidate_preview}"
    )
    if weaknesses:
        print(f"[ReviewerAgent] weaknesses={weaknesses}")
    elif not approved:
        print("[ReviewerAgent] weaknesses_missing=true")
    if result.get("invalid_reason"):
        print("[ReviewerAgent] invalid_reason=true; boş red gerekçesi fail-closed reddedildi.")
        raw_json = str(result.get("raw_reviewer_json") or "").strip()
        if raw_json:
            print(f"[ReviewerAgent] raw_reviewer_json={raw_json[:1000]}")
    return approved


async def main() -> int:
    cfg = Config()
    agent = CoverageAgent(config=cfg)
    coverage_xml = os.getenv("AUTONOMOUS_LOOP_COVERAGE_XML", "coverage.xml")
    limit = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_AGENT_LIMIT", "3") or "3")
    batch_size = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_AGENT_BATCH_SIZE", "1") or "1")
    max_missing_lines = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_LINES", "25") or "25")
    max_missing_branches = int(os.getenv("AUTONOMOUS_LOOP_COVERAGE_MAX_MISSING_BRANCHES", "10") or "10")
    exclude_files = [
        item.strip()
        for item in os.getenv("AUTONOMOUS_LOOP_EXCLUDE_FILES", "").split(",")
        if item.strip()
    ]

    async def reviewer_gate(candidate: str, finding: dict) -> bool:
        static_rejection_reason = _static_candidate_rejection_reason(candidate, finding)
        if static_rejection_reason:
            print(
                "[ReviewerGate] Test önerisi statik kalite filtresinden geçemedi "
                f"(reason={static_rejection_reason}). Reddedildi."
            )
            return False
        approved = await _review_with_reviewer_agent(cfg, str(candidate), finding)
        if not approved:
            print("[ReviewerGate] ReviewerAgent semantik onay vermedi. Öneri uygulanmayacak.")
        return approved

    # run_autonomous_coverage_batch içeride CoverageAgent write_missing_tests aracını çağırır.
    result = await agent.run_autonomous_coverage_batch(
        coverage_xml=coverage_xml,
        coveragerc="pyproject.toml",
        limit=limit,
        batch_size=batch_size,
        append=True,
        reviewer_gate=reviewer_gate,
        max_missing_lines_per_finding=max_missing_lines,
        max_missing_branches_per_finding=max_missing_branches,
        exclude_files=exclude_files,
    )
    result = _update_reviewer_block_state(result)
    print(f"[CoverageAgent] {result.get('summary', 'coverage batch analizi tamamlandı.')}")
    print(
        f"[CoverageAgent] batch_count={result.get('batch_count', 0)} "
        f"total_findings={result.get('total_findings', 0)}"
    )
    for item in result.get("results", []):
        print(
            "[CoverageAgent] "
            f"batch={item.get('batch_index')} finding={item.get('finding_index')} "
            f"status={item.get('status')} target={item.get('target_path')} "
            f"test={item.get('suggested_test_path')}"
        )
    if result.get("status") == "no_gaps_detected":
        print("[CoverageAgent] Coverage açığı bulunamadı.")
        return 0
    if result.get("status") == "blocked_by_reviewer":
        print(
            "[CoverageAgent] status=blocked_by_reviewer reason="
            f"{result.get('blocked_reason')} repeated={result.get('repeated_rejections', [])}"
        )
        print(f"[CoverageAgent] {result.get('manual_action')}")
        return 3
    return 0 if any(item.get("success") for item in result.get("results", [])) else 1


raise SystemExit(asyncio.run(main()))
PY_COVERAGE_AGENT
}


run_github_upload() {
  if is_truthy_flag "${AUTONOMOUS_SKIP_UPLOAD}"; then
    echo "[UPLOAD] AUTONOMOUS_LOOP_SKIP_UPLOAD=${AUTONOMOUS_SKIP_UPLOAD}; github_upload.py adımı atlandı."
    return 0
  fi
  uv run python github_upload.py
}

_capture_quality_command() {
  local log_path="$1"
  shift
  mkdir -p "$(dirname "${log_path}")"
  "$@" 2>&1 | tee "${log_path}"
  return "${PIPESTATUS[0]}"
}

run_full_quality_tests() {
  _capture_quality_command \
    "${AUTONOMOUS_TEST_FAILURE_LOG}" \
    env CI=true AUTO_HEAL_ON_FAILURE=0 ./run_tests.sh
}

run_autonomous_quality_tests() {
  _capture_quality_command \
    "${AUTONOMOUS_TEST_FAILURE_LOG}" \
    env RUN_STATIC_ANALYSIS="${AUTONOMOUS_TEST_STATIC_ANALYSIS}" AUTO_HEAL_ON_FAILURE=0 ./run_tests.sh
}

run_auto_heal_for_test_failure() {
  local source="${1:-pytest}"
  local log_path="${AUTONOMOUS_TEST_FAILURE_LOG}"

  if ! is_truthy_flag "${AUTONOMOUS_AUTO_HEAL_ENABLED}"; then
    echo "[HEAL] Auto-heal devre dışı (AUTONOMOUS_LOOP_AUTO_HEAL_ENABLED=${AUTONOMOUS_AUTO_HEAL_ENABLED})."
    return 1
  fi
  if [ ! -s "${log_path}" ]; then
    echo "[HEAL] Auto-heal log dosyası yok veya boş: ${log_path}"
    return 1
  fi

  mkdir -p "$(dirname "${AUTONOMOUS_AUTO_HEAL_RESULT_PATH}")"
  echo "[HEAL] Self-heal tetikleniyor: source=${source}, log=${log_path}, output=${AUTONOMOUS_AUTO_HEAL_RESULT_PATH}"
  local cmd=(
    uv run python -m scripts.auto_heal
    --log "${log_path}"
    --source "${source}"
    --output "${AUTONOMOUS_AUTO_HEAL_RESULT_PATH}"
  )
  if [ "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}" = "prompt" ] || \
    [ "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}" = "ask" ] || \
    [ "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}" = "interactive" ]; then
    echo "[HEAL] HITL modu etkileşimli; scripts.auto_heal terminalden onay isteyecek."
  else
    cmd+=(--hitl-approve "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}")
  fi
  "${cmd[@]}"
}

run_static_analysis_heal_phases() {
  local mypy_exit=0
  local bandit_exit=0

  if ! is_truthy_flag "${AUTONOMOUS_RUN_LINTER_PHASES}"; then
    echo "[LINTER] AUTONOMOUS_LOOP_RUN_LINTER_PHASES=${AUTONOMOUS_RUN_LINTER_PHASES}; mypy/bandit fazları atlandı."
    return 0
  fi

  mkdir -p "${AUTONOMOUS_REPORTS_DIR}"

  echo "[LINTER] Running Mypy Type Check..."
  uv run mypy . > "${AUTONOMOUS_MYPY_REPORT}" 2>&1
  mypy_exit=$?
  if [ "${mypy_exit}" -ne 0 ]; then
    echo "[LINTER] Mypy failed (exit=${mypy_exit}). Triggering Auto-Heal for type-check context..."
    cp "${AUTONOMOUS_MYPY_REPORT}" "${AUTONOMOUS_TEST_FAILURE_LOG}"
    run_auto_heal_for_test_failure mypy || true
  else
    echo "[LINTER] Mypy passed."
  fi

  echo "[SECURITY] Running Bandit Security Scan..."
  uv run bandit -r . -c pyproject.toml -f json -o "${AUTONOMOUS_BANDIT_REPORT}"
  bandit_exit=$?
  if [ "${bandit_exit}" -ne 0 ]; then
    echo "[SECURITY] Bandit found warnings (exit=${bandit_exit}). Triggering Auto-Heal for security context..."
    cp "${AUTONOMOUS_BANDIT_REPORT}" "${AUTONOMOUS_TEST_FAILURE_LOG}"
    run_auto_heal_for_test_failure bandit || true
  else
    echo "[SECURITY] Bandit passed."
  fi
}

run_preflight_quality_gate() {
  local test_exit
  local gate_exit
  local upload_exit
  local current_percent
  local coverage_status

  echo ""
  echo "========== Ön Kontrol =========="
  echo "[PREFLIGHT LINTER] Mypy/Bandit fazları çalıştırılıyor (AUTONOMOUS_LOOP_RUN_LINTER_PHASES=${AUTONOMOUS_RUN_LINTER_PHASES})."
  run_static_analysis_heal_phases
  if [ -f "${AUTONOMOUS_COVERAGE_JSON}" ] && [ -f "${AUTONOMOUS_COVERAGE_XML}" ]; then
    echo "[PREFLIGHT 1/3] Mevcut coverage artefaktları bulundu: ${AUTONOMOUS_COVERAGE_JSON}, ${AUTONOMOUS_COVERAGE_XML}"
    current_percent="$(read_coverage_percent "${AUTONOMOUS_COVERAGE_JSON}" "${AUTONOMOUS_COVERAGE_TARGET_FILE}")"
    coverage_status=$?
    if [ "${coverage_status}" -eq 0 ] && coverage_target_reached "${current_percent}" "${AUTONOMOUS_COVERAGE_TARGET}"; then
      echo "[PREFLIGHT 2/3] Mevcut coverage otonom iyileştirme hedefini sağlıyor: %${current_percent} >= %${AUTONOMOUS_COVERAGE_TARGET}."
    else
      echo "[PREFLIGHT 2/3] Mevcut coverage otonom iyileştirme hedefinin altında veya okunamadı; bu durum local/CI gate başarısızlığı anlamına gelmez."
      echo "[PREFLIGHT 2/3] AUTONOMOUS_LOOP_OPERATION_PROFILE=${AUTONOMOUS_OPERATION_PROFILE}; CoverageAgent testleri çalıştırmadan önce denenecek."
      run_coverage_agent
      coverage_agent_exit=$?
      if [ "${coverage_agent_exit}" -eq 3 ]; then
        echo "[PREFLIGHT] CoverageAgent status=blocked_by_reviewer; manuel test yazılması gerekiyor. Otonom döngü başlatılmayacak."
        exit 1
      fi
    fi
  else
    echo "[PREFLIGHT 1/3] Coverage artefaktı eksik (${AUTONOMOUS_COVERAGE_JSON}/${AUTONOMOUS_COVERAGE_XML}); önce ./run_tests.sh ile üretilecek."
  fi

  echo "[PREFLIGHT 2/3] Test: ./run_tests.sh (tam kalite kapısı; statik analiz dahil)"
  run_full_quality_tests
  test_exit=$?

  echo "[PREFLIGHT 3/3] Kontrol: Test çıkış kodu = $test_exit; local gate = %${LOCAL_COVERAGE_GATE}; otonom hedef = %${AUTONOMOUS_COVERAGE_TARGET}"
  check_autonomous_quality_gate "$test_exit"
  gate_exit=$?

  if [ "$gate_exit" -ne 0 ]; then
    echo "[PREFLIGHT] Otonom iyileştirme hedefi veya test adımı sağlanmadı (durum: $gate_exit); ${ITERATIONS} döngülük otonom onarım akışı başlatılacak."
    return 1
  fi

  echo "[PREFLIGHT] Kod zaten sağlıklı; gereksiz otonom onarım döngüsü atlanıyor."
  echo "[PREFLIGHT] Upload: uv run python github_upload.py"
  run_github_upload
  upload_exit=$?
  if [ "$upload_exit" -ne 0 ]; then
    echo "[HATA] Ön kontrol sonrası upload adımı başarısız oldu (exit code: $upload_exit)."
    exit "$upload_exit"
  fi

  echo "[BİTTİ] Ön kontrol başarıyla geçti; upload tamamlandı, otonom döngü çalıştırılmadı."
  exit 0
}


run_preflight_quality_gate

for ((i=1; i<=ITERATIONS; i++)); do
  echo ""
  echo "========== Döngü $i/$ITERATIONS =========="

  echo "[1/3] Upload: uv run python github_upload.py"
  run_github_upload
  upload_exit=$?
  if [ "$upload_exit" -ne 0 ]; then
    echo "[HATA] Upload adımı başarısız oldu (exit code: $upload_exit). Döngü durduruluyor."
    exit "$upload_exit"
  fi

  echo "[2/3] Test: RUN_STATIC_ANALYSIS=${AUTONOMOUS_TEST_STATIC_ANALYSIS} AUTO_HEAL_ON_FAILURE=0 ./run_tests.sh"
  run_autonomous_quality_tests
  test_exit=$?

  echo "[3/3] Kontrol: Test çıkış kodu = $test_exit; local gate = %${LOCAL_COVERAGE_GATE}; otonom hedef = %${AUTONOMOUS_COVERAGE_TARGET}"
  check_autonomous_quality_gate "$test_exit"
  gate_exit=$?
  if [ "$gate_exit" -ne 0 ]; then
    echo "[UYARI] Otonom iyileştirme hedefi veya test adımı sağlanmadı (durum: $gate_exit). Otonom düzeltme/coverage iyileştirme döngüsü başlatılıyor..."

    healed=0
    for ((retry=1; retry<=AUTO_REMEDIATION_MAX_RETRIES; retry++)); do
      if [ "$test_exit" -ne 0 ]; then
        echo "[HEAL] Deneme $retry/$AUTO_REMEDIATION_MAX_RETRIES: test kırılması için self-heal"
        run_auto_heal_for_test_failure pytest || true
      fi

      echo "[HEAL] Deneme $retry/$AUTO_REMEDIATION_MAX_RETRIES: coverage analizi ve otonom öneri"
      run_coverage_agent
      coverage_agent_exit=$?
      if [ "${coverage_agent_exit}" -eq 3 ]; then
        echo "[HEAL] CoverageAgent status=blocked_by_reviewer; aynı hedef dosya aynı red tipiyle tekrarlandı."
        echo "[HEAL] Manuel test yazılması gerekiyor; gereksiz remediation tekrarları durduruluyor."
        exit 1
      fi
      if [ -f "${AUTONOMOUS_COVERAGE_XML}" ]; then
        uv run python scripts/coverage_hotspots.py --xml "${AUTONOMOUS_COVERAGE_XML}" --top 20 --root . || true
      fi

      echo "[HEAL] Testler tekrar çalıştırılıyor (statik analiz/mypy tekrarı yok)..."
      run_autonomous_quality_tests
      test_exit=$?
      run_static_analysis_heal_phases
      check_autonomous_quality_gate "$test_exit"
      gate_exit=$?
      if [ "$gate_exit" -eq 0 ]; then
        healed=1
        echo "[OK] Otonom düzeltme/coverage iyileştirme başarılı oldu."
        break
      fi
    done

    if [ "$healed" -ne 1 ]; then
      if [ "$test_exit" -ne 0 ]; then
        final_exit="$test_exit"
      else
        final_exit=1
      fi
      echo "[HATA] Otonom düzeltme denemeleri tükendi. Döngü durduruluyor (test exit: $test_exit, gate: $gate_exit)."
      exit "$final_exit"
    fi
  fi

  echo "[OK] Döngü $i başarıyla tamamlandı."
done

echo ""
echo "[BİTTİ] Upload -> Test -> Kontrol döngüsü $ITERATIONS kez başarıyla tamamlandı."
