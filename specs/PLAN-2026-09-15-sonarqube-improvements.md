# PLAN 2026-09-15: improve the value of SonarQube results

## Problem

The self-hosted SonarQube analysis of `couchpotato` is current at
`165e64019150e604be6f3dc6f85f03bb81afe9d0`, but its default quality gate is
red on 56 findings labelled as new code. The measurement is hard to interpret:
the inherited new-code definition is `PREVIOUS_VERSION`, while every recorded
analysis reports project version `1.0.0`.

The wider backlog contains 1,129 open findings. Its largest groups are not a
safe work queue: some describe an unserved legacy JavaScript layer, some are
static-analysis false positives around Jinja or Alpine markup, and the
cognitive-complexity findings cluster in the database, migration, scanner, and
renamer paths where no-behaviour refactors carry unusually high data-loss risk.

The useful work is therefore to improve the truthfulness of the measurement
and fix small, evidenced defect classes rather than optimise the dashboard.

## Proposed scope

1. Make the new-code boundary explicit and reproducible without moving the
   SonarQube scan into CI or turning it into a merge gate.
2. Prevent new unexplained Playwright fixed waits with an enforced exemption
   mechanism, and replace only the three currently evidenced timing guesses
   with observable conditions. Retain bounded waits that prove non-occurrence
   and forced actions that deliberately exercise application-side guards.
3. Fix the late-bound `media_type` callbacks registered in
   `couchpotato/core/media/_base/media/main.py`, with tests proving each
   registered media type remains bound to its own route.
4. Specify BeautifulSoup parsers in small provider groups, guarded by parsing
   tests that protect existing behaviour on representative malformed input.
5. Extend the existing false-green guard to catch conditional E2E bodies that
   can skip their named behavior while still passing.
6. Adjudicate only evidenced false positives. The current `Web:S5254` finding
   is one candidate: `base.html` already has `<html lang="en">`, and SonarQube
   points at a CSS comment that mentions `<html>`.

## Explicit non-goals

- Making SonarQube a CI, release, or merge gate.
- Exposing the private SonarQube instance outside the internal network.
- Lowering the count by disabling rules or bulk-dismissing findings.
- Mechanical cognitive-complexity or naming refactors.
- Editing dead legacy JavaScript merely to clear findings; delete it only when
  the corresponding migrated UI proves it is unserved.
- Raising aggregate coverage indiscriminately; tests should target risky or
  changed behaviour.
- Reworking the provider-controlled bracket parser: commit `de6e6436d` / PR
  #326 already replaced the reachable quadratic expression with a linear scan
  and added equivalence and adversarial tests. Other regex findings require a
  fresh, separately scoped reachability assessment.

## Evidence captured before planning

- SonarQube 26.9.0 reports the latest analysis as successful and exactly at
  repository `HEAD`.
- Overall results: 55.6% coverage, 1.8% duplicated lines, 23 bugs, 1,106 code
  smells, zero vulnerabilities, and zero security hotspots.
- New-code results: 86.4% coverage, 0.06003% duplicated lines, and 56 open
  findings (55 code smells and one bug).
- Anonymous access to the internal instance returns HTTP 401. The project's
  `public` visibility flag is instance-local and is not evidence of public
  network exposure.
- Prior adjudication is recorded in
  `specs/PLAN-2026-09-07-sonarqube-slices.md` and
  `specs/PLAN-2026-09-07-post-sonarqube-followups.md`; do not re-open those
  decisions without new evidence.

## Acceptance criteria

### Scanner truthfulness and security

- **AC-OPS-1:** `make sonar` captures one exact 40-character commit SHA before
  coverage and passes that same value as `sonar.projectVersion`. Under the
  inherited `PREVIOUS_VERSION` policy, “new code” means changes since the
  preceding successful analysed commit.
- **AC-OPS-2:** Before coverage and again before upload, the scan refuses a
  non-`master`, dirty, or changed-HEAD checkout. A preflight failure performs
  no coverage generation, scanner invocation, network request, or freshness
  stamp update.
- **AC-OPS-3:** After scanner upload, the target reads the submitted CE task
  identity from `.scannerwork/report-task.txt` and polls it with a documented
  bounded interval and timeout using only the analysis token. It atomically
  updates `.sonar-last-analysis` only after CE reports `SUCCESS`; `FAILED`,
  `CANCELED`, malformed data, authentication failure, or timeout preserves the
  prior stamp and prints an actionable recovery message. Quality-gate status
  never controls the command result.
- **AC-OPS-4:** `make sonar-staleness` remains credential-free, network-free,
  and non-blocking. It separately warns when analysed files are dirty and must
  not claim that line numbers describe the current tree in that state.
- **AC-SEC-1:** Routine scanning continues to use only `SONAR_TOKEN` from
  `~/.sonar-token`, never the administrator credential. The preflight accepts
  analysis-token prefixes `sqa_` and `sqp_`, rejects an administrator `squ_`
  token before coverage, and never places a credential in argv, output, the
  freshness stamp, or committed files.
- **AC-SEC-2:** Commit metadata passed to the scanner is the validated full SHA
  only. It cannot contain branch text, shell metacharacters, usernames, paths,
  hosts, media data, or secrets.
- **AC-SEC-3:** No slice adds SonarQube or either credential to CI, changes the
  quality gate into a merge/release gate, adds an external listener or tunnel,
  or weakens anonymous access. Existing exclusions for personal-state,
  report, worktree, and vendored paths remain effective.
- **AC-QA-1:** Scanner tests use stubbed coverage, scanner, and CE responses to
  prove distinct commits produce distinct versions; every terminal CE state,
  timeout, malformed response, dirty tree, branch mismatch, and HEAD change is
  exercised without using a real credential or network service.
- **AC-PROD-1:** A successful clean-master validation scan proves Sonar reports
  the same full SHA as both revision and project version, CE status is
  `SUCCESS`, coverage is present and plausible, and the local stamp matches.

### Playwright synchronization and false-green prevention

- **AC-DESIGN-1:** The first synchronization slice changes only
  `review-queue.a11y.spec.ts:608` and the redundant `networkidle` waits at
  `accessibility.a11y.spec.ts:386` and `:913`. No production UI or copy changes
  are part of this slice.
- **AC-DESIGN-2:** The 640px reflow test retries the actual visible outcome:
  document width fits the viewport and the focused review control remains
  within it. The two removed `networkidle` calls retain their stronger
  route-specific readiness checks for the Settings tablist and populated
  Wanted movie count.
- **AC-A11Y-1:** Every changed accessibility scan or layout measurement first
  asserts that its state-specific content is visible and populated. Withholding
  that readiness must make the focused test fail rather than scan an absent or
  hidden subtree.
- **AC-A11Y-2:** Existing bounded waits that prove non-occurrence or wait for a
  measured transition remain documented and unchanged. Existing forced actions
  that bypass Playwright actionability to exercise focusable `aria-disabled`
  and duplicate-request guards also remain unchanged.
- **AC-QA-2:** `scripts/check_test_traps.py` rejects every new executable
  `waitForTimeout` unless the call carries a checked, non-empty exemption that
  names the forbidden event or transition being observed. Unit fixtures prove
  rejection, valid exemption, malformed/empty exemption rejection, and
  anti-vacuity. Previously adjudicated waits need not be rewritten in this
  slice.
- **AC-QA-3:** The false-green guard catches click-only conditional bodies and
  conditionally swallowed response assertions, while allowing idempotent
  teardown and conditions whose branches both assert. Existing cases in
  `interactions.e2e.spec.ts` are either made unconditional or renamed/removed
  so every test fails when its named behavior is absent.
- **AC-A11Y-3:** Changed specs pass Chromium and, where accessibility or reflow
  behavior is touched, the accessibility project and relevant phone-width
  coverage. Existing focus, live-region, light/dark-theme, and non-vacuity
  assertions remain intact.

### Callback correctness

- **AC-QA-4:** A focused Python test registers at least two synthetic media
  types, retains the stored callbacks until registration completes, and proves
  both directions for `*.list`, `*.available_chars`, `*.watched`,
  `*.unwatched`, `*.watch_history`, and `*.delete`: each callback receives its
  own type and never the other type. Restoring any late-bound closure makes the
  test fail.
- **AC-SIMP-1:** The production change uses one small shared callback binder so
  the route type cannot be replaced by query/body keywords or positional
  arguments. It introduces no registration abstraction, new dependency, or
  unrelated refactor. A default-argument-only binding was rejected during
  review because keyword-only defaults remained request-overridable while
  positional-only defaults changed the old callback contract. The issue is
  described as a latent wrong-results defect; deletion is not described as a
  present data-loss defect because its handler does not consume `type`.

### Parser determinism

- **AC-QA-5:** Every production `BeautifulSoup(...)` invocation names a parser
  explicitly. An AST-based repository guard discovers calls dynamically,
  asserts at least one call is found, and fails on a newly implicit parser.
- **AC-PROD-2:** Each provider group changed is driven through its real parsing
  method with representative ordinary and malformed synthetic HTML. Extracted
  identifiers, titles, links, sizes, or candidate results match pre-change
  behavior; testing BeautifulSoup directly is insufficient.
- **AC-SEC-4:** Parser selection uses an installed, pinned parser, preserves an
  existing explicit parser choice absent contrary evidence, and does not log or
  return response bodies, credentials, headers, private paths, library titles,
  or watch history when parsing fails.
- **AC-SIMP-2:** Parser selection changes no scraping logic and uses one
  repository-wide recurrence guard rather than one guard per provider. It may
  be delivered in provider-sized groups when fixtures expose different parsing
  contracts.

### SonarQube adjudication and global constraints

- **AC-A11Y-4:** Before adjudicating `Web:S5254`, a fresh successful analysis
  is matched to the implementation commit and a rendered-page test proves
  `document.documentElement.lang === "en"`. The exact issue must still point
  to non-rendered CSS-comment text, not the root element.
- **AC-SEC-5:** Only that exact issue may be changed under this plan. The admin
  token is loaded from the owner-only `~/.sonar-admin-token`, its assignment
  value—not the whole line—is sent outside argv/output, and the transition is
  re-fetched and verified. Its comment cites code/test evidence and an expiry
  condition without credentials, LAN details, private paths, or personal data.
- **AC-A11Y-5:** No ARIA role, native element, live-region behavior, keyboard
  interaction, focus behavior, or mobile layout changes solely to clear a
  finding. Existing `Web:S6819` decisions remain closed absent new behavioral
  evidence.
- **AC-SIMP-3:** Scanner metadata, synchronization, false-green prevention,
  callback binding, parser selection, and issue adjudication remain separate,
  independently reviewable slices. No slice depends on a target Sonar score.
- **AC-SIMP-4:** No slice changes cognitive-complexity findings, naming, dead
  legacy JavaScript, aggregate coverage targets, vendored CodernityDB, shipped
  public app keys, or the documented accepted E2E coverage gap.
- **AC-QA-6:** Each slice passes focused tests, `make check-traps`, and relevant
  lint/browser checks. The final combined local state passes the repository's
  prescribed Python, UI-unit, Chromium, and accessibility verification before
  it is eligible for delivery.

## Implementation sequence

Each item is an independent review unit. External delivery is not implied by
this checklist; commits, pushes, PRs, and SonarQube state changes occur only
within the authority explicitly granted by the owner.

- [ ] **T1 — truthful scan completion and versioning** — state: awaiting-ci #354
  (implementation and local review clean; AC-PROD-1 awaits a post-commit clean
  master scan). Add
  clean-master/stable-HEAD preflight, full-SHA project versioning, CE completion
  polling, atomic freshness stamping, dirty-tree staleness reporting, and
  credential-boundary regression tests. Covers AC-OPS-1..4, AC-SEC-1..3,
  AC-QA-1, AC-PROD-1.
- [ ] **T2 — narrow synchronization repair** — state: awaiting-ci #354. Replaced the one
  unexplained reflow wait and two redundant `networkidle` waits with observable
  conditions. Covers AC-DESIGN-1..2, AC-A11Y-1..3.
- [ ] **T3 — recurring E2E false-green mechanisms** — state: awaiting-ci #354. Enforced
  syntax-aware fixed-wait exemptions and conditional-body detection, then
  repaired or removed the exposed vacuous tests.
  Covers AC-QA-2..3 and AC-A11Y-2..3.
- [ ] **T4 — bind media callback types** — state: awaiting-ci #354. Added the two-type
  regression test and a small shared route binder. Covers AC-QA-4, AC-SIMP-1.
- [ ] **T5 — deterministic provider parsing** — state: awaiting-ci #354. Added the AST
  recurrence guard, characterize provider parsing, and explicitly select the
  pinned parser in provider-sized groups. Covers AC-QA-5, AC-PROD-2,
  AC-SEC-4, AC-SIMP-2.
- [ ] **T6 — adjudicate the confirmed HTML-language false positive**
  *(needs: T1)* — state: queued. After a fresh successful scan and rendered
  proof, change only the exact `Web:S5254` issue and verify the transition.
  Covers AC-A11Y-4..5, AC-SEC-5.

All tasks also cover AC-SIMP-3..4 and AC-QA-6.

## Conductor log

- 2026-09-15: plan cycle complete with security, QA, simplicity, product,
  design, accessibility, and operability coverage. Removed already-completed
  regex work (`de6e6436d`), split the work into independent tasks, and started
  T1. The old post-SonarQube plan has a pre-existing user modification and is
  outside this plan's write scope. No external delivery is authorised.
- 2026-09-15: T1 reached a clean local Harness review after four remediation
  mechanisms: fresh CE-task handoff and post-scan checkout validation;
  credential redirect/proxy/environment isolation; analysis-root drift
  synchronization; and ambient Git repository isolation. Focused suite: 50
  passed. AC-PROD-1 remains pending because the truthful scanner correctly
  refuses this uncommitted checkout. T2 started independently.
- 2026-09-15: Final clean-agent review hardened T1's credential boundary as a
  mechanism after repeated Node/npm preload findings. npm now installs the
  pinned scanner tokenlessly in an isolated temporary project with lifecycle
  scripts disabled and distinct empty user/global configs; only a direct Node
  launch receives the analysis token. The complete security-critical install
  command is pinned by tests, a malicious `.npmrc` execution test stays inert,
  and a real tokenless install verified the pinned package entry point. The
  scanner/Git-boundary suite passed 59 tests and two independent final reviews
  were clean.
- 2026-09-15: T2 completed and passed the Harness security, QA,
  accessibility/design/product, architecture, and fresh-verification lenses.
  The two complete affected accessibility specs passed 44/44 with no skips;
  the three edited tests also passed 9/9 across three repetitions, and the
  related 393px mobile reflow test passed. No review findings survived.
- 2026-09-15: T4 completed after review exposed two forms of caller rebinding
  that default-argument captures could not safely cover together. A shared
  seven-line binder now preserves the old positional-argument behavior and
  makes the registered route type win over request keywords. Security,
  QA/product, and fresh verification are clean; the fresh adjacent suite
  passed 80 tests.
- 2026-09-15: Targeted mutation testing of T4 initially killed 3/4 binder
  mutants. The survivor removed ordinary forwarded request fields, exposing a
  missing assertion; after strengthening the regression test, all 4/4 mutants
  were killed. The temporary mutation target was then restored, leaving the
  repository's established mutation scope unchanged.
- 2026-09-15: T5 completed after review hardened the recurrence guard against
  invalid `builder=` strings and assignment/chained aliases, and required the
  pre-existing HDTrailers matching-heading failure to be characterized rather
  than hidden behind a no-match fixture. All 17 production calls are explicit;
  the final parser/provider suite passed 73 tests and all review lenses are
  clean.
- 2026-09-15: T3 completed after repeated Harness review converted recurring
  findings into mechanisms: the E2E trap checker now uses TypeScript symbols
  and lexical scope, fixed-wait exemptions use stable structural identities,
  and CI/local verification installs the pinned parser dependency before the
  gate. External trailer traffic and settings persistence are intercepted,
  exact movie IDs are asserted, and the irreducibly non-hermetic Add Movie
  block was removed with its coverage claim. Final focused evidence was clean:
  284 checker tests, 27 Chromium interaction tests, 214 UI unit tests, and the
  affected accessibility checks; security/product and operability reviews
  reported no findings.
- 2026-09-15: Final combined verification passed: 4,178 Python unit tests, 42
  Python integration tests, 214 UI unit tests, and 282 Playwright tests across
  Chromium, accessibility, and mobile, with Ruff, the 317-file trap gate, UI
  conformance, and diff hygiene clean. T1's post-commit live validation and T6
  remain deliberately pending until the work is committed on clean `master`.
- 2026-09-16: Opened PR #354 after the mandatory pre-push gate passed 4,184
  Python unit, 42 integration, 214 UI unit, 176 Chromium, 2 isolation, 10
  mobile, and 96 accessibility tests. T1 through T5 are awaiting CI. T1's live
  clean-`master` proof and dependent T6 remain post-merge work.
- 2026-09-16: PR #354's first Python CI run exposed a clean-runner dependency
  gap: 73 TypeScript-backed trap-checker tests failed because that job had not
  installed the pinned TypeScript package. Added a load-bearing workflow-order
  assertion first, observed it fail, then made the Python job set up Node and
  run the script-disabled npm install before pytest. The complete 284-test trap
  checker suite is green locally; CI re-verification is pending.
- 2026-09-16: The second Python CI run loaded TypeScript and reduced the failure
  to one host-dependent fixture. Its missing-Node test removed only the first
  matching `PATH` entry, while the GitHub runner exposes a fallback Node
  installation. Replaced that subtraction with a constructed empty executable
  directory; the focused test and complete 284-test checker suite are green.
