SHELL := /usr/bin/env bash

SHELLCHECK ?= shellcheck
BATS ?= bats

SHELLCHECK_FILES := \
	install_sidar.sh \
	scripts/install_modules/*.sh \
	scripts/install_modules/phases/*.sh \
	scripts/install_modules/utils/*.sh \
	tests/shell/*.bats

.PHONY: lint lint-shell test-shell

lint: lint-shell

lint-shell:
	$(SHELLCHECK) --severity=warning -x $(SHELLCHECK_FILES)

test-shell:
	$(BATS) tests/shell
