# PLAN: GitHub repository health cleanup

## Objective

Remove the duplicate GPL license presentation from GitHub while preserving the
canonical GPL-3.0 license, verify the repository's CodeQL configuration from
GitHub's APIs and workflow evidence, and use the resulting merge to begin the
next beta after promoting `v3.130.0-beta.1` to production.

## Acceptance criteria

- [x] AC-PROD-1: `LICENSE` remains the sole root GPL-3 document, retains its
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
- [x] AC-OPS-1: Hosted CI passes and the pull request is merged.
- [x] AC-OPS-2: The merge publishes a new beta release.
- [ ] AC-SEC-1: CodeQL's latest master analyses are successful with no analysis errors;
      any GitHub configuration banner is resolved or documented with evidence
      if it is external/stale rather than repository-controlled.
- [x] AC-CQL-1: The advanced workflow scans exactly `python`, canonical
      `javascript-typescript`, and `actions`, while preserving the protected
      check names `Analyze (python)` and `Analyze (javascript)` and adding
      `Analyze (actions)`.
- [x] AC-CQL-2: A focused parsed-YAML test pins the exact language/check-name
      mapping, matrix wiring, least-privilege permissions, triggers, action
      versions, explicit categories, and `fail-fast: false`; independent
      mutations prove each critical mapping assertion is load-bearing.
- [x] AC-CQL-3: The change adds no default setup, query pack, secret, broader
      permission, dependency, build mode, branch-protection mutation, or
      historical-analysis deletion.
- [ ] AC-CQL-4: Hosted PR and exact-master runs publish all three successful
      analyses. The Code Scanning API reports the merge SHA, no analysis error,
      and non-zero rule counts for Python, JavaScript/TypeScript, and Actions.
- [ ] AC-CQL-5: The Tools page shows all three configurations current and no
      out-of-date warning. Any new Actions alert is adjudicated individually;
      alert history and the zero-open-alert baseline are not silently erased.
- [ ] AC-CQL-6: After the first successful exact-master `Analyze (actions)`
      context exists, add that exact context to `master` branch protection and
      verify Python, JavaScript, and Actions analysis failures all block future
      merges. This admin mutation is deliberately deferred until GitHub knows
      the new context name.
- [ ] AC-CQL-7: Reinspect every CodeQL configuration after the canonical run.
      If either the old advanced `/language:javascript` identity or disabled
      default-setup identities remain stale, retire only a precisely identified
      superseded configuration after proving it has no open-alert ownership;
      never bulk-delete analyses or erase alert history to clear the banner.

## Tasks

- [x] TASK-1: Promote `v3.130.0-beta.1` to stable `v3.130.0` and verify the
      release and image promotion workflow.
- [x] TASK-2: Add a failing repository-metadata regression test.
- [x] TASK-3: Remove `license.txt` and repoint the README to `LICENSE`.
- [x] TASK-4: Run focused and full local verification.
- [x] TASK-5: Run the required independent local review gate and address every
      real finding.
- [x] TASK-6: Push, open the PR, monitor hosted review/CI, merge, and verify the
      next beta release.
- [ ] TASK-7: Reconcile CodeQL configuration and current GitHub service state —
      in progress. Preserve Python, refresh the stale canonical JavaScript/
      TypeScript and Actions categories, and retain protected check names.

## Conductor log

- 2026-09-19: The duplicate GPL repair merged as PR #383, GitHub now presents
  one GPL-3 license, stable `v3.130.0` was released, and beta
  `v3.131.0-beta.1` started.
- 2026-09-19: CodeQL's error banner was traced to four failed, zero-result
  legacy default-setup analyses. Those exact deletable analyses were removed;
  a fresh advanced-workflow run succeeded for Python and JavaScript with no
  open alerts. The remaining warning identifies two successful but stale
  default-setup categories (`actions` and `javascript-typescript`) last scanned
  at `0432302b`, while the default-setup API itself says `not-configured`.
- 2026-09-19: TASK-7 planning found Python is already current and healthy. The
  safe repair uses canonical scan identifiers for Python, JavaScript/TypeScript,
  and Actions, but separates them from stable display labels because branch
  protection requires exact contexts `Analyze (python)` and
  `Analyze (javascript)`. Security, QA, operability, product, and simplicity
  lenses prohibit deleting alert history or enabling a second CodeQL setup.
- 2026-09-19: TASK-7's focused guard failed on the old two-language matrix,
  then passed with the canonical three-language mapping. Independent mutations
  proved it rejects a missing Python scan, a renamed protected JavaScript
  context, category/display-name miswiring, and weakened upload permission.
  The fast gate passed 4,371 unit tests (14 skipped, 5 expected failures), 42
  integration tests, 214 UI-unit tests, Ruff, conformance, and the 327-file
  trap scan. Review then removed an optional YAML import that could have made
  the guard skip and updated the development-process language inventory to
  include GitHub Actions.
