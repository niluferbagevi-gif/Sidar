SHELL := /usr/bin/env bash

SHELLCHECK ?= uv run shellcheck
BATS ?= bats
BENCHMARK_COMPARE_REQUIRED ?= 0
FRONTEND_BUNDLE_BUDGET_LOCAL_FULL ?= 1

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

.PHONY: lint lint-shell installer-shellcheck test test-shell check-install-manifests dev-full ci-parity production-readiness benchmark-seed frontend-gate backend-integration

lint: lint-shell check-install-manifests

installer-shellcheck:
	$(SHELLCHECK) --severity=warning -x $(INSTALLER_SHELLCHECK_FILES)

lint-shell:
	$(SHELLCHECK) --severity=warning -x $(SHELLCHECK_FILES)

check-install-manifests:
	uv run python scripts/tools/update_core_install_manifest.py --check
	uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check

test-shell:
	$(BATS) tests/shell

test: test-shell

dev-full:
	RUN_GPU_STRESS=1 RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all

ci-parity:
	$(MAKE) dev-full FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=1

production-readiness:
	TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all

benchmark-seed:
	BENCHMARK_COMPARE_REQUIRED=$(BENCHMARK_COMPARE_REQUIRED) RUN_BENCHMARKS=required bash run_tests.sh --stage all

frontend-gate:
	RUN_FRONTEND_E2E=1 FRONTEND_E2E_ENFORCE_RESULT=1 bash run_tests.sh --stage frontend

backend-integration:
	bash run_tests.sh --stage integration
