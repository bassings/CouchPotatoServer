# CouchPotatoServer — developer workflow shortcuts.
# Path to production: make setup → code → make verify (auto-enforced on push)
#                     → PR → Claude review + remediate → merge → release.

# Same resolution order scripts/verify.sh uses, so `make <target>` and the
# gate run under the same interpreter and cannot disagree about which
# dependencies are installed.
#
# Used by EVERY Python recipe below, not just one. When only check-traps used
# it, this comment was a claim the file did not deliver: measured,
# `make lint` ran ruff 0.15.0 from Homebrew python3 while the gate ran the
# pinned 0.16.0 from the venv (requirements-dev.txt), so `make lint` green did
# not mean the gate would be. `setup` deliberately still uses bare python3 --
# it is the target that CREATES the environment.
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

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
	$(PYTHON) -m ruff check .

security-lint: ## Static security lint (ruff bandit "S" rules — informational)
	$(PYTHON) -m ruff check --select S couchpotato/ CouchPotato.py

test-py: ## Python unit tests only
	PYTHONPATH=libs $(PYTHON) -m pytest tests/unit/ -q --tb=short

test-ui: ## UI unit tests (vitest) only
	npm run test:unit

test-e2e: ## E2E tests (Playwright, auto-starts server) only
	npx playwright test --project=chromium

mutation: mutation-py mutation-js ## Run all mutation testing (slow)

mutation-py: ## Python mutation testing (mutmut)
	PYTHONPATH=libs $(PYTHON) -m mutmut run

mutation-js: ## JS mutation testing (Stryker)
	npm run test:mutation

# BASE defaults to master; override for a different comparison point, e.g.
#   make mutation-changed BASE=origin/master
BASE ?= master

mutation-changed: ## Mutation testing on changed files only (fast enough per-change)
	$(PYTHON) scripts/mutation_changed.py --base $(BASE)

check-traps: ## False-green guard (jsdom layout reads, exit-code-eating pipes, weak shell gates)
	@# The venv, not the system interpreter. This checker needs PyYAML to read
	@# the workflow files, and it fails LOUDLY when it is missing rather than
	@# skipping -- correct behaviour, but bare `python3` on a developer's Mac
	@# has no PyYAML, so `make check-traps` (the command CLAUDE.md names) went
	@# red with 7 findings on a clean tree while scripts/verify.sh, which uses
	@# $$PYTHON, went green on the same tree. A gate that cries wolf from the
	@# documented entry point trains the reader to ignore it, which is the
	@# opposite of what a false-green guard is for. Overridable, and still
	@# falls back to python3 so a clone with no venv gets the loud failure.
	@# --require-git, like scripts/verify.sh and ci.yml. Without it a
	@# `git ls-files` failure is caught, noted on stderr and the run exits 0
	@# with rule 5 (orphaned test files) never having executed -- and this is
	@# the entry point CLAUDE.md's command table names, so it is the one most
	@# likely to be run somewhere odd. The earlier justification for leaving it
	@# bare was that the git-less Alpine container needs it: measured, nothing
	@# git-less invokes this target at all (scripts/test-local.sh only mentions
	@# the checker in a comment), so that reasoning was simply wrong.
	$(PYTHON) scripts/check_test_traps.py --require-git

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
