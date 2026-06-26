# CouchPotatoServer — developer workflow shortcuts.
# Path to production: make setup → code → make verify (auto-enforced on push)
#                     → PR → Claude review + remediate → merge → release.

.PHONY: help setup verify verify-fast test-py test-ui test-e2e lint security-lint mutation mutation-py mutation-js

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

verify: ## Full local gate — mirrors CI (lint + py unit + ui unit + e2e)
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
