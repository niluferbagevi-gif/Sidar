SHELL := /usr/bin/env bash

SHELLCHECK ?= uv run shellcheck
BATS ?= bats
BENCHMARK_COMPARE_REQUIRED ?= 0
CI_RUN_BENCHMARKS ?= 0
CI_PRODUCTION_READINESS ?= 0
FRONTEND_BUNDLE_BUDGET_LOCAL_FULL ?= 1
SIDAR_TOTAL_JS_BUDGET_KB ?= 500
SIDAR_TOTAL_GZIP_BUDGET_KB ?= 160
PLUGIN_SANDBOX_IMAGE ?= sidar:latest

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

.PHONY: lint lint-shell installer-shellcheck test test-shell check-install-manifests finalize-install-module-pin deps-full deps-dev-light sync-ci-parity-deps validate validate-dev dev-full dev-full-gpu ci-parity plugin-sandbox-security base-quality-gates release-readiness production-readiness doctor-production-readiness benchmark-seed frontend-gate backend-integration format format-check python-quality

lint: lint-shell check-install-manifests

installer-shellcheck:
	$(SHELLCHECK) --severity=warning -x $(INSTALLER_SHELLCHECK_FILES)

lint-shell:
	$(SHELLCHECK) --severity=warning -x $(SHELLCHECK_FILES)

check-install-manifests:
	uv run python scripts/tools/update_core_install_manifest.py --check
	uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check
	uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh --check-pin

finalize-install-module-pin:
	bash scripts/finalize_install_module_pin.sh

deps-full:
	bash scripts/install_ci_system_deps.sh
	uv sync --frozen --all-extras

deps-dev-light:
	uv sync --frozen --extra dev-light

# Refresh both lockfile-backed environments before claiming local CI parity.
# This prevents a previously populated .venv or node_modules tree from hiding
# dependency changes that landed after the checkout being validated.
sync-ci-parity-deps:
	uv sync --frozen --all-extras
	npm --prefix web_ui_react ci

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

# AUTO_BUILD_DOCKER_TEST_IMAGE=1 mirrors ci.yml's integration-test job: the
# plugin sandbox backend defaults to Docker in every environment (SEC-PLUGIN-001,
# web/plugins/sandbox.py:plugin_sandbox_backend), and
# tests/integration/web/test_plugin_sandbox_integration.py exercises that real
# Docker path with no skip guard (unlike test_plugin_sandbox_container_escape.py,
# which module-skips without a pre-built image). Without this, `make dev-full`
# deterministically fails that test on any checkout where `sidar:latest` has not
# been built by hand, even though install_sidar.sh already requires a working
# Docker daemon. prepare_docker_test_image() (scripts/test_gates/backend_helpers.sh)
# no-ops if the image already exists, so this only costs a build on first run.
validate:
	@echo "ℹ️ 'make validate' geriye dönük alias'tır; development doğrulaması çalıştırılıyor."
	@echo "   Release/merge kanıtı için: make release-readiness"
	$(MAKE) validate-dev

validate-dev: dev-full

dev-full:
	SIDAR_TOTAL_JS_BUDGET_KB=$(SIDAR_TOTAL_JS_BUDGET_KB) \
	SIDAR_TOTAL_GZIP_BUDGET_KB=$(SIDAR_TOTAL_GZIP_BUDGET_KB) \
	RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 \
	FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=$(FRONTEND_BUNDLE_BUDGET_LOCAL_FULL) \
	AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=$(PLUGIN_SANDBOX_IMAGE) \
	bash run_tests.sh --stage all

dev-full-gpu:
	RUN_GPU_STRESS=1 $(MAKE) dev-full

# Distinct from plain `dev-full`: TEST_PROFILE=ci switches run_tests.sh's
# profile-dependent defaults to the same branch CI takes (AUTO_OPEN_ARTIFACTS=0,
# RUN_BATS_TESTS=1 unconditionally instead of "auto", BENCHMARK_COMPARE_FAIL
# tightened to mean:10% instead of local's mean:15%, and the
# COVERAGE_FAIL_UNDER_CI/_LOCAL override split -- see run_tests.sh). Without
# it, this target ran with local-profile defaults under a name that promised
# CI parity: `make ci-parity` could pass locally (looser 15% benchmark
# tolerance) on a change that would then fail real CI's 10% threshold.
# FRONTEND_E2E_NPM_SCRIPT=test:e2e mirrors ci.yml's "test" job exactly: all 8
# web_ui_react/e2e/ specs, not just the smoke default (see base-quality-gates
# below for the same override on the release-gate path).
ci-parity: sync-ci-parity-deps
	TEST_PROFILE=ci FRONTEND_E2E_NPM_SCRIPT=test:e2e \
	$(MAKE) dev-full FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=1 \
		SIDAR_TOTAL_JS_BUDGET_KB=$(SIDAR_TOTAL_JS_BUDGET_KB) \
		SIDAR_TOTAL_GZIP_BUDGET_KB=$(SIDAR_TOTAL_GZIP_BUDGET_KB)

# Build the current checkout instead of trusting a potentially stale local tag,
# then make skipped real-container security tests a hard failure.
plugin-sandbox-security:
	@command -v docker >/dev/null || { echo "Docker CLI bulunamadı." >&2; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "Docker daemon erişilebilir değil." >&2; exit 1; }
	docker build --tag $(PLUGIN_SANDBOX_IMAGE) .
	SIDAR_PLUGIN_SANDBOX_IMAGE=$(PLUGIN_SANDBOX_IMAGE) \
	SIDAR_REQUIRE_PLUGIN_SANDBOX_CONTAINER_TESTS=1 \
	uv run pytest -q -rs tests/integration/web/test_plugin_sandbox_container_escape.py

# FRONTEND_E2E_NPM_SCRIPT=test:e2e mirrors ci.yml's "test" job exactly: all 8
# web_ui_react/e2e/ specs, not just the smoke default. Without this override
# `make production-readiness` silently ran a narrower e2e suite than CI itself
# despite claiming full-gate parity.
# AUTO_BUILD_DOCKER_TEST_IMAGE=1: see the comment on `dev-full` above -- the
# release/production-readiness gate must build (or reuse) `sidar:latest` for
# the same reason, otherwise a release-readiness run fails on the identical
# Docker-sandbox gap it exists to catch.
base-quality-gates:
	TEST_PROFILE=ci RUN_BENCHMARKS=$(CI_RUN_BENCHMARKS) RUN_FRONTEND_E2E=1 \
	FRONTEND_E2E_NPM_SCRIPT=test:e2e \
	SIDAR_PRODUCTION_READINESS=$(CI_PRODUCTION_READINESS) \
	SIDAR_TOTAL_JS_BUDGET_KB=$(SIDAR_TOTAL_JS_BUDGET_KB) \
	SIDAR_TOTAL_GZIP_BUDGET_KB=$(SIDAR_TOTAL_GZIP_BUDGET_KB) \
	AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=$(PLUGIN_SANDBOX_IMAGE) \
	env -u CI_RUN_BENCHMARKS -u CI_PRODUCTION_READINESS \
	bash run_tests.sh --stage all

production-readiness:
	$(MAKE) base-quality-gates CI_RUN_BENCHMARKS=required CI_PRODUCTION_READINESS=1

release-readiness: production-readiness

doctor-production-readiness:
	uv run python scripts/doctor_production_readiness.py

# Lokal benchmark baseline bootstrap içindir; CI baseline için workflow_dispatch
# seed_benchmark_baseline=true kullanılmalıdır.
benchmark-seed:
	BENCHMARK_COMPARE_REQUIRED=0 BENCHMARK_ENFORCE_COMPARE=0 RUN_BENCHMARKS=required bash run_tests.sh --stage all

frontend-gate:
	RUN_FRONTEND_E2E=1 FRONTEND_E2E_ENFORCE_RESULT=1 bash run_tests.sh --stage frontend

backend-integration:
	bash run_tests.sh --stage integration
