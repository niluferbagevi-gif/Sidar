#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

DEFAULT_COVERAGE_FAIL_UNDER="$(python - <<'PY'
from configparser import ConfigParser
from pathlib import Path

cfg = ConfigParser()
cfg.read(Path(".coveragerc"))
print(cfg.get("report", "fail_under", fallback="90"))
PY
)"

COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-${DEFAULT_COVERAGE_FAIL_UNDER}}"
AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"

PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
RUN_BENCHMARKS="${RUN_BENCHMARKS:-auto}"
PERFORMANCE_TEST_DIR="${PERFORMANCE_TEST_DIR:-tests/performance}"

BACKEND_EXIT_CODE=0
FRONTEND_EXIT_CODE=0
BENCHMARK_EXIT_CODE=0

if ! [[ "${COVERAGE_FAIL_UNDER}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "⚠️ Geçersiz COVERAGE_FAIL_UNDER değeri: '${COVERAGE_FAIL_UNDER}'. Varsayılan 90 kullanılacak."
  COVERAGE_FAIL_UNDER="90"
fi

echo "ℹ️ Coverage quality gate eşiği: ${COVERAGE_FAIL_UNDER} (pytest --cov-fail-under ile .coveragerc fail_under değerini override eder)"

# 0) Önceki test artefaktlarını temizle
rm -rf .coverage .coverage.* htmlcov web_ui_react/coverage

open_artifact() {
  local target="$1"
  if [ ! -e "$target" ] || [ "${AUTO_OPEN_ARTIFACTS}" != "1" ]; then
    return 0
  fi

  # WSL2 öncelikli kontroller
  if [ -n "${WSL_DISTRO_NAME:-}" ] && command -v wslview >/dev/null 2>&1; then
    wslview "$target" >/dev/null 2>&1 &
  elif [ -n "${WSL_DISTRO_NAME:-}" ] && command -v explorer.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    explorer.exe "$(wslpath -w "$target")" >/dev/null 2>&1 &
  # Standart Linux/macOS fallback'leri
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$target" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "$target" >/dev/null 2>&1 &
  elif command -v start >/dev/null 2>&1; then
    start "" "$target" >/dev/null 2>&1 &
  else
    echo "ℹ️ Otomatik açma için desteklenen komut bulunamadı: $target"
  fi
}

run_pytest_coverage_report() {
  echo "📊 Pytest + Coverage + Quality Gate çalıştırılıyor..."
  if ! python - <<'PY' >/dev/null 2>&1
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
opt_deps = data.get("project", {}).get("optional-dependencies", {})
deps = opt_deps.get("test") or opt_deps.get("dev") or []
deps_l = [d.lower() for d in deps]
assert any("pytest-cov" in d for d in deps_l), "pytest-cov"
assert any("pytest-xdist" in d for d in deps_l), "pytest-xdist"
PY
  then
    echo "❌ pyproject.toml test bağımlılıklarında pytest-cov/pytest-xdist doğrulaması başarısız."
    BACKEND_EXIT_CODE=1
    return
  fi

  if ! python - <<'PY' >/dev/null 2>&1
import coverage  # noqa: F401
import pytest_cov  # noqa: F401
import pytest_asyncio  # noqa: F401
PY
  then
    echo "⚠️ Test ve coverage araçları (pytest-asyncio vb.) eksik. Proje mimarisine göre otomatik kuruluyor..."

    if command -v uv >/dev/null 2>&1; then
      echo "ℹ️ 'uv' tespit edildi, dev bağımlılıkları senkronize ediliyor..."
      uv sync --extra dev
    else
      echo "ℹ️ 'uv' bulunamadı, 'pip' ile dev bağımlılıkları kuruluyor..."
      pip install -e ".[dev]"
    fi

    if ! python -c "import pytest_asyncio" >/dev/null 2>&1; then
      echo "❌ Geliştirici bağımlılıklarının otomatik kurulumu başarısız oldu."
      BACKEND_EXIT_CODE=1
      return
    fi
  fi

  # -c pyproject.toml ile marker/addopts ayarlarının kök dizinden bağımsız şekilde
  # her çağrıda kesin yüklenmesi garanti edilir.
  # Coverage rapor formatları pyproject.toml addopts üzerinden merkezi yönetilir.
  # Sadece fail-under eşiği gerektiğinde CLI'dan override edilir.
  local pytest_cmd=(pytest -c pyproject.toml --cov-fail-under="${COVERAGE_FAIL_UNDER}")
  local pytest_targets=("tests")

  if [ "${ENABLE_GPU_TESTS:-1}" != "1" ]; then
    echo "ℹ️ GPU testleri atlanıyor (Çalıştırmak için: ENABLE_GPU_TESTS=1 bash run_tests.sh)"
    pytest_cmd+=(-m "not gpu")
  else
    if ! command -v nvidia-smi >/dev/null 2>&1 && ! command -v nvidia-smi.exe >/dev/null 2>&1; then
      echo "⚠️ ENABLE_GPU_TESTS=1 verildi ancak nvidia-smi bulunamadı. GPU testleri güvenli fallback ile atlanıyor."
      pytest_cmd+=(-m "not gpu")
    else
      echo "🔥 GPU testleri de dahil ediliyor!"
      if [ "${RUN_GPU_STRESS:-0}" != "1" ]; then
        export RUN_GPU_STRESS=1
        echo "ℹ️ GPU tespit edildiği için testlerde RUN_GPU_STRESS=1 otomatik etkinleştirildi."
      fi
    fi
  fi

  if python -c "import xdist" >/dev/null 2>&1; then
    pytest_cmd+=(-n "${PYTEST_WORKERS}")
  fi

  # Benchmark ölçümlerinin doğruluğu için performans testleri bu aşamada
  # özellikle hariç tutulur ve aşağıda tek çekirdekli ayrı fazda çalıştırılır.
  pytest_cmd+=(--ignore=tests/performance)
  if [ "${PERFORMANCE_TEST_DIR}" != "tests/performance" ] && [ -d "${PERFORMANCE_TEST_DIR}" ]; then
    pytest_cmd+=(--ignore="${PERFORMANCE_TEST_DIR}")
  fi

  pytest_cmd+=("${pytest_targets[@]}")

  echo "➡️ Çalıştırılan komut: ${pytest_cmd[*]}"

  "${pytest_cmd[@]}"
  BACKEND_EXIT_CODE=$?

  # xdist altında bazı koşullarda sadece .coverage.* shard'ları kalabilir.
  # Önce bunları birleştirmeyi dener, başarısızsa quality gate'i fail eder.
  if [ ! -f ".coverage" ] && [ "${BACKEND_EXIT_CODE}" -eq 0 ]; then
    if compgen -G ".coverage.*" > /dev/null; then
      echo "ℹ️ .coverage bulunamadı fakat .coverage.* shard dosyaları tespit edildi. coverage combine deneniyor..."
      if python -m coverage combine && python -m coverage html -d htmlcov && python -m coverage xml -o coverage.xml; then
        echo "✅ coverage combine başarılı; raporlar yeniden üretildi."
      else
        echo "❌ coverage combine başarısız oldu. Paralel testlerde coverage verisi toparlanamadı."
        BACKEND_EXIT_CODE=1
      fi
    else
      echo "⚠️ Uyarı: Testler başarılı görünüyor ancak .coverage dosyası üretilemedi. xdist worker'ları crash olmuş olabilir."
      BACKEND_EXIT_CODE=1
    fi
  fi

  if [ -f "htmlcov/index.html" ]; then
    echo "✅ Coverage HTML raporu oluşturuldu: htmlcov/index.html"
    open_artifact "htmlcov/index.html"
  else
    echo "⚠️ Coverage raporu oluşturulamadı: htmlcov/index.html bulunamadı."
  fi
}

# 1) Backend testleri + coverage (pyproject addopts ile) + quality gate
run_pytest_coverage_report

# 2) Kritik yol performans baseline testleri (pytest-benchmark)
if [ "${RUN_BENCHMARKS}" = "0" ]; then
  echo "ℹ️ Benchmark testleri RUN_BENCHMARKS=0 ile atlandı."
elif [ -d "${PERFORMANCE_TEST_DIR}" ]; then
  echo "📊 Aşama 2: Performans benchmark testleri tek çekirdek üzerinde koşturuluyor..."
  python -m pytest -c pyproject.toml -v "${PERFORMANCE_TEST_DIR}" -n 0 --no-cov
  BENCHMARK_EXIT_CODE=$?
else
  echo "⚠️ Benchmark testi atlandı: ${PERFORMANCE_TEST_DIR} bulunamadı."
  if [ "${RUN_BENCHMARKS}" = "required" ]; then
    echo "❌ RUN_BENCHMARKS=required iken benchmark dizini bulunamadı."
    BENCHMARK_EXIT_CODE=1
  fi
fi

# 3) Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
if [ -d "web_ui_react" ] && [ -f "web_ui_react/package.json" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    FRONTEND_EXIT_CODE=1
  else
    echo "🚀 Frontend (React) Testleri Başlıyor..."
    if pushd web_ui_react > /dev/null; then
      # Yerel ortamda yavaşlığı önlemek için CI değişkenine göre davran.
      if [ "${CI:-0}" = "true" ] || [ "${CI:-0}" = "1" ]; then
        echo "ℹ️ CI ortamı tespit edildi, 'npm ci' çalıştırılıyor..."
        npm ci
      else
        echo "ℹ️ Yerel ortam tespit edildi, 'npm install' çalıştırılıyor..."
        npm install
      fi
      local_npm_ci_exit=$?
      if [ "${local_npm_ci_exit}" -ne 0 ]; then
        FRONTEND_EXIT_CODE=${local_npm_ci_exit}
      else
        npm run test:coverage
        FRONTEND_EXIT_CODE=$?
      fi

      for report in coverage/lcov-report/index.html coverage/index.html; do
        open_artifact "$PWD/$report"
      done

      popd > /dev/null || true
    else
      FRONTEND_EXIT_CODE=1
    fi
  fi
elif [ -d "web_ui_react" ]; then
  echo "⚠️ Frontend testleri atlandı: web_ui_react/package.json bulunamadı."
fi

echo "======================================================"

# 4) Final Durum Değerlendirmesi
if [ "${BACKEND_EXIT_CODE}" -ne 0 ] || [ "${FRONTEND_EXIT_CODE}" -ne 0 ] || [ "${BENCHMARK_EXIT_CODE}" -ne 0 ]; then
  echo "❌ Bazı testler veya kalite kapıları (coverage) başarısız oldu!"
  echo "   Backend Çıkış Kodu: ${BACKEND_EXIT_CODE}"
  echo "   Frontend Çıkış Kodu: ${FRONTEND_EXIT_CODE}"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE}"
  exit 1
else
  echo "✅ Tüm Backend, Frontend ve Benchmark testleri BAŞARIYLA tamamlandı!"
  exit 0
fi
