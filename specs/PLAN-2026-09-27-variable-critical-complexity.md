# Variable helper critical-complexity paydown

## Goal

Close the two critical `python:S3776` findings in `couchpotato/core/helpers/variable.py` without changing dictionary-merge or startup bytecode-cleanup behaviour. The exact-master Sonar analysis at `fce0ec9a` reports cognitive complexity 20 for `mergeDicts` and 23 for `removePyc`, against a limit of 15. `specs/PLAN-2026-09-27-scanner-scan-debt.md` is the format exemplar.

## Acceptance criteria

- [ ] AC-DATA-1: `removePyc` still removes only eligible `.pyc` files, respects `only_excess`, preserves matching `.py` siblings, and prunes only directories observed empty under its existing top-down walk.
- [ ] AC-REL-1: Missing directories during cleanup remain benign; failed removals are logged and later candidates continue. The public signature and startup/updater call sites remain unchanged.
- [ ] AC-QA-1: `mergeDicts` retains its outer-copy and nested-dict behaviour, scalar replacement, list prepend/append order, duplicate removal (including unhashable items), and iterative deep-merge handling.
- [ ] AC-QA-2: Characterisation tests cover boundary and failure paths; deliberate mutations prove new assertions fail for the intended reasons and pass after restoration.
- [ ] AC-SEC-1: No new private paths, settings values or credentials are logged or sent outside the process.
- [ ] AC-SIMP-1: Extract private purpose-specific helpers without changing public names, dependencies, schema or unrelated legacy naming conventions.
- [ ] AC-REL-2: Both S3776 findings close on a fresh-clone exact-master Sonar scan, with no new S3776 finding in extracted helpers. Focused tests, full gate, two independent clean reviews and hosted checks pass.

## TDD note

The refactor preserves existing behaviour, so the measured S3776 findings are the structural red. Characterisation tests should pass on the baseline; deliberate mutations provide behavioural red evidence before extraction.
