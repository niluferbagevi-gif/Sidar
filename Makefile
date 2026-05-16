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

.PHONY: lint lint-shell test-shell

lint: lint-shell

lint-shell:
	$(SHELLCHECK) --severity=warning -x $(SHELLCHECK_FILES)

test-shell:
	$(BATS) tests/shell
