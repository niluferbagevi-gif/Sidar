#!/usr/bin/env bash

# Helper functions sourced by run_tests.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

read_preferred_python_version() {
  if [ -n "${SIDAR_PYTHON_VERSION:-}" ]; then
    printf '%s' "${SIDAR_PYTHON_VERSION}"
    return 0
  fi
  if [ -f "${SCRIPT_DIR}/.python-version" ]; then
    head -n 1 "${SCRIPT_DIR}/.python-version" | tr -d '[:space:]'
    return 0
  fi
  printf '3.11'
}
assert_venv_writable() {
  if [ ! -d "${PROJECT_VENV_DIR}" ]; then
    return 0
  fi

  local owner
  owner="$(stat -c %U "${PROJECT_VENV_DIR}" 2>/dev/null || true)"
  if [ -n "${owner}" ] && [ "${owner}" != "${USER:-$(id -un)}" ]; then
    echo "❌ .venv sahipliği mevcut kullanıcıyla uyuşmuyor (owner=${owner}, user=${USER:-$(id -un)})."
    echo "   Düzeltme: sudo chown -R ${USER:-$(id -un)}:${USER:-$(id -un)} \"${PROJECT_VENV_DIR}\""
    return 1
  fi

  if [ ! -w "${PROJECT_VENV_DIR}" ]; then
    echo "❌ .venv dizini yazılabilir değil: ${PROJECT_VENV_DIR}"
    echo "   Düzeltme: sudo chown -R ${USER:-$(id -un)}:${USER:-$(id -un)} \"${PROJECT_VENV_DIR}\""
    return 1
  fi

  return 0
}
ensure_project_venv() {
  export UV_PROJECT_ENVIRONMENT="${PROJECT_VENV_ENV}"

  if ! command -v uv >/dev/null 2>&1; then
    return 0
  fi

  local preferred_python
  preferred_python="$(read_preferred_python_version)"
  local recreate_venv=0

  if [ ! -x "${PROJECT_VENV_DIR}/bin/python" ]; then
    recreate_venv=1
  elif ! "${PROJECT_VENV_DIR}/bin/python" - <<'PY_VENV_CHECK' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)
PY_VENV_CHECK
  then
    recreate_venv=1
  elif [ -n "${preferred_python}" ] && ! "${PROJECT_VENV_DIR}/bin/python" - "${preferred_python}" <<'PY_VENV_VERSION' >/dev/null 2>&1
import sys

preferred = sys.argv[1].strip()
if not preferred:
    raise SystemExit(0)
major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
# Only enforce major.minor pins such as 3.11; patch-level pins remain uv's job.
parts = preferred.split(".")
if len(parts) >= 2 and all(part.isdigit() for part in parts[:2]):
    raise SystemExit(0 if major_minor == ".".join(parts[:2]) else 1)
raise SystemExit(0)
PY_VENV_VERSION
  then
    recreate_venv=1
  fi

  if [ "${recreate_venv}" -eq 1 ]; then
    echo "ℹ️ Proje sanal ortamı hazırlanıyor: uv venv --python ${preferred_python} ${PROJECT_VENV_ENV}"
    rm -rf "${PROJECT_VENV_DIR}"
    uv venv --python "${preferred_python}" "${PROJECT_VENV_ENV}"
  fi

  if [ -f "${PROJECT_VENV_DIR}/bin/activate" ]; then
    # shellcheck disable=SC1090
    source "${PROJECT_VENV_DIR}/bin/activate"
  fi
}
report_git_diff_state() {
  local label="$1"

  if ! command -v git >/dev/null 2>&1 || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ℹ️ ${label}: git çalışma ağacı durumu raporlanamadı (git repo değil)."
    return 0
  fi

  if git diff --exit-code --quiet; then
    echo "✅ ${label}: git diff --exit-code temiz."
  else
    echo "⚠️ ${label}: git diff --exit-code değişiklik görüyor."
    git diff --stat || true
  fi
}
run_precommit_autofix() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "⚠️ 'uv' bulunamadı; Ruff kalite kapısı atlanıyor."
    return 0
  fi

  if [ "${RUFF_AUTOFIX:-0}" != "1" ]; then
    echo "🔍 Ruff kalite kapısı: uv run ruff check ."
    if ! uv run ruff check .; then
      echo "❌ Ruff lint kontrolü başarısız. Düzeltmek için: RUFF_AUTOFIX=1 bash run_tests.sh --stage all"
      return 1
    fi
    echo "🔍 Ruff format kapısı: uv run ruff format --check ."
    if ! uv run ruff format --check .; then
      echo "❌ Ruff format kontrolü başarısız. Düzeltmek için: RUFF_AUTOFIX=1 bash run_tests.sh --stage all"
      return 1
    fi
    return 0
  fi

  report_git_diff_state "RUFF_AUTOFIX başlangıç durumu"

  local ruff_autofix_cmd=(uv run ruff check --fix)
  local unsafe_fixes="${RUFF_AUTOFIX_UNSAFE:-0}"
  local unsafe_rules="${RUFF_AUTOFIX_UNSAFE_RULES:-I,UP}"
  if [ "${unsafe_fixes}" = "1" ]; then
    if [ -z "${unsafe_rules}" ]; then
      echo "⚠️ RUFF_AUTOFIX_UNSAFE=1 ancak RUFF_AUTOFIX_UNSAFE_RULES boş; unsafe fixler atlanıyor."
    else
      ruff_autofix_cmd+=(--unsafe-fixes --select "${unsafe_rules}")
      echo "⚠️ Ruff unsafe fixleri sınırlı selector listesiyle çalışacak: ${unsafe_rules}"
    fi
  fi
  ruff_autofix_cmd+=(.)

  echo "🧹 Ruff autofix opt-in: ${ruff_autofix_cmd[*]}"
  if ! "${ruff_autofix_cmd[@]}"; then
    echo "❌ Ruff autofix sonrası lint kontrolleri başarısız. Testler durduruldu."
    report_git_diff_state "RUFF_AUTOFIX bitiş durumu"
    return 1
  fi
  echo "🧹 Ruff format opt-in: uv run ruff format ."
  if ! uv run ruff format .; then
    echo "❌ Ruff format autofix başarısız. Testler durduruldu."
    report_git_diff_state "RUFF_AUTOFIX bitiş durumu"
    return 1
  fi

  report_git_diff_state "RUFF_AUTOFIX bitiş durumu"
}
check_python_version() {
  if ! python - <<'PY'
import sys

major, minor = sys.version_info[:2]
if (major, minor) < (3, 11) or (major, minor) >= (3, 12):
    raise SystemExit(1)
PY
  then
    local current_python
    current_python="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
    echo "❌ Desteklenmeyen Python sürümü: ${current_python}"
    echo "ℹ️ Bu proje için desteklenen aralık: >=3.11, <3.12 (yalnızca Python 3.11)."
    echo "ℹ️ Not: Uyumlu sürüm kullanılmadığında SQLAlchemy gibi bağımlılıklar yüklenemez ve ModuleNotFoundError alınabilir."
    exit 1
  fi
}
generate_test_secret_value() {
  python - <<'PY_SECRET' 2>/dev/null || openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n='
import secrets
print(secrets.token_urlsafe(32))
PY_SECRET
}
render_generated_secret_sentinels() {
  local target="$1"
  local generated_password=""

  if [ ! -f "${target}" ] || ! grep -q '^POSTGRES_PASSWORD=__GENERATE__$' "${target}"; then
    return 0
  fi

  generated_password="$(generate_test_secret_value)"
  if [ -z "${generated_password}" ]; then
    echo "⚠️ POSTGRES_PASSWORD=__GENERATE__ için parola üretilemedi; '${target}' dosyasını elle güncelleyin."
    return 1
  fi

  python - "${target}" "${generated_password}" <<'PY_RENDER'
from pathlib import Path
import sys

path = Path(sys.argv[1])
password = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
path.write_text(
    "\n".join(
        f"POSTGRES_PASSWORD={password}" if line == "POSTGRES_PASSWORD=__GENERATE__" else line
        for line in lines
    )
    + "\n",
    encoding="utf-8",
)
PY_RENDER
  echo "✅ '${target}' içindeki POSTGRES_PASSWORD=__GENERATE__ güçlü lokal parola ile değiştirildi."
}
ensure_test_dotenv() {
  local target="${DOTENV_FILE:-.env.test}"
  local template=".env.test.example"

  if [ -f "${target}" ]; then
    return 0
  fi

  if [ ! -f "${template}" ]; then
    echo "⚠️ '${target}' bulunamadı ve şablon '${template}' da mevcut değil; varsayılan değerlerle devam edilecek."
    return 0
  fi

  echo "ℹ️ '${target}' bulunamadı; '${template}' şablonundan otomatik oluşturuluyor."
  if install -m 600 "${template}" "${target}"; then
    render_generated_secret_sentinels "${target}" || true
    echo "✅ '${target}' oluşturuldu. Lokal ihtiyaçlarınıza göre düzenleyebilirsiniz (sırlar yalnızca bu dosyada tutulur)."
  else
    echo "⚠️ '${target}' otomatik oluşturulamadı; ortam değişkenleri olmadan devam edilecek."
  fi
}
cleanup_zone_identifier_artifacts() {
  if [ "${CLEAN_ZONE_IDENTIFIER_ARTIFACTS:-1}" != "1" ]; then
    echo "ℹ️ Zone.Identifier temizliği devre dışı (CLEAN_ZONE_IDENTIFIER_ARTIFACTS=${CLEAN_ZONE_IDENTIFIER_ARTIFACTS:-0})."
    return 0
  fi

  echo "🧹 Windows Zone.Identifier yan dosyaları temizleniyor..."
  if ! uv run python scripts/cleanup_zone_identifier.py --root .; then
    echo "❌ Zone.Identifier temizliği başarısız oldu."
    return 1
  fi
}
validate_coverage_ratchet_state() {
  if [ ! -f "${COVERAGE_RATCHET_STATE_FILE}" ]; then
    echo "❌ Coverage ratchet state dosyası bulunamadı: ${COVERAGE_RATCHET_STATE_FILE}" >&2
    echo "   Bu dosya repo'ya commit edilmeli ve .gitignore kapsamına alınmamalıdır." >&2
    echo "   Baseline kaybı, coverage gate'in %0'dan yeniden başlamasına neden olabilir." >&2
    return 1
  fi

  python - "${COVERAGE_RATCHET_STATE_FILE}" "${COVERAGE_RATCHET_MIN_EXISTING_GATE}" <<'PY_RATCHET_STATE'
from pathlib import Path
import sys
import tomllib

state_path = Path(sys.argv[1])
min_gate = float(sys.argv[2])
data = tomllib.loads(state_path.read_text(encoding="utf-8"))
try:
    raw_gate = data["tool"]["coverage"]["report"]["fail_under"]
except KeyError as exc:
    raise SystemExit(f"{state_path} içinde [tool.coverage.report] fail_under bulunamadı") from exc
try:
    gate = float(raw_gate)
except (TypeError, ValueError) as exc:
    raise SystemExit(f"{state_path} içindeki fail_under sayısal değil") from exc
if gate < min_gate:
    raise SystemExit(
        f"{state_path} fail_under={gate:g}; beklenen minimum {min_gate:g}. "
        "Coverage ratchet baseline sıfırlanmış olabilir."
    )
print(f"{gate:g}")
PY_RATCHET_STATE
}
