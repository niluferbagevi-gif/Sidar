#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2034  # Helpers update run_tests.sh globals after being sourced.
# Helper functions sourced by run_tests.sh; do not execute directly.

run_pytest_coverage_report() {
  echo "📊 Pytest + Coverage + Quality Gate çalıştırılıyor..."
  local test_dotenv_file="${DOTENV_FILE:-.env.test}"
  echo "ℹ️ Test ortam değişken dosyası: DOTENV_FILE=${test_dotenv_file}"
  if ! python - <<'PY' >/dev/null 2>&1
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
opt_deps = data.get("project", {}).get("optional-dependencies", {})
deps = opt_deps.get("test") or opt_deps.get("dev") or opt_deps.get("all") or []
deps_l = [d.lower() for d in deps]
assert any("pytest-cov" in d for d in deps_l), "pytest-cov"
assert any("pytest-xdist" in d for d in deps_l), "pytest-xdist"
PY
  then
    echo "❌ pyproject.toml test bağımlılıklarında pytest-cov/pytest-xdist doğrulaması başarısız."
    BACKEND_EXIT_CODE=1
    return
  fi

  # -c pyproject.toml ile marker/addopts ayarlarının kök dizinden bağımsız şekilde
  # her çağrıda kesin yüklenmesi garanti edilir. Doğrudan/tekil pytest debug
  # çağrıları yanıltıcı coverage gate hatası üretmesin diye coverage seçenekleri
  # pyproject addopts yerine yalnız bu kalite kapısı içinde açıkça verilir.
  # Faz bazlı pytest-cov raporları pyproject.toml fail_under değerini kullanarak
  # erken başarısız olmasın diye burada 0 ile nötrlenir; asıl kalite kapısı
  # tüm fazlar birleştirildikten sonra coverage report --fail-under ile uygulanır.
  echo "🔎 Active coverage.py config doğrulanıyor: coverage debug config"
  uv run python -m coverage debug config || true

  local coverage_pytest_opts=(
    --cov=agent
    --cov=core
    --cov=managers
    --cov=plugins
    --cov=web
    --cov-report=term-missing
    --cov-report=html
    --cov-report=xml
  )
  local base_pytest_cmd=(
    env "DOTENV_FILE=${test_dotenv_file}" uv run pytest -c pyproject.toml
    "${coverage_pytest_opts[@]}"
    --cov-fail-under=0
  )
  if [ "${QUALITY_GATE_EXIT_AFTER_FIRST_FAIL}" = "1" ]; then
    echo "ℹ️ QUALITY_GATE_EXIT_AFTER_FIRST_FAIL=1; pytest ilk failure sonrası duracak (-x)."
    base_pytest_cmd+=(-x)
  fi

  local enable_gpu_tests="${ENABLE_GPU_TESTS:-auto}"
  if [ "${enable_gpu_tests}" = "auto" ]; then
    if gpu_hardware_available; then
      enable_gpu_tests="1"
      echo "ℹ️ GPU donanımı tespit edildi; ENABLE_GPU_TESTS=auto -> 1."
    else
      enable_gpu_tests="0"
      echo "ℹ️ GPU donanımı tespit edilmedi; ENABLE_GPU_TESTS=auto -> 0 ve GPU testleri atlanacak."
    fi
  fi

  if [ "${enable_gpu_tests}" != "1" ]; then
    echo "ℹ️ GPU testleri atlanıyor (Çalıştırmak için: ENABLE_GPU_TESTS=1 bash run_tests.sh)"
    base_pytest_cmd+=(-m "not gpu")
  else
    if ! gpu_hardware_available; then
      echo "⚠️ ENABLE_GPU_TESTS=1 verildi ancak nvidia-smi bulunamadı. GPU testleri güvenli fallback ile atlanıyor."
      base_pytest_cmd+=(-m "not gpu")
    else
      echo "🔥 GPU testleri de dahil ediliyor!"
      if [ "${RUN_GPU_STRESS:-0}" != "1" ]; then
        export RUN_GPU_STRESS=1
        echo "ℹ️ GPU tespit edildiği için testlerde RUN_GPU_STRESS=1 otomatik etkinleştirildi."
      fi
    fi
  fi

  if python -c "import xdist" >/dev/null 2>&1; then
    # `xdist_group` ile işaretlenen process-global state testlerini aynı worker'da
    # seri çalıştırırken işaretsiz testlerde paralelliği korur.
    base_pytest_cmd+=(-n "${PYTEST_WORKERS}" --dist "${PYTEST_DIST_MODE}")
  fi

  # Coverage raporlarını XML/JSON olarak dışa aktararak otomatik araçların
  # (ör. coverage hotspot analizi ve otonom test üretim döngüsü) makinece
  # okunabilir artefaktlardan beslenmesini garanti ederiz.
  base_pytest_cmd+=(--cov-report=json)

  # Benchmark ölçümlerinin doğruluğu için performans testleri bu aşamada
  # özellikle hariç tutulur ve aşağıda tek çekirdekli ayrı fazda çalıştırılır.
  base_pytest_cmd+=(--ignore=tests/performance)
  if [ "${PERFORMANCE_TEST_DIR}" != "tests/performance" ] && [ -d "${PERFORMANCE_TEST_DIR}" ]; then
    base_pytest_cmd+=(--ignore="${PERFORMANCE_TEST_DIR}")
  fi

  local run_unit_phase=0
  local phase2_dirs=()
  if stage_selected backend || stage_selected unit; then
    run_unit_phase=1
  fi
  if stage_selected backend || stage_selected integration; then
    phase2_dirs+=(tests/integration)
  fi
  if stage_selected backend || stage_selected smoke; then
    phase2_dirs+=(tests/smoke)
  fi
  if stage_selected backend || stage_selected e2e; then
    phase2_dirs+=(tests/e2e)
  fi

  # Aşama 1: Unit testler (yüksek paralellik)
  local phase1_exit=0
  mkdir -p "${TEST_SUMMARY_JUNIT_DIR}"
  rm -f "${TEST_SUMMARY_JUNIT_DIR}"/backend-*.xml
  if [ "${run_unit_phase}" -eq 1 ]; then
    local phase1_cmd=(
      "${base_pytest_cmd[@]}"
      "--junitxml=${TEST_SUMMARY_JUNIT_DIR}/backend-unit.xml"
      tests/unit
    )
    echo "➡️ Aşama 1 (Unit) komutu: ${phase1_cmd[*]}"
    BACKEND_UNIT_RAN=1
    run_checked "${phase1_cmd[@]}"
    phase1_exit=$?
    BACKEND_UNIT_EXIT_CODE=${phase1_exit}
  else
    echo "ℹ️ Aşama 1 (Unit) atlandı (--stage=${RUN_TESTS_STAGE})."
  fi

  # Aşama 2: Integration/Smoke/E2E testleri (sınırlı paralellik)
  local phase2_workers="${INTEGRATION_PYTEST_WORKERS:-2}"
  local phase2_cmd=("${base_pytest_cmd[@]}")
  local filtered_phase2_cmd=()
  local skip_next=0
  for arg in "${phase2_cmd[@]}"; do
    if [ "${skip_next}" -eq 1 ]; then
      skip_next=0
      continue
    fi
    if [ "${arg}" = "-n" ]; then
      skip_next=1
      continue
    fi
    filtered_phase2_cmd+=("${arg}")
  done
  local phase2_exit=0
  if [ "${#phase2_dirs[@]}" -gt 0 ]; then
    if stage_selected backend || stage_selected integration; then
      BACKEND_INTEGRATION_RAN=1
    fi
    if stage_selected backend || stage_selected smoke; then
      BACKEND_SMOKE_RAN=1
    fi
    if stage_selected backend || stage_selected e2e; then
      BACKEND_E2E_RAN=1
    fi
    local phase2_cov_args=()
    if [ "${run_unit_phase}" -eq 1 ]; then
      # Aşama 2 coverage verisini Aşama 1 ile birleştiririz; entegrasyon testleri
      # tek başına fail-under kalite barajına tabi tutulmaz.
      phase2_cov_args+=(--cov-append)
    fi
    phase2_cmd=(
      "${filtered_phase2_cmd[@]}"
      "${phase2_cov_args[@]}"
      "--junitxml=${TEST_SUMMARY_JUNIT_DIR}/backend-integration-smoke-e2e.xml"
      -n "${phase2_workers}"
      "${phase2_dirs[@]}"
    )
    echo "➡️ Aşama 2 (Integration/Smoke/E2E) komutu: ${phase2_cmd[*]}"
    run_checked "${phase2_cmd[@]}"
    phase2_exit=$?
    if [ "${BACKEND_INTEGRATION_RAN}" = "1" ]; then
      BACKEND_INTEGRATION_EXIT_CODE=${phase2_exit}
    fi
    if [ "${BACKEND_SMOKE_RAN}" = "1" ]; then
      BACKEND_SMOKE_EXIT_CODE=${phase2_exit}
    fi
    if [ "${BACKEND_E2E_RAN}" = "1" ]; then
      BACKEND_E2E_EXIT_CODE=${phase2_exit}
    fi
  else
    echo "ℹ️ Aşama 2 (Integration/Smoke/E2E) atlandı (--stage=${RUN_TESTS_STAGE})."
  fi

  if [ "${phase1_exit}" -ne 0 ] || [ "${phase2_exit}" -ne 0 ]; then
    record_backend_failure "pytest_failed"
    BACKEND_EXIT_CODE=1
  else
    BACKEND_EXIT_CODE=0
  fi

  # xdist altında bazı koşullarda sadece .coverage.* shard'ları kalabilir.
  # Önce bunları birleştirmeyi dener, başarısızsa quality gate'i fail eder.
  if [ ! -f ".coverage" ] && [ "${BACKEND_EXIT_CODE}" -eq 0 ]; then
    if compgen -G ".coverage.*" > /dev/null; then
      echo "ℹ️ .coverage bulunamadı fakat .coverage.* shard dosyaları tespit edildi. coverage combine deneniyor..."
      if uv run python -m coverage combine; then
        echo "✅ coverage combine başarılı; final rapor üretimi bir sonraki adımda yapılacak."
      else
        echo "❌ coverage combine başarısız oldu. Paralel testlerde coverage verisi toparlanamadı."
        record_backend_failure "coverage_combine_failed"
        BACKEND_EXIT_CODE=1
      fi
    else
      echo "⚠️ Uyarı: Testler başarılı görünüyor ancak .coverage dosyası üretilemedi. xdist worker'ları crash olmuş olabilir."
      record_backend_failure "coverage_data_missing"
      BACKEND_EXIT_CODE=1
    fi
  fi

  enforce_combined_coverage_gate

  if [ -f "htmlcov/index.html" ]; then
    echo "✅ Coverage HTML raporu oluşturuldu: htmlcov/index.html"
    open_artifact "htmlcov/index.html"
  else
    echo "⚠️ Coverage raporu oluşturulamadı: htmlcov/index.html bulunamadı."
  fi
}

should_enforce_combined_coverage_gate() {
  stage_all_selected || stage_selected backend || stage_selected unit
}

enforce_combined_coverage_gate() {
  if [ "${BACKEND_EXIT_CODE}" -ne 0 ]; then
    echo "ℹ️ Test fazlarından biri başarısız olduğu için final coverage quality gate atlandı."
    return 0
  fi

  if [ ! -f ".coverage" ]; then
    echo "⚠️ Final coverage quality gate çalıştırılamadı: .coverage bulunamadı."
    record_backend_failure "coverage_data_missing"
    BACKEND_EXIT_CODE=1
    return 0
  fi

  # Rapor üretim komutları (html/xml/json) coverage.py'nin [tool.coverage.report]
  # fail_under eşiğini de miras alır; --fail-under=0 olmadan, eşiğin altında
  # kalan kısmi bir çalışmada rapor dosyası başarıyla yazılsa bile komut
  # non-zero döner ve script bunu yanlışlıkla "rapor üretilemedi" sayar.
  # Artefakt üretimini kalite kapısından ayırmak için burada her zaman
  # --fail-under=0 kullanılır; asıl eşik aşağıda ayrıca uygulanır.
  echo "📊 Final birleşik coverage raporları yenileniyor..."
  if ! uv run python -m coverage html -d htmlcov --fail-under=0; then
    echo "❌ Coverage HTML raporu üretilemedi."
    record_backend_failure "coverage_html_report_failed"
    BACKEND_EXIT_CODE=1
    return 0
  fi
  if ! uv run python -m coverage xml -o coverage.xml --fail-under=0; then
    echo "❌ Coverage XML raporu üretilemedi."
    record_backend_failure "coverage_xml_report_failed"
    BACKEND_EXIT_CODE=1
    return 0
  fi
  if ! uv run python -m coverage json -o coverage.json --fail-under=0; then
    echo "❌ Coverage JSON raporu üretilemedi."
    record_backend_failure "coverage_json_report_failed"
    BACKEND_EXIT_CODE=1
    return 0
  fi

  if ! should_enforce_combined_coverage_gate; then
    echo "ℹ️ Kısmi test stage'i seçildi (--stage=${RUN_TESTS_STAGE}); global coverage fail-under kalite kapısı atlandı."
    return 0
  fi

  echo "🧪 Final coverage quality gate doğrulanıyor: coverage report --fail-under=${COVERAGE_FAIL_UNDER}"
  if uv run python -m coverage report --fail-under="${COVERAGE_FAIL_UNDER}"; then
    echo "✅ Final coverage quality gate geçti (eşik: ${COVERAGE_FAIL_UNDER})."
  else
    echo "❌ Final coverage quality gate başarısız oldu (eşik: ${COVERAGE_FAIL_UNDER})."
    record_backend_failure "coverage_gate_failed"
    BACKEND_EXIT_CODE=1
  fi
}

update_progressive_coverage_gate() {
  if [ "${COVERAGE_RATCHET_ENABLED:-1}" != "1" ]; then
    echo "ℹ️ Coverage ratcheting devre dışı (COVERAGE_RATCHET_ENABLED=${COVERAGE_RATCHET_ENABLED:-0})."
    return 0
  fi

  if [ "${BACKEND_EXIT_CODE}" -ne 0 ]; then
    echo "ℹ️ Backend kalite akışı başarısız olduğu için coverage ratchet atlandı (nedenler: $(format_backend_failure_reasons))."
    return 0
  fi

  if [ ! -f "coverage.json" ]; then
    echo "⚠️ coverage.json bulunamadı; coverage ratchet uygulanamadı."
    return 0
  fi

  echo "📈 Coverage ratcheting kontrolü çalıştırılıyor (step=${COVERAGE_RATCHET_STEP:-1}, min=${COVERAGE_RATCHET_MIN_GATE:-5}, max=${COVERAGE_RATCHET_MAX_GATE:-100})..."
  if uv run python scripts/coverage_ratchet.py \
    --coverage-config "${COVERAGE_RATCHET_STATE_FILE}" \
    --coverage-json coverage.json \
    --step "${COVERAGE_RATCHET_STEP:-1}" \
    --min-gate "${COVERAGE_RATCHET_MIN_GATE:-5}" \
    --max-gate "${COVERAGE_RATCHET_MAX_GATE:-100}"; then
    DEFAULT_COVERAGE_FAIL_UNDER="$(python - "${COVERAGE_RATCHET_STATE_FILE}" <<'PY_RATCHET_GATE'
from pathlib import Path
import sys
import tomllib

data = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under", 5))
PY_RATCHET_GATE
)"
    if [ "${COVERAGE_FAIL_UNDER_SOURCE}" = "explicit-override" ]; then
      echo "ℹ️ Açık COVERAGE_FAIL_UNDER override korundu; ratchet sonrası eşik ${COVERAGE_FAIL_UNDER} olarak bırakıldı (pyproject.toml baseline=${DEFAULT_COVERAGE_FAIL_UNDER})."
    else
      COVERAGE_FAIL_UNDER="${DEFAULT_COVERAGE_FAIL_UNDER}"
    fi
  else
    echo "❌ Coverage ratcheting başarısız oldu."
    record_backend_failure "ratchet_failed"
    BACKEND_EXIT_CODE=1
  fi
}
