# Browser test guard complexity, 2026-10-10

## Objective

Close the three critical `javascript:S3776` findings in
`scripts/check_e2e_test_traps.mjs` without weakening detection of browser tests
that can pass without checking the intended behaviour. Include the related
`javascript:S3358` nested conditional if the same extraction resolves it.

## Acceptance criteria

1. Preserve wait alias discovery, including destructuring, assignment and
   bound methods, across the existing three collection passes.
2. Preserve guard, swallowed response and live region findings, including
   source line, test title, wait context and finding kind in JSON output.
3. Add focused contract tests for any uncovered branches before changing the
   guard. Confirm each new test fails under a deliberate mutation, then passes
   after restoration. Compare the old and new guard output on a varied corpus.
4. Close the three identified critical findings with no replacement critical
   finding. Pass focused tests, full `make verify`, two independent local
   reviews, PR CI and cloud review, then merge and scan exact clean `master`.
   Record any new findings and the reporting gate. No production deployment.

## Tasks

- [x] G1 Characterise current guard output and assess existing contracts
- [x] G2 Extract focused helpers and verify equivalent output
- [x] G3 Complete full local gate and independent reviews
- [x] G4 Deliver PR through CI, cloud review and merge
- [x] G5 Confirm exact-master SonarQube result

## Conductor log

- 2026-10-10: Existing guard unit tests cover wait aliases, hoisted visibility
  probes, swallowed-response guards, live region assertions and TypeScript
  compiler boundaries. Extracted collection and finding helpers. A baseline
  copy and the refactored script produced exactly equal JSON on all 43 tracked
  browser test files plus five targeted wait, response, guard and live region
  examples. Focused tests and mutation proof are running.
- 2026-10-10: All 324 guard unit tests passed. Existing contracts covered the
  extracted branches, so no duplicate test was added. Three deliberate
  mutations disabled wait alias discovery, visibility guard detection and
  swallowed response expression detection in turn. Each mutation applied,
  made its targeted test fail, and passed again after restoration. The
  repository's trap check is running; the full gate and review remain open.
- 2026-10-10: The repository trap check passed across 391 files. The complete
  local gate passed: 4,905 Python unit, 42 integration, 311 JavaScript unit,
  227 desktop, 2 isolation, 24 phone and 126 accessibility tests. Ruff and
  UI conformance checks also passed. Two independent code-reviewer agents
  found the guard extraction clean. PR delivery and exact-master analysis
  remain open.
- 2026-10-10: PR #536 passed CI and cloud review and merged as `63e860bdb`.
  The exact clean-master scan closed the three critical `javascript:S3776`
  issues and the related `javascript:S3358` issue. Open findings moved from
  606 to 602, critical from 132 to 129, with no new findings. Coverage was
  66.5%, bugs, vulnerabilities and hotspots were zero, and the reporting
  gate was green.
