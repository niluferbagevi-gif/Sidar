SHELL := /usr/bin/env bash

SHELLCHECK ?= uv run shellcheck
BATS ?= bats
BENCHMARK_COMPARE_REQUIRED ?= 0
CI_RUN_BENCHMARKS ?= 0
CI_PRODUCTION_READINESS ?= 0
FRONTEND_BUNDLE_BUDGET_LOCAL_FULL ?= 1
SIDAR_TOTAL_JS_BUDGET_KB ?= 550
SIDAR_TOTAL_GZIP_BUDGET_KB ?= 170

SHELLCHECK_FILES := $(shell git ls-files \
	'install_sidar.sh' \
	'autonomous_loop.sh' \
	'run_tests.sh' \
	'scripts/*.sh' \
	'scripts/**/*.sh' \
	'tests/shell/*.bats')

INSTALLER_SHELLCHECK_FILES := $(shell git ls-files \
	'install_sidar.sh' \
	'scripts/install_modules/*.sh' \
	'scripts/install_modules/**/*.sh')

.PHONY: lint lint-shell installer-shellcheck test test-shell check-install-manifests deps-full deps-dev-light dev-full dev-full-gpu ci-parity base-quality-gates production-readiness doctor-production-readiness benchmark-seed frontend-gate backend-integration format format-check python-quality

lint: lint-shell check-install-manifests

installer-shellcheck:
	$(SHELLCHECK) --severity=warning -x $(INSTALLER_SHELLCHECK_FILES)

lint-shell:
	$(SHELLCHECK) --severity=warning -x $(SHELLCHECK_FILES)

check-install-manifests:
	uv run python scripts/tools/update_core_install_manifest.py --check
	uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check
	uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check-pin

deps-full:
	bash scripts/install_ci_system_deps.sh
	uv sync --frozen --all-extras

deps-dev-light:
	uv sync --frozen --extra dev-light

test-shell:
	$(BATS) tests/shell

test: test-shell

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

python-quality:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --strict core/ agent/ web/ managers/ launcher/

dev-full:
	SIDAR_TOTAL_JS_BUDGET_KB=$(SIDAR_TOTAL_JS_BUDGET_KB) \
	SIDAR_TOTAL_GZIP_BUDGET_KB=$(SIDAR_TOTAL_GZIP_BUDGET_KB) \
	RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 \
	FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=$(FRONTEND_BUNDLE_BUDGET_LOCAL_FULL) \
	bash run_tests.sh --stage all

dev-full-gpu:
	RUN_GPU_STRESS=1 $(MAKE) dev-full

ci-parity:
	$(MAKE) dev-full FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=1 \
		SIDAR_TOTAL_JS_BUDGET_KB=$(SIDAR_TOTAL_JS_BUDGET_KB) \
		SIDAR_TOTAL_GZIP_BUDGET_KB=$(SIDAR_TOTAL_GZIP_BUDGET_KB)

base-quality-gates:
	TEST_PROFILE=ci RUN_BENCHMARKS=$(CI_RUN_BENCHMARKS) RUN_FRONTEND_E2E=1 \
	SIDAR_PRODUCTION_READINESS=$(CI_PRODUCTION_READINESS) \
	SIDAR_TOTAL_JS_BUDGET_KB=$(SIDAR_TOTAL_JS_BUDGET_KB) \
	SIDAR_TOTAL_GZIP_BUDGET_KB=$(SIDAR_TOTAL_GZIP_BUDGET_KB) \
	bash run_tests.sh --stage all

production-readiness:
	$(MAKE) base-quality-gates CI_RUN_BENCHMARKS=required CI_PRODUCTION_READINESS=1

doctor-production-readiness:
	uv run python scripts/doctor_production_readiness.py

# Lokal benchmark baseline bootstrap içindir; CI baseline için workflow_dispatch
# seed_benchmark_baseline=true kullanılmalıdır.
benchmark-seed:
	BENCHMARK_COMPARE_REQUIRED=$(BENCHMARK_COMPARE_REQUIRED) RUN_BENCHMARKS=required bash run_tests.sh --stage all

frontend-gate:
	RUN_FRONTEND_E2E=1 FRONTEND_E2E_ENFORCE_RESULT=1 bash run_tests.sh --stage frontend

backend-integration:
	bash run_tests.sh --stage integration
