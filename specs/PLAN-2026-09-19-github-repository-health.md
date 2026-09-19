# PLAN: GitHub repository health cleanup

## Objective

Remove the duplicate GPL license presentation from GitHub while preserving the
canonical GPL-3.0 license, verify the repository's CodeQL configuration from
GitHub's APIs and workflow evidence, and use the resulting merge to begin the
next beta after promoting `v3.130.0-beta.1` to production.

## Acceptance criteria

- [ ] AC-PROD-1: `LICENSE` remains the sole root GPL-3 document, retains its
      canonical content, and GitHub detects it as GPL-3.0.
- [x] AC-PROD-2: The README license link points to `LICENSE` and preserves the
      original author's copyright notice and GPL-3.0-or-later grant from the
      removed legacy copy.
- [x] AC-QA-1: Focused tests prevent another exact or lightly edited root GPL-3
      document under any filename, modified canonical license content, or a
      stale README link from returning.
- [x] AC-QA-2: The focused test, Ruff, and the repository's relevant full
      checks pass.
- [x] AC-QA-3: At least two independent local reviewers report no real findings
      before the branch is pushed.
- [ ] AC-OPS-1: Hosted CI passes and the pull request is merged.
- [ ] AC-OPS-2: The merge publishes a new beta release.
- [ ] AC-SEC-1: CodeQL's latest master analyses are successful with no analysis errors;
      any GitHub configuration banner is resolved or documented with evidence
      if it is external/stale rather than repository-controlled.

## Tasks

- [x] TASK-1: Promote `v3.130.0-beta.1` to stable `v3.130.0` and verify the
      release and image promotion workflow.
- [x] TASK-2: Add a failing repository-metadata regression test.
- [x] TASK-3: Remove `license.txt` and repoint the README to `LICENSE`.
- [x] TASK-4: Run focused and full local verification.
- [x] TASK-5: Run the required independent local review gate and address every
      real finding.
- [ ] TASK-6: Push, open the PR, monitor hosted review/CI, merge, and verify the
      next beta release.
- [ ] TASK-7: Reconcile CodeQL configuration and current GitHub service state.
