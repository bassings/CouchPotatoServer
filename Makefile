# CouchPotatoServer — developer workflow shortcuts.
# Path to production: make setup → code → make verify (auto-enforced on push)
#                     → PR → Claude review + remediate → merge → release.

.PHONY: help setup verify verify-fast test-py test-ui test-e2e lint security-lint check-traps check-secrets check-secrets-history mutation mutation-py mutation-js mutation-changed backup

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## One-time: install Python+JS deps and git hooks so the local gate runs on push
	git config core.hooksPath .githooks
	chmod +x .githooks/* scripts/*.sh
	python3 -m pip install -r requirements.txt -r requirements-dev.txt
	npm ci
	npx playwright install chromium
	@echo "✅ Setup complete. 'git push' now runs the full gate (scripts/verify.sh)."

verify: ## Full local gate — mirrors CI (lint + py unit + py integration + ui unit + e2e)
	./scripts/verify.sh

verify-fast: ## Quick gate — lint + unit only, skips E2E
	./scripts/verify.sh --no-e2e

lint: ## ruff lint only
	python3 -m ruff check .

security-lint: ## Static security lint (ruff bandit "S" rules — informational)
	python3 -m ruff check --select S couchpotato/ CouchPotato.py

test-py: ## Python unit tests only
	PYTHONPATH=libs python3 -m pytest tests/unit/ -q --tb=short

test-ui: ## UI unit tests (vitest) only
	npm run test:unit

test-e2e: ## E2E tests (Playwright, auto-starts server) only
	npm run test:e2e -- --project=chromium

mutation: mutation-py mutation-js ## Run all mutation testing (slow)

mutation-py: ## Python mutation testing (mutmut)
	PYTHONPATH=libs python3 -m mutmut run

mutation-js: ## JS mutation testing (Stryker)
	npm run test:mutation

# BASE defaults to master; override for a different comparison point, e.g.
#   make mutation-changed BASE=origin/master
BASE ?= master

mutation-changed: ## Mutation testing on changed files only (fast enough per-change)
	python3 scripts/mutation_changed.py --base $(BASE)

check-traps: ## False-green guard (jsdom layout reads, exit-code-eating pipes, weak shell gates)
	python3 scripts/check_test_traps.py

# Pinned version: an unpinned :latest changes the ruleset under you, so a clean
# scan today can fail tomorrow with no code change. Bump deliberately.
GITLEAKS_IMAGE ?= zricethezav/gitleaks:v8.30.1

check-secrets: ## Secret scan of the working tree (same command CI runs)
	docker run --rm -v "$(PWD):/repo" -w /repo $(GITLEAKS_IMAGE) \
		detect --source=. --no-git --config=.gitleaks.toml --no-banner --redact -v

check-secrets-history: ## Secret scan of ALL git history (noisy: ~37 known hits, see below)
	@echo "Expect ~37 findings. As of 2026-07-30 they break down as:"
	@echo "  * 29 authored by ruud@crashdummy.nl (upstream CouchPotato), spanning"
	@echo "    2011-2016 -- NOT just pre-2013; 10 of the 29 are 2013 or later."
	@echo "  *  2 by other upstream contributors (one of them the lone 2017 hit)."
	@echo "  *  6 authored by bassings@gmail.com -- THIS FORK's own commits:"
	@echo "       - QA/QA_SESSION_2026-02-19.md (a per-install api_key, redacted"
	@echo "         from HEAD 2026-07-30; still in history, hence rotate not redact)"
	@echo "       - 5 under migration_backup/ (2025-07-30), which are COPIES of the"
	@echo "         same upstream provider keys; that directory is no longer tracked."
	@echo "  Triage anything outside that set -- do not assume a finding is upstream"
	@echo "  noise just because most of them are."
	docker run --rm -v "$(PWD):/repo" -w /repo $(GITLEAKS_IMAGE) \
		detect --source=. --config=.gitleaks.toml --no-banner --redact -v

backup: ## Snapshot the SQLite DB + settings (see docs/development-process.md)
	./scripts/backup.sh
