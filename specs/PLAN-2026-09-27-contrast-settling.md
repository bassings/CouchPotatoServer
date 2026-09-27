# Settled colour-contrast gate

## Goal

Make the Wanted-page colour-contrast check measure the rendered state after finite visual transitions, while continuing to fail on real WCAG 2.2 AA contrast violations. PR #473's hosted accessibility job failed on transition-frame ratios of 4.24:1 and 4.45:1, then passed on retry with no source change. `specs/PLAN-2026-09-27-scanner-scan-debt.md` is the format exemplar.

## Acceptance criteria

- [ ] AC-A11Y-1: The existing real-page colour-contrast check waits for visible finite transitions to settle before axe measures the Wanted page.
- [ ] AC-A11Y-2: The check still fails on a genuinely settled contrast ratio below 4.5:1 and does not suppress axe violations or relax `--fail-on-flaky-tests`.
- [ ] AC-QA-1: A deliberate animated low-contrast state proves the wait is load-bearing: the check fails without it and passes once it is restored.
- [ ] AC-REL-1: Focused Playwright coverage, full local gate, two fresh independent clean reviews and hosted checks pass; merge is followed by exact-master Sonar verification.
