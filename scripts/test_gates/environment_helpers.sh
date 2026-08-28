#!/usr/bin/env bash

# Helper functions sourced by run_tests.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

validate_test_gate_environment_schema() {
  echo "🔤 Test kalite-gate environment schema doğrulanıyor..."
  uv run --frozen python -m scripts.test_gates.env_schema
}

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
# Bare `python` her sistemde garanti değildir (birçok modern Ubuntu/WSL
# kurulumunda yalnızca `python3` var) ve bu dosyadaki fonksiyonlar
# ensure_project_venv()'den *önce* ya da sonra (uv PATH'te değilse venv hiç
# aktive edilmeden ensure_project_venv erken döner, bkz. satır ~46-48)
# çağrılabilir. Aynı desen scripts/install_modules/phases/12_alembic.sh
# ::resolve_alembic_python ile paylaşılır: önce proje venv'inin python'ı,
# sonra `python3`, sonra `python` tercih edilir; hiçbiri yoksa açıkça
# başarısız olunur (sessizce "command not found" ile çökmek yerine).
resolve_test_gate_python() {
  if [ -n "${PROJECT_VENV_DIR:-}" ] && [ -x "${PROJECT_VENV_DIR}/bin/python" ]; then
    printf '%s' "${PROJECT_VENV_DIR}/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  return 1
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
# `uv run --frozen ruff ...` hiçbir sync/install yapmaz, yalnızca mevcut
# .venv'i olduğu gibi kullanır. run_tests.sh bu kalite kapısını en baştan
# (ensure_project_venv'den hemen sonra, backend test fazının kendi
# ensure_runtime_dependencies self-heal'i devreye girmeden çok önce) çalıştırır.
# "Tam Docker" kurulum modunda host'ta hiç `uv sync` çalışmaz; kurulum yalnızca
# Alembic için `uv sync --frozen --extra postgres` çalıştırmış olabilir — bu
# durumda ruff (bir "dev" bağımlılığı) henüz kurulu değildir ve doğrudan
# çağrı "No such file or directory" ile başarısız olur. resolve_alembic_python
# (scripts/install_modules/phases/12_alembic.sh) ile aynı desen: eksikse
# hedefe özel bir profille tamamla ve tekrar dene. `--extra dev` yeterlidir
# (ruff = "dev" bağımlılık grubunda, bkz. pyproject.toml) ve --all-extras'ın
# tetikleyeceği PortAudio/ses gibi sistem bağımlılığı gerektiren ekstralara
# ihtiyaç duymaz.
ensure_ruff_available() {
  if uv run --frozen ruff --version >/dev/null 2>&1; then
    return 0
  fi

  echo "⚠️ Ruff bulunamadı (ör. 'Tam Docker' kurulum modunda .venv hiç senkronize edilmemiş olabilir, ya da yalnızca dar bir extra profille -- Alembic için 'postgres' gibi -- senkronize edilmiştir)."
  echo "ℹ️ Ruff için 'uv sync --frozen --extra dev' ile tamamlanıyor..."
  if ! uv sync --frozen --extra dev; then
    echo "❌ Ruff'ın otomatik kurulumu başarısız oldu. Manuel: uv sync --frozen --extra dev (veya --all-extras)"
    return 1
  fi

  if ! uv run --frozen ruff --version >/dev/null 2>&1; then
    echo "❌ Ruff doğrulaması başarısız: senkronizasyon sonrası hâlâ bulunamadı."
    return 1
  fi

  echo "✅ Ruff hazır; kalite kapısı devam ediyor."
}

run_ruff_quality_gate() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "⚠️ 'uv' bulunamadı; Ruff kalite kapısı atlanıyor."
    return 0
  fi

  if ! ensure_ruff_available; then
    return 1
  fi

  echo "🔍 Ruff kalite kapısı: uv run --frozen ruff check ."
  if ! uv run --frozen ruff check .; then
    echo "❌ Ruff lint kontrolü başarısız. Düzeltmek için: RUFF_AUTOFIX=1 bash run_tests.sh --stage all"
    return 1
  fi
  echo "🔍 Ruff format kapısı: uv run --frozen ruff format --check ."
  if ! uv run --frozen ruff format --check .; then
    echo "❌ Ruff format kontrolü başarısız. Düzeltmek için: RUFF_AUTOFIX=1 bash run_tests.sh --stage all"
    return 1
  fi
}

run_ruff_autofix() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "⚠️ 'uv' bulunamadı; Ruff autofix çalıştırılamıyor."
    return 0
  fi

  if ! ensure_ruff_available; then
    return 1
  fi

  report_git_diff_state "RUFF_AUTOFIX başlangıç durumu"

  local ruff_autofix_cmd=(uv run --frozen ruff check --fix)
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
  echo "🧹 Ruff format opt-in: uv run --frozen ruff format ."
  if ! uv run --frozen ruff format .; then
    echo "❌ Ruff format autofix başarısız. Testler durduruldu."
    report_git_diff_state "RUFF_AUTOFIX bitiş durumu"
    return 1
  fi

  report_git_diff_state "RUFF_AUTOFIX bitiş durumu"
}
check_python_version() {
  local python_bin
  if ! python_bin="$(resolve_test_gate_python)"; then
    echo "❌ Python bulunamadı: ne \${PROJECT_VENV_DIR}/bin/python, ne 'python3', ne 'python' PATH'te mevcut."
    echo "ℹ️ Kontrol: 'command -v uv' boş dönüyorsa 'uv' bu terminal oturumunun PATH'inde değildir."
    echo "   install_sidar.sh doğrudan çalıştırıldıysa ('source' edilmeden) PATH güncellemesi yalnızca o kurulum"
    echo "   alt-process'ine özeldi ve mevcut terminale geri yansımaz."
    echo "ℹ️ Çözüm: terminali kapatıp yeniden açın (veya 'source ~/.bashrc' / 'source ~/.zshrc' çalıştırın),"
    echo "   ardından bu komutu tekrar deneyin."
    exit 1
  fi

  if ! "${python_bin}" - <<'PY'
import sys

major, minor = sys.version_info[:2]
if (major, minor) < (3, 11) or (major, minor) >= (3, 12):
    raise SystemExit(1)
PY
  then
    local current_python
    current_python="$("${python_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
    echo "❌ Desteklenmeyen Python sürümü: ${current_python}"
    echo "ℹ️ Bu proje için desteklenen aralık: >=3.11, <3.12 (yalnızca Python 3.11)."
    echo "ℹ️ Not: Uyumlu sürüm kullanılmadığında SQLAlchemy gibi bağımlılıklar yüklenemez ve ModuleNotFoundError alınabilir."
    exit 1
  fi
}
generate_test_secret_value() {
  local python_bin
  python_bin="$(resolve_test_gate_python)" || python_bin=""
  if [ -n "${python_bin}" ] && "${python_bin}" - <<'PY_SECRET' 2>/dev/null
import secrets
print(secrets.token_urlsafe(32))
PY_SECRET
  then
    return 0
  fi
  openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n='
}
render_generated_secret_sentinels() {
  local target="$1"
  local generated_password=""
  local reused_process_env_password=0

  if [ ! -f "${target}" ] || ! grep -q '^POSTGRES_PASSWORD=__GENERATE__$' "${target}"; then
    return 0
  fi

  # Process env is the single source of truth when it already defines
  # POSTGRES_PASSWORD (e.g. a CI job's service-container credentials, or a
  # developer's shell exporting it before a fresh `bash run_tests.sh`).
  # Generating an unrelated random secret here instead would desync .env.test
  # from the actual PostgreSQL role's password — and when the caller also
  # skips the ALTER ROLE reconciliation step (AUTO_PREPARE_TEST_DB=0, as CI's
  # "Base quality gates" job does because it prepares the test database
  # itself), nothing ever applies the generated password to the live server,
  # so every DB connection using .env.test's DATABASE_URL/POSTGRES_PASSWORD
  # fails auth. Reuse the process env value instead of generating a
  # disconnected one whenever it's available.
  if [ -n "${POSTGRES_PASSWORD:-}" ]; then
    generated_password="${POSTGRES_PASSWORD}"
    reused_process_env_password=1
  else
    generated_password="$(generate_test_secret_value)"
  fi
  if [ -z "${generated_password}" ]; then
    echo "⚠️ POSTGRES_PASSWORD=__GENERATE__ için parola üretilemedi; '${target}' dosyasını elle güncelleyin."
    return 1
  fi

  local python_bin
  if ! python_bin="$(resolve_test_gate_python)"; then
    echo "⚠️ Python bulunamadı (ne python3 ne python PATH'te); '${target}' içindeki POSTGRES_PASSWORD=__GENERATE__ satırı güncellenemedi. Elle düzenleyin."
    return 1
  fi

  "${python_bin}" - "${target}" "${generated_password}" <<'PY_RENDER'
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
  if [ "${reused_process_env_password}" -eq 1 ]; then
    echo "✅ '${target}' içindeki POSTGRES_PASSWORD=__GENERATE__ değeri mevcut process env POSTGRES_PASSWORD ile senkronize edildi."
  else
    echo "✅ '${target}' içindeki POSTGRES_PASSWORD=__GENERATE__ güçlü lokal parola ile değiştirildi."
  fi
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

  local python_bin
  if ! python_bin="$(resolve_test_gate_python)"; then
    echo "❌ Python bulunamadı (ne python3 ne python PATH'te); coverage ratchet state doğrulanamıyor." >&2
    return 1
  fi

  "${python_bin}" - "${COVERAGE_RATCHET_STATE_FILE}" "${COVERAGE_RATCHET_MIN_EXISTING_GATE}" <<'PY_RATCHET_STATE'
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
