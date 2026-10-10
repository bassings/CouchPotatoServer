# Settings script critical complexity, 2026-10-10

## Objective

Close the three critical `javascript:S3776` findings in
`couchpotato/ui/templates/partials/settings/scripts.html` while preserving
settings loading, tab and group ordering, and save confirmation behaviour.
This follows the TMDB provider batch. Release and deployment are excluded.

## Acceptance criteria

1. Initialisation registers watchers once, loads settings and version data,
   builds the same tab order, and reports settings-load failures visibly.
2. Group selection preserves hidden and advanced section rules, tab remapping,
   combined Search Settings placement, category labels and ordering.
3. Saves preserve failed-response handling, server-returned values, masked
   secret handling, dirty state, restart flags and truthful announcements.
4. Behaviour tests cover the important boundary and failure cases before the
   refactor. Deliberate mutations fail those tests and restoration passes.
5. Focused and full local checks, two independent reviews, PR CI and cloud
   review pass. An exact clean-master SonarQube scan confirms the three
   findings closed, identifies new findings and checks the reporting gate.

## Tasks

- [x] S1 Characterise existing behaviour and add contracts
- [x] S2 Refactor the three functions without changing results or side effects
- [x] S3 Verify, mutate and obtain two clean independent reviews
- [ ] S4 Deliver PR through CI, cloud review and merge
- [ ] S5 Confirm exact-master SonarQube result

## Conductor log

- 2026-10-10: Three critical findings are in `init`, `getTabGroups` and
  `saveSingle`. Existing browser tests cover some watcher, tab and rewritten
  setting behaviour. The save path handles rejected writes and secrets, so
  new contracts must pin its failure and boundary behaviour before extraction.
- 2026-10-10: Added five browser contracts on the original implementation:
  tab/version loading, visible load failure, combined and category ordering,
  refused save state, and secret-safe successful save. All five passed.
  Deliberate mutations to preferred tab order, combined grouping, refusal
  handling and secret masking each applied, failed the targeted browser test,
  and passed after restoration. The source SHA-256 was restored exactly.
- 2026-10-10: Extracted version loading and tab-order computation from
  `init`, per-section grouping from `getTabGroups`, and response parsing and
  accepted-save state changes from `saveSingle`. All 19 focused settings
  browser tests passed after the extraction. The repository test-trap guard
  passed across 392 files with the project virtual environment. A first run
  using system Python failed because PyYAML was absent from that interpreter;
  no repository check was weakened.
- 2026-10-10: Three post-refactor mutations removed the calls to the new tab,
  group and accepted-save helpers in turn. Each applied, failed its targeted
  browser contract and passed after restoration. The refactored source
  SHA-256 was restored exactly.
- 2026-10-10: The full local gate passed: 4,905 Python unit, 42 integration,
  311 JavaScript unit, 232 desktop, two browser-isolation, 24 phone and 126
  accessibility tests. The guard and conformance checks passed as well. Two
  independent code-reviewer agents examined the implementation, tests and
  spec and found no material issue. PR delivery and exact-master scan remain.
