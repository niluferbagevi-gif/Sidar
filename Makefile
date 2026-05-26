SHELL := /usr/bin/env bash

SHELLCHECK ?= uv run shellcheck
BATS ?= bats

SHELLCHECK_FILES := $(shell git ls-files \
	'install_sidar.sh' \
	'autonomous_loop.sh' \
	'run_tests.sh' \
	'scripts/*.sh' \
	'scripts/**/*.sh' \
	'tests/shell/*.bats')

.PHONY: lint lint-shell installer-shellcheck test test-shell

lint: installer-shellcheck lint-shell

installer-shellcheck:
	$(SHELLCHECK) --severity=warning -x install_sidar.sh

lint-shell:
	$(SHELLCHECK) --severity=warning -x $(SHELLCHECK_FILES)

test-shell:
	$(BATS) tests/shell

test: test-shell
