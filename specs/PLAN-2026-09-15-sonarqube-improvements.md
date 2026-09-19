# PLAN 2026-09-15: improve the value of SonarQube results

> **Lifecycle: active**
> **Legacy runtime: retired; `/old/*`: redirect-only.**

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
- Mechanical cognitive-complexity or naming refactors, except the exact
  `CouchPotato.py` regression introduced by T8 and bounded by T9's behavioral
  tests; this does not reopen the existing complexity backlog.
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
- **AC-SIMP-4:** No slice changes cognitive-complexity findings, naming,
  aggregate coverage targets, vendored CodernityDB, shipped
  public app keys, or the documented accepted E2E coverage gap. The sole
  exception is T9's bounded repair of the exact `CouchPotato.py` finding that
  T8 introduced; it must preserve T8 behavior and may not expand into backlog
  complexity cleanup. T14 may delete the complete dead legacy JavaScript tree
  only after proving the tree has no production route, template or build
  consumer; it must not refactor or selectively preserve that unserved code.
- **AC-QA-6:** Each slice passes focused tests, `make check-traps`, and relevant
  lint/browser checks. The final combined local state passes the repository's
  prescribed Python, UI-unit, Chromium, and accessibility verification before
  it is eligible for delivery.

### Windows hidden-attribute failure semantics

- **AC-QA-7:** A Windows `GetFileAttributesW` failure sentinel (`-1`) is
  treated as "not hidden" under both normal and optimized (`python -O`)
  execution. Tests also retain the ordinary hidden-bit and non-hidden cases.
- **AC-SEC-6:** The file-browser result must not depend on an `assert`, because
  optimized Python removes assertions and would otherwise classify a failed
  lookup as hidden. The repair remains local to attribute interpretation and
  does not expose the requested path or change traversal handling.
- **AC-SIMP-5:** Replace assertion-based control flow with one explicit
  sentinel check; do not refactor directory enumeration or Windows imports.

### Startup OSError handling

- **AC-OPS-5:** The process entry point treats `OSError(errno.EINTR, ...)` as
  an interrupted shutdown, while any other `OSError` is logged when a loader
  exists and re-raised so startup cannot fail silently.
- **AC-QA-8:** Focused tests execute the entry-point control flow with a fake
  loader and prove both the EINTR and non-EINTR branches. A mutation that
  restores the broad early `except OSError: pass` must fail the non-EINTR test.
- **AC-SEC-7:** A non-EINTR `OSError` is surfaced without copying its filename
  or traceback into the unfiltered startup error handler or the final raised
  exception. Tests use a private media-path sentinel and capture real logging.
- **AC-SIMP-6:** Keep one `OSError` handler and preserve the existing
  `KeyboardInterrupt`, `SystemExit`, and generic-exception behavior; do not
  change loader initialization, daemonization, or restart behavior.
- **AC-OPS-6:** Extract the startup `OSError` policy into bounded helpers while
  preserving the exact exit, logging, and path-redaction behavior delivered by
  T8, including quiet EINTR handling and the stderr fallback.
- **AC-QA-9:** Exercise the extracted non-EINTR policy directly and retain the
  entry-point integration coverage. Reversing its EINTR predicate must fail
  both the direct non-EINTR test and the EINTR integration test.
- **AC-SIMP-7:** Close the `python:S3776` issue introduced when T8 made the
  entry point testable, without moving excessive complexity into another
  helper or weakening the privacy-safe error boundary.
- **AC-QA-10:** A focused AST regression rejects nested conditional
  expressions in the path-safe startup-error helper and fails against the
  exact compact expression reported by SonarQube.
- **AC-SIMP-8:** Replace only the nested conditional reported as
  `python:S3358` with explicit branches; do not change errno fallback,
  logging, exit, or path-redaction behavior.
- **AC-QA-11:** An iTunes automation regression with more configured URLs than
  enable flags proves a missing flag disables that URL instead of raising
  outside the provider's error boundary. Reversing the corrected bounds
  predicate must fail the test.
- **AC-OPS-7:** Keep processing enabled iTunes feeds while safely skipping
  URLs whose enable flag is missing, and remove the redundant always-true XML
  root check reported as `python:S5727` without changing feed parsing.
- **AC-QA-12:** Provider-level regressions prove missing enable flags fail
  closed for iTunes, IMDb watchlists, and Letterboxd without suppressing an
  earlier enabled entry. Reversing the shared bounds predicate must fail.
- **AC-SIMP-9:** Replace the recurring direct enable-list indexing class with
  one shared bounds helper used by all three affected automation providers.
- **AC-QA-13:** The shared enable-list helper follows the repository's Python
  naming convention, all three providers import that exact symbol, and their
  fail-closed behavior remains covered.

### Standalone health-probe reliability

- **AC-QA-14:** The retained `simple_healthcheck.py` runs under Python 3,
  compares the response body as bytes, requires HTTP 200 plus CouchPotato page
  identity, bounds the response prefix to 64 KiB, caps each network operation
  at the five-second latency threshold, and stops before the next body read
  once that threshold is observed. Focused tests cover the current sign-in
  page, 404/503 responses, wrong content, connection and mid-read protocol
  failures, the 64 KiB cap, response closure, latency, and both process exit
  codes. An already-blocking socket operation retains its own capped timeout;
  this is a bounded health probe, not a hard real-time deadline.
- **AC-SEC-8:** The probe requests only the root page. It no longer calls the
  API-key endpoint and does not print exception details that can contain local
  network or proxy information.
- **AC-OPS-8:** The probe remains a standalone process with success/failure
  exit semantics. Deletion remains separately gated on REMEDIATION AC-OPS-12's
  production grep; repairing it does not claim that external check occurred.
- **AC-SIMP-10:** Replace the five overlapping `unittest` methods with one
  request and explicit failure collection; introduce no dependency or service
  endpoint.

### Final reliability-finding adjudication

- **AC-QA-15:** Every SonarQube issue classified as a bug after T15 has a
  call-site review and specific executable or source evidence. A finding is
  accepted only when that evidence shows the reported failure cannot escape
  its intended boundary, has no runtime effect, or is the test mechanism
  itself.
- **AC-OPS-9:** Record the exact `master` revision, analysis timestamp, quality
  gate, aggregate measures, and the complete surviving bug inventory. Do not
  change issue status in SonarQube; that remains an owner-controlled action.
- **AC-SIMP-11:** Do not churn production code merely to lower the count. The
  two harmless parameter-shadowing findings remain named cleanup debt rather
  than being presented as reliability repairs.

### Maintainability backlog continuation

- **AC-QA-16:** Put.io completion-age comparisons parse the API's naive
  `finished_at` value as UTC and compare it with an aware UTC current time.
  Focused tests prove a completion younger than five minutes remains `busy`
  while completions exactly five minutes old and older are `completed`;
  restoring a naive current time must fail rather than silently passing the
  regression.
- **AC-OPS-10:** The repair preserves the existing five-minute race window,
  transfer filtering, download-disabled behavior, and in-progress download
  list behavior. It introduces no local-time or host-timezone dependency.
- **AC-SIMP-12:** Keep the timezone repair local to the Put.io age comparison;
  do not refactor unrelated downloader control flow merely to reduce the
  SonarQube count.
- **AC-QA-17:** uTorrent token acquisition accepts the byte response returned
  by `urllib`, extracts the contents of the exact `div#token` element rather
  than a preceding decoy element, and rejects a response without that element
  with a stable explicit error. A focused regression must fail against the
  current string-regex-on-bytes implementation.
- **AC-OPS-11:** The token response is closed on both successful and malformed
  responses. Token parsing remains compatible with the existing uTorrent Web
  UI endpoint and does not change authentication or request refresh behavior.
- **AC-SEC-9:** A malformed token response must not copy its body, token-like
  values, credentials, URL, or local-network details into the exception or a
  log message.
- **AC-SIMP-13:** Replace the super-linear token regex with a bounded standard-
  library HTML parser local to the uTorrent adapter; add no dependency and do
  not refactor unrelated downloader behavior.
- **AC-QA-18:** `cleanHost` detects already-present HTTP Basic Auth without a
  regular expression, preserves that URL unchanged, and continues to insert
  configured credentials when userinfo is absent. Focused tests cover both
  branches and fail if this decision path calls `re.findall`.
- **AC-SEC-10:** The already-authenticated-URL warning contains no embedded or
  configured username/password, hostname, port, path, query, or other URL
  content. The returned URL remains behavior-compatible; this slice changes
  disclosure at the logging boundary, not credential storage semantics.
- **AC-OPS-12:** A URL parser failure cannot crash host cleanup: configured
  credentials are still inserted when userinfo is absent, while recognizable
  existing userinfo is preserved without duplication even when malformed IPv6
  brackets make `urlsplit` reject the URL. No downloader request,
  authentication, SSL, trailing-slash, or protocol-selection behavior changes.
- **AC-SIMP-14:** Replace the one super-linear Basic Auth regex with one bounded
  standard-library URL authority check; add no dependency and do not refactor
  unrelated variable helpers or downloader adapters.
- **AC-QA-19:** `scanForPassword` preserves the two supported SABnzbd naming
  formats, their precedence, case-insensitive keyword handling, whitespace
  trimming, and last-marker behavior without calling a regular-expression
  search. Boundary tests cover repeated markers, malformed braces, and missing
  separators; deterministic differential input agrees with the prior parser.
- **AC-OPS-13:** Missing and non-string release names remain ordinary
  no-password results, and the sole production caller retains its existing
  title fallback and generated-name behavior.
- **AC-SIMP-15:** Replace both super-linear password regexes with bounded string
  scans local to `variable.py`; add no dependency and do not refactor the
  caller or unrelated helpers.
- **AC-QA-20:** Preserve the complete T20 password-parser behavior and bounded
  scaling while keeping every keyword-parser helper at no more than eight
  explicit decision nodes. The structural guard must fail on the merged T20
  implementation before the refactor and pass afterward.
- **AC-SIMP-16:** Resolve both T20-introduced `python:S3776` findings by
  extracting named parser decisions, without restoring regex parsing, adding a
  dependency, or changing the public `scanForPassword` boundary.
- **AC-QA-21:** AppleTrailers extracts the FilmId from the fetched page without
  a regular expression, preserves the legacy single-line greedy boundary, and
  continues to request the same metadata URL and search by title/year. Valid,
  competing-marker, malformed, and adversarial inputs have focused coverage.
- **AC-OPS-14:** A missing or malformed FilmId returns no movie and makes no
  downstream metadata request; malformed provider-controlled page content is
  not copied into the error log.
- **AC-SIMP-17:** Replace live `python:S8786` issue
  `893fdc54-72f9-4fdd-a6c8-ff7503ecdb14` with one bounded string parser local
  to the AppleTrailers adapter, adding no dependency or unrelated refactor.

## Implementation sequence

Each item is an independent review unit. External delivery is not implied by
this checklist; commits, pushes, PRs, and SonarQube state changes occur only
within the authority explicitly granted by the owner.

- [x] **T1 — truthful scan completion and versioning** — state: merged #354.
  Added
  clean-master/stable-HEAD preflight, full-SHA project versioning, CE completion
  polling, atomic freshness stamping, dirty-tree staleness reporting, and
  credential-boundary regression tests. Covers AC-OPS-1..4, AC-SEC-1..3,
  AC-QA-1, AC-PROD-1.
- [x] **T2 — narrow synchronization repair** — state: merged #354. Replaced the one
  unexplained reflow wait and two redundant `networkidle` waits with observable
  conditions. Covers AC-DESIGN-1..2, AC-A11Y-1..3.
- [x] **T3 — recurring E2E false-green mechanisms** — state: merged #354. Enforced
  syntax-aware fixed-wait exemptions and conditional-body detection, then
  repaired or removed the exposed vacuous tests.
  Covers AC-QA-2..3 and AC-A11Y-2..3.
- [x] **T4 — bind media callback types** — state: merged #354. Added the two-type
  regression test and a small shared route binder. Covers AC-QA-4, AC-SIMP-1.
- [x] **T5 — deterministic provider parsing** — state: merged #354 and #364. Added the AST
  recurrence guard, characterize provider parsing, and explicitly select the
  pinned parser in provider-sized groups. Covers AC-QA-5, AC-PROD-2,
  AC-SEC-4, AC-SIMP-2.
- [x] **T6 — adjudicate the confirmed HTML-language false positive**
  *(needs: T1)* — state: completed. After a fresh successful scan and rendered
  proof, change only the exact `Web:S5254` issue and verify the transition.
  Covers AC-A11Y-4..5, AC-SEC-5.
- [x] **T7 — explicit Windows hidden-attribute failure handling** — state:
  completed. Replaced the assertion used as control flow in the file browser,
  with a regression test that executes the real method under `python -O`.
  Covers AC-QA-7, AC-SEC-6, AC-SIMP-5.
- [x] **T8 — make startup OSError handling reachable** — state: completed.
  Remove the shadowing broad handler through a testable entry-point boundary,
  retaining EINTR shutdown semantics and surfacing every other OS failure.
  Covers AC-OPS-5, AC-QA-8, AC-SEC-7, AC-SIMP-6.
- [x] **T9 — bound startup exception complexity** — state: completed.
  Extract the now-reachable `OSError` policy into small helpers, use the shared
  path-safe formatter, and replace the numeric EINTR sentinel.
  Covers AC-OPS-6, AC-QA-9, AC-SEC-7, AC-SIMP-7.
- [x] **T10 — make errno fallback explicit** — state: completed.
  Replace the T9-introduced nested conditional without widening the startup
  refactor. Covers AC-QA-10, AC-SEC-7, AC-SIMP-8.
- [x] **T11 — bound iTunes automation configuration** — state: completed.
  Treat a missing per-URL enable flag as disabled, retain enabled-feed parsing,
  and remove the redundant parsed-root condition. Covers AC-QA-11, AC-OPS-7.
- [x] **T12 — enforce bounded automation enable flags** — state: completed.
  Replace sibling direct flag indexing in IMDb and Letterboxd, and T11's local
  guard, with one tested fail-closed mechanism. Covers AC-QA-12, AC-SIMP-9.
- [x] **T13 — align the shared helper with Python naming** — state: completed.
  Rename the T12 helper and every provider import to close its exact new-code
  `python:S1542` regression without changing behavior. Covers AC-QA-13.
- [x] **T14 — remove the unserved legacy core static tree** — state: completed.
  Delete the complete 20-file `couchpotato/core/**/static` tree after
  proving it is outside the production mount, keep unfinished user behavior in
  the explicit UI parity backlog, and enforce both the filesystem boundary and
  active-guidance lifecycle with regression tests. The sole lifecycle
  deferment is the user-owned, concurrently edited
  `PLAN-2026-09-07-post-sonarqube-followups.md`; T14 must not rewrite or gate
  that file, and its lifecycle remains an explicit owner-reconciliation task.
  Covers AC-SIMP-4 and AC-QA-6.
- [x] **T15 — repair the retained standalone health probe** — state: merged #374.
  Replace the Python-2-labelled, bytes-incompatible, assertion-wrapping probe
  with one Python 3 root-page check while its deletion still requires the
  production-only AC-OPS-12 grep. Covers AC-QA-14, AC-SEC-8, AC-OPS-8, and
  AC-SIMP-10.
- [x] **T16 — adjudicate the final reliability inventory** — state: completed.
  Review all nine post-T15 `BUG`-typed findings at their call sites, retain the
  evidence for each accepted finding, and separate harmless cleanup debt from
  runtime defects. Covers AC-QA-15, AC-OPS-9, and AC-SIMP-11.
- [x] **T17 — make Put.io completion age timezone-aware** — state: merged #376.
  Repair Sonar's high-reliability-impact `python:S6903` deprecation finding
  without changing the existing five-minute completion race policy. Covers AC-QA-16,
  AC-OPS-10, and AC-SIMP-12.
- [x] **T18 — make uTorrent token parsing byte-safe and bounded** — state: merged #377.
  Replace the failing string regex at live issue
  `f3570b64-354a-4d63-b964-83b74d555e8d` with exact, bounded token-element
  parsing and deterministic response closure. Covers AC-QA-17, AC-OPS-11,
  AC-SEC-9, and AC-SIMP-13.
- [x] **T19 — make `cleanHost` auth detection bounded and secret-safe** — state: merged #378.
  Replace live issue `acaf5cc5-25b0-4950-8ac8-57a78990f81d` without changing
  URL construction behavior, and remove credential/local-network disclosure
  from its error log. Covers AC-QA-18, AC-SEC-10, AC-OPS-12, and AC-SIMP-14.
- [x] **T20 — make release password scanning bounded** — state: merged #379.
  Replace live issue `13424fcf-7147-4f58-aa8f-1012fecd4cbf` while preserving
  both supported release-name password formats and caller behavior. Covers
  AC-QA-19, AC-OPS-13, and AC-SIMP-15.
- [x] **T21 — split password parser decisions** — state: merged #380.
  Resolve live issues `42794452-9679-4251-b024-fc4de366ba53` and
  `0cb42ac4-630b-417c-95b7-17455ae2980e` introduced by T20, while retaining its
  bounded behavior and compatibility corpus. Covers AC-QA-20 and AC-SIMP-16.
- [ ] **T22 — bound AppleTrailers FilmId parsing** — state: in-progress.
  Replace live issue `893fdc54-72f9-4fdd-a6c8-ff7503ecdb14` while preserving
  valid provider behavior and failing closed before the metadata request.
  Covers AC-QA-21, AC-OPS-14, and AC-SIMP-17.

All tasks also cover AC-SIMP-3 and AC-QA-6. AC-SIMP-4 applies with the explicit
T9 and T14 exceptions stated above.

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
- 2026-09-15: Final combined verification covered 4,178 collected Python
  unit-test items, 42
  Python integration tests, 214 UI unit tests, and 282 Playwright tests across
  Chromium, accessibility, and mobile, with Ruff, the 317-file trap gate, UI
  conformance, and diff hygiene clean. T1's post-commit live validation and T6
  remain deliberately pending until the work is committed on clean `master`.
- 2026-09-16: Opened PR #354 after the mandatory pre-push gate covered 4,184
  collected Python unit-test items, 42 integration, 214 UI unit, 176 Chromium, 2 isolation, 10
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
- 2026-09-16: Cloud review of PR #354 found three boundary gaps and each was
  driven red before implementation: a one-statement braced early return now
  joins the 34-shape AST corpus; every scanner child environment now removes
  `SONARQUBE_SCANNER_PARAMS`; and the documented Alpine unit-test runner now
  installs the locked TypeScript dependency into a writable isolated volume.
  Exercising that runner rather than trusting its static test also exposed its
  missing Git/Bash mechanisms and a fixture that accidentally retained Git
  whenever Node shared `/usr/bin`; the runner now provisions both tools and
  the fixture exposes only a temporary Node link. Final focused evidence is
  346 scanner/guard tests plus the 317-file gate, and the real Alpine run is
  green with 4,171 passed, 29 skipped, and 5 expected failures. CI and fresh
  review are pending for this repair commit.
- 2026-09-16: The mandatory two-agent repair review found two remaining
  mechanism gaps. The Sonar boundary removed only the deprecated JSON variable,
  so the preferred `SONAR_SCANNER_JSON_PARAMS` and generic
  `SONAR_SCANNER_*` property namespace could still override analysis scope;
  parameterized red tests now pin all three forms and `_safe_env` removes the
  namespace before every child. The Alpine runner also now marks only `/app`
  as a Git safe directory before testing, so a root container accepts a
  non-root-owned bind mount. Focused red evidence failed three cases; final
  evidence is 348 scanner/guard tests, the 317-file gate, Ruff, shell syntax,
  and diff hygiene. A fresh independent review is pending.
- 2026-09-16: Security re-review found the same scanner-environment class in
  non-`SONAR_SCANNER_*` variables. Per the recurrence rule, the boundary is
  now namespace-based rather than an expanding denylist: every ambient
  `SONAR_*` and `SONARQUBE_*` variable is removed from all child processes,
  and only the token read from the analysis-token file is added back for the
  direct scanner launch. A future-name assertion makes the mechanism
  load-bearing. Seven red cases preceded the implementation; the final
  scanner/guard suite now passes 355 tests with Ruff and the 317-file gate.
  Security re-review is pending.
- 2026-09-16: Reconciled the plan after the dependency queue: PR #365 adopted
  the TypeScript 7 native compiler while retaining the TypeScript 6 compiler
  API boundary, and merged with all hosted checks and both cloud reviews clean.
  The post-merge Sonar analysis completed at exact project version and revision
  `6095847d7676ac5eaabb755928f20cdf903a90bf`; the gate is OK with 56.8%
  coverage, 17 bugs, 1,081 code smells, and zero vulnerabilities or hotspots.
  T1 through T6 are complete. T7 starts from the remaining critical
  assertion-control-flow bug in the Windows file browser.
- 2026-09-16: T7 followed an explicit red-green-mutation loop. The optimized
  interpreter regression failed against the assertion-based implementation,
  then the explicit Win32 `-1` sentinel check made 39 focused file-browser and
  Windows-import tests pass. Removing that check made the optimized regression
  fail, so the test killed the relevant mutation. QA review added direct
  normal-interpreter sentinel coverage; fresh security, QA, product, and
  verification reviews are clean. The full gate covered 4,233 collected
  Python unit-test items, 42
  integration, 214 UI unit, 176 Chromium, 2 isolation, 10 mobile, and 96
  accessibility tests. T7 is locally healthy for delivery.
- 2026-09-16: PR review found two completed task blocks that still described
  work as building or awaiting validation. The recurrence is now guarded by a
  structural plan-status test: its red run identified the stale T1 block;
  synthetic cases cover both checkbox/state mismatch directions, lifecycle
  prose outside the state field, and malformed task lines hidden among valid
  ones. The repaired plan plus T7 regression suite passes 32 tests with Ruff
  and diff hygiene clean.
- 2026-09-16: PR #366 merged as `38a7236f99c339a8651f609f82a1cff6b71cbb2f`.
  The exact-revision Sonar analysis closed the targeted browser `S5779` issue,
  reducing bugs from 17 to 16 and open issues from 1,098 to 1,097; coverage
  remains 56.8%, duplication 1.8%, and the gate is OK. T8 starts from the
  reachable startup error-handling defect identified by `python:S1045`.
- 2026-09-16: T8 completed locally. The red test first proved that the script
  boundary was not callable; focused tests then cover EINTR, non-EINTR,
  `KeyboardInterrupt`, `SystemExit`, and generic exceptions. Restoring the
  shadowing broad `except OSError: pass` kills the non-EINTR regression test.
  Security review found and drove removal of both the original filename and
  the implicit `exc_info` traceback from the real logger path; security, QA,
  and operability lenses are clean. The full release gate covered 4,261
  collected Python unit-test items, 42 integration tests, 214 UI unit tests, 176 Chromium flows, 2
  isolation checks, 10 mobile checks, and 96 accessibility checks.
- 2026-09-16: PR #367 merged as `848709951dcb98c05ffc2495226b8057291d5d35`.
  The exact-version and exact-revision Sonar analysis closed the targeted
  `python:S1045` issue and reduced bugs from 16 to 15. Coverage remains 56.8%,
  duplication 1.8%, and vulnerabilities and hotspots remain zero. Extracting
  the entry point exposed one new `python:S3776` smell, so code smells rose
  from 1,081 to 1,082, open issues stayed at 1,097, and the informational gate
  reports one new issue. T9 starts from that measured regression.
- 2026-09-16: T9 completed locally. The red test established a directly
  testable `OSError` policy boundary; the implementation split path-safe error
  reconstruction and reporting out of `main`, reused the shared path-safe
  formatter, and replaced the numeric EINTR sentinel. Reversing the EINTR
  predicate made both required tests fail. QA found and drove a narrow policy
  exception for only the T8-introduced complexity regression; security, QA,
  and operability re-reviews are clean. The full release gate covered 4,263
  collected Python unit-test items, 42 integration tests, 214 UI unit tests, 176 Chromium
  flows, 2 isolation checks, 10 mobile checks, and 96 accessibility checks.
- 2026-09-17: PR #368 merged as `62cf23aab13ae16933f22be160eaf05ad0d4e11a`.
  The exact-version and exact-revision Sonar analysis closed T9's `S3776`
  issue, but reported the nested errno conditional as new `python:S3358`.
  Code smells therefore remained 1,082 and the informational gate remained
  red with one new issue. T10 starts from that exact replacement finding.
- 2026-09-17: T10 completed locally. The AST regression was red against the
  exact nested errno conditional reported by SonarQube, then explicit
  `if`/`elif`/`else` branches restored green without changing the startup
  policy. QA review found the first guard inspected only direct children and
  could miss a wrapped nested conditional; the guard now walks every
  descendant, and an independently applied wrapped mutation fails it.
  Security, QA, and operability re-reviews are clean. The full release gate
  covered 4,264 collected Python unit-test items, 42 integration tests, 214 UI unit tests, 176
  Chromium flows, 2 isolation checks, 10 mobile checks, and 96 accessibility
  checks.
- 2026-09-17: PR #369 merged as `53d52ef646c2f84c30cdf29010507f93d2aa4e9b`.
  The exact-version and exact-revision Sonar analysis closed T10's `S3358`
  issue with no replacement finding: code smells fell from 1,082 to 1,081,
  open issues from 1,097 to 1,096, and the informational gate returned to OK.
  Coverage remains 56.8%, bugs 15, duplication 1.8%, and vulnerabilities and
  hotspots zero. The remaining `S5863` bcrypt test finding is adjudicated as a
  real salted-hash assertion, not a tautology. T11 starts from the genuine
  off-by-one configuration failure found while reviewing the critical
  `S5727` iTunes automation finding.
- 2026-09-17: T11 completed locally. A red regression reproduced the
  out-of-range enable-flag access before the provider's exception boundary;
  the corrected inclusive bound now treats missing flags as disabled while a
  real enabled XML feed still reaches search and returns its IMDb id. Reversing
  `>=` to `>` failed at the original access, killing the targeted mutation.
  The redundant parsed-root condition is removed because `fromstring` returns
  a root or raises into the existing per-feed handler. Security/privacy, QA,
  and product/operability reviews are clean. The full release gate covered
  4,265 collected Python unit-test items, 42 integration tests, 214 UI unit tests, 176
  Chromium flows, 2 isolation checks, 10 mobile checks, and 96 accessibility
  checks.
- 2026-09-17: PR #370 merged as `c943de1c4f44f7a01c80e897db12196368729f69`.
  The exact-version and exact-revision Sonar analysis closed both the targeted
  iTunes `S5727` finding and its existing `S3776` complexity finding. Code
  smells fell from 1,081 to 1,079, open issues from 1,096 to 1,094, coverage
  rose from 56.8% to 56.9%, and the gate remains OK with 15 bugs and zero
  vulnerabilities or hotspots. Hosted review identified the same missing-flag
  failure class in IMDb and Letterboxd; T12 converts the repeated instance
  class into a shared mechanism rather than another pair of local patches.
- 2026-09-17: T12 completed locally. Both sibling provider regressions were
  red with the same out-of-range failure. One shared fail-closed helper now
  bounds iTunes, IMDb, and Letterboxd enable-list access; reversing its strict
  upper bound failed all three real provider regressions. Security/privacy,
  QA, and product/operability reviews are clean. The full release gate covered
  4,267 collected Python unit-test items, 42 integration tests, 214 UI unit tests, 176
  Chromium flows, 2 isolation checks, 10 mobile checks, and 96 accessibility
  checks.
- 2026-09-17: PR #371 merged as
  `fdb86567f2adbeff55a9482a21db7f6c2a4303a2` with every hosted check and
  cloud review clean. The exact-version and exact-revision Sonar analysis
  retained 100% new-code coverage and 0.0% new duplication, but identified
  the new shared helper's camelCase name as one `python:S1542` smell. Total
  coverage rose from 56.9% to 57.0%; code smells rose from 1,079 to 1,080 and
  open issues from 1,094 to 1,095, while bugs remained 15 and vulnerabilities
  and hotspots remained zero. T13 starts from that exact replacement finding.
- 2026-09-17: T13 completed locally. The naming regression first failed by
  importing the required snake_case symbol; renaming the helper and all three
  provider imports made the focused iTunes, IMDb, and Letterboxd tests green.
  Ruff reports no finding and the former camelCase symbol is absent from the
  source and tests.
- 2026-09-17: PR #372 merged as
  `f25a90d85f0348ec684220beeb9c86d3045b161c` with every hosted check and
  cloud review clean. The exact-version and exact-revision Sonar analysis
  closed T13's `python:S1542` issue with no replacement finding: code smells
  fell from 1,080 to 1,079 and open issues from 1,095 to 1,094. The gate is
  OK, new-code coverage is 100%, total coverage is 57.0%, bugs remain 15,
  duplication remains 1.8%, and vulnerabilities and hotspots remain zero.
- 2026-09-17: T14 starts from the critical `typescript:S4275` updater finding.
  Two independent clean-agent reviews rejected the first fix after proving its
  runtime premise false: the app mounts only `couchpotato/static`, the current
  templates reference only that tree, and the retired ClientScript/combined
  bundle path no longer exposes any of the 20 files under
  `couchpotato/core/**/static`. A synthetic MooTools test could kill the local
  `self` mutation while preserving code no user can execute. T14 therefore
  treats the recurring class as one mechanism: delete the complete orphaned
  core static tree, including the S4275 updater and S1848 Trakt/PutIO findings,
  and add a structural guard that fails if any file is reintroduced beneath a
  core `static` directory. Acceptance also requires the existing current-UI
  and legacy-bundle-removal tests to remain green.
- 2026-09-17: PR #373 merged as
  `7a993cb396eb17a64e07a8aa4e59e17ebe2938e4` with every hosted check and
  cloud review clean. Two complete local gates each covered 4,283 collected
  Python unit-test items,
  42 integration tests, 214 UI unit tests, 176 Chromium flows, 2 isolation
  checks, 10 mobile checks, and 96 accessibility checks. The exact-master
  Sonar analysis closed the updater, Trakt, and PutIO bugs with no replacement
  finding: bugs fell from 15 to 12, smells from 1,079 to 835, coverage rose
  from 57.0% to 60.9%, and duplication fell from 1.8% to 1.6%. The gate is OK
  with zero new issues, vulnerabilities, or hotspots.
- 2026-09-17: T15 starts from the three remaining critical S5779 findings in
  `simple_healthcheck.py`. The first focused run was red because no explicit
  `check_health` boundary existed. The replacement is constrained to one root
  request: deletion remains blocked on the production-only AC-OPS-12 grep, so
  this slice repairs the retained executable without pretending that external
  evidence was obtained.
- 2026-09-17: T15 review rejected fixtures that passed through object
  finalization rather than explicit `HTTPError` closure, raised a protocol
  failure at the opener rather than the real body-read boundary, and did not
  execute the process exit mapping. Mutation-resistant replacements retain the
  error object, fail from `read1`, and execute `__main__` for success and
  failure. A live slow-stream probe also showed urllib's per-operation timeout
  did not bound the old unbounded `read()`; the probe now reads at most 64 KiB
  in chunks, caps each socket operation at the latency threshold, and starts no
  further read after that threshold is observed. A read already in progress
  can consume its own capped timeout, so the plan does not claim a hard
  five-second wall-clock deadline.
- 2026-09-17: PR #374 merged as
  `dcccb91ba6528117313d2c825d305f3bfbd17c52` with every hosted check and
  cloud review clean. Two complete local gates each covered 4,297 collected
  Python unit-test items,
  42 integration tests, 214 UI unit tests, 176 Chromium flows, 2 isolation
  checks, 10 mobile checks, and 96 accessibility checks. The exact-master
  Sonar analysis at `2026-09-17T00:00:47+0000` closed all three health-probe
  `python:S5779` bugs: bugs fell from 12 to 9, smells from 835 to 831, and
  coverage rose from 60.9% to 61.2%. Duplication remained 1.6%; the gate is OK
  with zero vulnerabilities or security hotspots.
- 2026-09-17: T16 reviewed the complete nine-finding reliability inventory.
  All are accepted with call-site evidence; none is silently dismissed in
  SonarQube:

  | Finding | Adjudication and evidence |
  |---|---|
  | `python:S8904` `awesomehd.py:37` | False positive. `.get_text()` is executed only inside `if soup.find('error'):`; `test_awesomehd_missing_authkey_skips_results_with_actionable_error` also exercises the adjacent missing-element boundary. |
  | `python:S8904` `bithdtv.py:83` | False positive. The exact `nfo_pre` value is guarded by `toUnicode(nfo_pre.text) if nfo_pre else ''`, so `None.text` is unreachable. |
  | `python:S8904` `thepiratebay.py:71` | Accepted tolerant parser behavior. The optional pagination lookup is inside its own `try/except`; failure retains the initialized single-page bound and result parsing continues. Provider parser tests execute this implementation with the pinned parser. |
  | `python:S5779` `test_race_conditions.py:298` | Intentional test mechanism. A worker-thread assertion is caught into `errors`, and the owning test fails on `assert len(errors) == 0`; forcing the worker assertion to fail is propagated and makes that final assertion fail. |
  | `typescript:S5845` `category-editor.spec.ts:90` | False positive from inference across untyped JavaScript. `categoryToForm` uses `c._id ?? ''`; the test deliberately proves numeric `_id=0` survives instead of becoming the string fallback. |
  | `Web:PageWithoutTitleCheck` `base.html:3` | False positive. The same template's `<head>` contains `<title>{% block title %}CouchPotato{% endblock %}</title>`. |
  | `python:S5863` `test_password_storage.py:67` | False positive. Two calls with the same password must differ because bcrypt generates a fresh random salt; a fixed-salt mutation fails this regression while authentication tests prove both hashes remain usable. |
  | `python:S1226` `newznab.py:170` | No runtime defect. The interface-compatible `host` argument is intentionally not consulted; the method enumerates configured hosts and passes each configured value to the base matcher. The loop-name shadow is cleanup debt only. |
  | `python:S1226` `torrentpotato.py:151` | Same bounded cleanup class as Newznab: configured hosts are deliberately enumerated, the interface argument is unused, and the loop variable is passed immediately to the base matcher. |

  The exact scan reports no other SonarQube bugs. T16 therefore closes the
  `BUG`-typed inventory without changing SonarQube issue state or mislabelling
  the two minor naming cleanups as production fixes.
- 2026-09-17: Reconciled after the owner clarified that the terminal condition
  includes all maintainability findings, not only `BUG`-typed findings. The
  live inventory contains 831 open code smells, including 42 with reliability
  impact. T17 starts from the sole Sonar-classified high-reliability critical
  finding: Put.io compares a naive UTC timestamp with `datetime.utcnow()`.
  Call-site review shows this is a low-risk deprecation cleanup rather than a
  present wrong-result defect because both operands currently represent naive
  UTC. Read-only
  triage of the remaining Python, browser/template, blocker, and critical
  findings is running in parallel; the user-owned modified post-Sonar plan
  remains outside this worktree and untouched.
- 2026-09-17: T17 reached green after an explicit red test rejected the naive
  `utcnow()` path in both younger-than-five-minute and older-than-five-minute
  cases. Production now uses an aware UTC clock and attaches UTC to Put.io's
  offset-less API timestamp. Restoring the naive clock failed both regression
  cases; the complete 20-test Put.io group and focused Ruff/diff checks pass.
  Independent Harness review and the broader gate remain pending.
- 2026-09-17: T17's fast repository gate collected 4,319 Python unit-test
  items (4,300 passed, 14 skipped, 5 xfailed) and passed 214 UI unit tests,
  with Ruff, the 323-file trap guard, UI conformance, and
  diff hygiene clean. The configured changed-file mutation scope does not
  include this downloader; the explicit naive-clock mutation remains the
  load-bearing proof. Independent review remains pending.
- 2026-09-17: T17's corrected exact tip passed security/privacy, QA/reliability,
  operability/product, and fresh-verification review with every criterion clean.
  The complete release gate collected 4,320 Python unit-test items (4,301
  passed, 14 skipped, 5 xfailed) and passed 42 integration tests, 214 UI unit
  tests, 176 Chromium flows, 2 isolation checks, 10 mobile
  checks, and 96 accessibility checks. T17 is locally healthy for delivery.
- 2026-09-17: Final evidence review found the recurring class of calling
  pytest's collected total a passed-test count. A structural guard first failed
  on the historical wording, every unverifiable historical total now says
  `collected`/`covered`, and T17 records the exact 4,301 passed, 14 skipped,
  and 5 xfailed outcomes. Reintroducing the old phrase makes the guard fail.
- 2026-09-17: Opened PR #376 after the final pre-push gate covered 4,326
  collected Python unit-test items and passed 42 integration, 214 UI unit, 176
  Chromium, 2 isolation, 10 mobile, and 96 accessibility tests. T17 is
  awaiting hosted CI and cloud review.
- 2026-09-17: T17 merged as PR #376 after all 16 hosted checks and the cloud
  review passed. Exact-master Sonar analysis
  `e2bfb10a-5b7d-4042-a956-d86ff4715e89` measured merge commit
  `3882511e15324e10af548767b1138eaabbeb795a`, closed the Put.io
  `python:S6903` issue as `FIXED`, reduced open code smells from 831 to 830 and
  critical smells from 198 to 197, and retained 61.2% coverage. T18 starts
  from that exact master revision.
- 2026-09-17: T18's red tests reproduced the production Python 3 failure:
  `urllib` returned bytes and the string regex raised `TypeError`. The bounded
  standard-library parser now selects only `div#token`, closes both successful
  and malformed responses, and emits a fixed body-free error when the element
  is absent. Mutating the selector to accept every `div` made the decoy-token
  regression fail. All 168 downloader tests and the 323-file trap guard pass.
  The fast repository gate collected 4,328 Python unit items (4,309 passed,
  14 skipped, 5 xfailed), then passed 42 integration and 214 UI-unit tests;
  Ruff and UI conformance are clean.
- 2026-09-17: Two independent clean-agent reviews measured exact commit
  `8f032ea71bdd8bc21160c098a72eb2f618ab09d4` and tree
  `95abac2a9308eb69fe62f9214661d9ea2dc9c877` as clean across security,
  privacy, operability, QA, reliability, product, and simplicity. Reviewers
  independently reproduced the legacy bytes `TypeError`, killed selector,
  response-closure, and body-disclosure mutations, verified real `urllib`
  response closure, and measured approximately linear parsing at 10k/20k
  adversarial input. T18 is locally healthy for delivery.
- 2026-09-17: Opened PR #377 after the full pre-push gate passed 4,309 Python
  unit tests (14 skipped, 5 xfailed), 42 integration tests, 214 UI-unit tests,
  176 Chromium flows, 2 isolation checks, 10 mobile checks, and 96
  accessibility checks. T18 is awaiting hosted CI and cloud review.
- 2026-09-17: T18 merged as PR #377 after all 16 hosted checks and cloud review
  passed. Exact-master analysis `240df92f-be48-4c62-93e6-687405a6950f`
  measured merge commit `cc05fec4eb7052e785a3b99a6e049210e0eb9b47`,
  closed issue `f3570b64-354a-4d63-b964-83b74d555e8d` as `FIXED`, and reduced
  open code smells from 830 to 829 and MAJOR smells from 335 to 334 while
  retaining 61.2% coverage. T19 starts from that exact master revision.
- 2026-09-17: T19's red tests proved the old `cleanHost` warning passed the
  entire credential-bearing URL to logging and that auth detection called
  `re.findall`; the missing-auth branch consequently failed when regex use was
  forbidden. Production now uses bounded `urlsplit` authority fields, emits a
  fixed URL-free warning, and treats parser failure as absent userinfo so the
  existing best-effort insertion remains. An always-absent-auth mutation
  produced double userinfo and was killed by the preservation regression.
  The complete helper/plan set passed 110 tests with 12 skips, and the fast
  gate collected 4,331 Python unit items (4,312 passed, 14 skipped, 5 xfailed),
  then passed 42 integration and 214 UI-unit tests; Ruff, conformance, and the
  323-file trap guard are clean.
- 2026-09-17: Two independent clean-agent reviews measured exact commit
  `a79f10e39e74eabe0f9a42eab2fa9ae503fdba3d` and tree
  `b42214c9731cc85af5567e95738a5985f94b1a94` as clean across security,
  privacy, operability, QA, reliability, product, and simplicity. Their URL
  matrix covered encoded, colon-bearing, and raw-`@` credentials; IPv6;
  path/query decoys; incomplete userinfo; absent userinfo; and malformed
  brackets. Adversarial 10k/20k/40k authority parsing scaled approximately
  linearly, and NZBGet's sole credential-inserting call path was unchanged.
  T19 is locally healthy for delivery.
- 2026-09-17: Opened PR #378 after the full pre-push gate passed 4,312 Python
  unit tests (14 skipped, 5 xfailed), 42 integration tests, 214 UI-unit tests,
  176 Chromium flows, 2 isolation checks, 10 mobile checks, and 96
  accessibility checks. T19 is awaiting hosted CI and cloud review.
- 2026-09-17: All 16 hosted checks passed, but cloud review found that malformed
  bracketed IPv6 with existing userinfo made `urlsplit` raise before exposing
  the credentials; the fallback then inserted a second credential pair. A new
  focused regression reproduced the exact double-userinfo result red. The
  bounded parse-failure fallback now inspects only the URL authority, preserves
  recognizable existing username/password, and retains best-effort insertion
  when userinfo is absent; all four focused Basic Auth tests pass. The repaired
  fast gate collected 4,332 Python items (4,313 passed, 14 skipped, 5 xfailed),
  then passed all 42 integration and 214 UI-unit tests with lint, conformance,
  and the 323-file trap guard clean. T19 is ready for independent local review
  before the required fix push.
- 2026-09-17: Two independent clean-agent reviews measured exact repair commit
  `ff08eb4b5b72f9856b219e363c637655b0e9b12f` and tree
  `2b396f0051ad07b65284a70e48deeae068537cc0` as clean. Their matrix exercised
  ten real `urlsplit` failure cases, including malformed IPv6 and NFKC-invalid
  authorities; normal, colon-rich, percent-encoded, and raw-`@` credentials;
  absent/incomplete userinfo; and path/query/fragment decoys. Existing auth was
  preserved without duplication or disclosure, absent auth retained configured
  insertion, and 10k/20k/40k failure inputs scaled approximately linearly. The
  repair will now receive its required full pre-push gate and hosted rerun.
- 2026-09-18: PR #378 merged as
  `ea5e6d92943e39a821b14f408b529db6fa15f0ec` after all 16 hosted checks,
  cloud review, and a clean rerun of one transient accessibility contrast
  failure. Exact-master analysis `225544b5-0422-416c-bdbd-5dd0069e6c42`
  closed `acaf5cc5-25b0-4950-8ac8-57a78990f81d` as `FIXED`, reduced open code
  smells from 829 to 826 and MAJOR smells from 334 to 331, and raised coverage
  from 61.2% to 61.3%.
- 2026-09-19: T20 red evidence replaced both password regex objects with traps;
  the existing implementation called `.search` and failed. Two bounded string
  helpers now pass all focused password tests. A deterministic 200,000-case
  differential corpus, including embedded newlines, matched the prior parser.
  An additional repeated-invalid-marker benchmark exposed and removed a
  quadratic line-prefix reconstruction path; 10k/20k/40k markers then measured
  approximately 0.0015/0.0030/0.0062 seconds. Other adversarial
  10k/20k/40k inputs scaled approximately linearly for both brace and keyword
  formats. Removing either parser branch made its format regressions fail,
  killing both targeted mutations. The final fast gate collected 4,341 Python
  unit items (4,322 passed, 14 skipped, 5 xfailed), then passed all 42 integration
  and 214 UI-unit tests with Ruff, conformance, and the 323-file trap guard
  clean. Independent security and QA review then found two compatibility gaps
  absent from the first corpus: whole-string lowercasing changed source offsets
  after expanding Unicode characters and failed the legacy long-s match, while
  terminal-newline and non-space whitespace behavior differed from the prior
  regexes. Seven new parser/caller assertions failed before the first repair;
  two whitespace assertions also pin the prior full-trim behavior. The
  position-preserving repair now passes all
  42 focused tests and a revised 200,000-case corpus containing Unicode and
  carriage-return/tab boundaries. Removing terminal-newline normalization made
  five tests fail; replacing the casefold comparison with exact matching made
  two fail. Repeated-invalid-marker 10k/20k/40k timings remain approximately
  linear: 0.0072/0.0145/0.0293 seconds for braces and
  0.0233/0.0451/0.0907 seconds for keywords. The post-repair fast gate
  collected 4,354 Python unit items (4,335 passed, 14 skipped, 5 xfailed), then
  passed all 42 integration and 214 UI-unit tests with Ruff, conformance, and
  the 323-file trap guard clean. Security re-review then found that each keyword
  marker before a newline copied and searched the remaining suffix, making a
  repeated multiline name quadratic. A slice-guard regression failed on the
  old loop before the repair. QA review then showed that limiting candidates to
  the final line lost the legacy regex's ability to consume newlines in the
  whitespace after `=`; both counterexamples failed before the second repair.
  The parser now precomputes the last non-whitespace position before the final
  line and permits only the one earlier `=` that can legally own that suffix,
  retaining cross-line whitespace without repeated suffix copies. All 45
  focused tests and an expanded exact 400,000-case differential corpus pass.
  The reviewer's 16k/32k/64k/128k input now scales approximately linearly at
  0.068/0.137/0.272/0.545 seconds. A fresh verifier then found that a competing
  marker on the final line changed selection when an earlier match could span a
  newline: the legacy regex chooses the leftmost match start before applying
  greediness within that line. Parser and caller reproductions both failed
  before repair. The bounded parser now checks the at-most-one cross-line
  prefix and suffix candidates in legacy priority order, then scans the final
  line right-to-left. Additional whitespace-only-line and short-final-line
  boundaries were added as each differential counterexample was found. All 53
  focused tests, 177,155 structured competing-marker cases, and 400,000 seeded
  random cases match the prior parser. The repeated 16k/32k/64k/128k multiline
  input now measures approximately 0.000009/0.000015/0.000027/0.000049 seconds.
  QA re-review found one remaining case where both constant cross-line
  candidates exist: their precedence depends on the regex match start rather
  than marker kind. Its parser and caller assertions failed before repair. The
  parser now compares those candidates by leftmost start, using the later marker
  only for equal starts, exactly reflecting search then greediness. All 55
  focused tests, 579,194 structured cases, and 500,000 seeded random cases now
  agree with the prior parser; the repeated multiline benchmark remains bounded
  at approximately 0.000005/0.000002/0.000001/0.000002 seconds. The exact-tip
  fast gate then collected 4,367
  Python unit items (4,348 passed, 14 skipped, 5 xfailed), and passed all 42
  integration and 214 UI-unit tests with Ruff, conformance, and the 323-file
  trap guard clean. Independent security and QA re-reviews both returned CLEAN
  on tree `5823781977b72812d5861b5a55d8ed848e8b6bec`; their additional differential
  corpora covered 611,150 and 750,000 cases respectively, with linear
  adversarial scaling. T20 is ready for the final clean-tree review gate and
  push.
- 2026-09-19: PR #379 merged as
  `b24f524b603c95bbc681c5768d9a1f7aaa26618f` after all 16 hosted checks.
  Exact-master analysis `7db2b4e9-de95-4ee9-958f-1185b15cc1b6` closed
  `13424fcf-7147-4f58-aa8f-1012fecd4cbf` as `FIXED`, reduced MAJOR smells from
  331 to 330, and raised coverage from 61.3% to 61.4%. It also identified two
  CRITICAL cognitive-complexity regressions in the replacement parser, so T21
  starts before the next provider finding. Its structural branch-budget test
  is red on the merged implementation: `_keyword_password_at` has 18 decision
  nodes and `_keyword_password` has 23, both above the budget of eight.
- 2026-09-19: T21 extracted the keyword parser's value, prefix, cross-line,
  and final-line decisions into named helpers; the branch-budget guard is now
  green with every helper at eight decision nodes or fewer. All 56 focused
  parser/caller tests pass, as do 500,000 seeded comparisons against the
  original regex oracle. The 16k/32k/64k/128k repeated multiline adversary
  remained bounded at approximately 0.000004/0.000002/0.000002/0.000002
  seconds. Deleting cross-line candidate selection made seven focused tests
  fail, proving those compatibility assertions are load-bearing. The fast gate
  collected 4,368 Python unit-test items (4,349 passed, 14 skipped, 5 xfailed),
  then passed 42 integration tests and 214 UI-unit tests with Ruff,
  conformance, and the 323-file trap guard clean.
- 2026-09-19: PR #380 merged as
  `2125bcf22884b1777094a5efc7e5f34b14d0b25d` after all hosted checks.
  Exact-master analysis `3b0a5df3-a7fb-4b1f-b979-15165a5c234a` closed both
  T21 issues as `FIXED`, introduced no new findings, reduced open code smells
  from 827 to 825, and raised coverage from 61.4% to 61.5%. T22 starts with
  the next confirmed external-input finding in AppleTrailers.
- 2026-09-19: T22 red evidence showed the provider's regex accepting an empty
  FilmId, taking approximately 60 seconds on 20,000 repeated delimiters, and
  calling regex search on the valid path. A bounded line parser now passes all
  eleven focused provider tests, including no downstream request for malformed
  input. Five hundred thousand seeded inputs match the legacy regex for valid
  IDs; the deliberate empty-ID and replacement-character rejections are the
  only policy differences. The
  10k/20k/40k/80k malformed adversary measured approximately
  0.000014/0.000024/0.000047/0.000103 seconds. Replacing the greedy final
  delimiter selection with the first delimiter made the competing-marker test
  fail, proving that compatibility assertion is load-bearing. The fast gate
  collected 4,379 Python unit-test items (4,360 passed, 14 skipped, 5 xfailed),
  then passed 42 integration tests and 214 UI-unit tests with Ruff,
  conformance, and the 324-file trap guard clean.
- 2026-09-19: T22 security review found one recurring test-mechanism gap with
  two instances: all focused tests still passed when malformed page content
  was raised into the traceback logger, and when newlines were removed before
  parsing so separate-line fragments formed one FilmId. The malformed-input
  test now asserts the error logger is untouched, and an explicit split-line
  case pins the legacy regex's newline boundary. Both assertions fail under
  their respective mutations.
- 2026-09-19: PR #381's hosted review found that the real HTTP/cache boundary
  returns response content as bytes while the first parser revision accepted
  only strings. A production-shaped bytes test failed before remediation and
  now passes after explicit UTF-8 decoding with replacement, keeping malformed
  byte sequences bounded and out of exception logs.
- 2026-09-19: Both local remediation reviewers then found the same malformed-
  byte boundary gap: a replacement character inside FilmId could still reach
  the metadata URL. Tests now prove corruption outside a valid ASCII ID remains
  recoverable, while corruption inside the ID fails closed without a request
  or error log. Removing either replacement decoding or the replacement-
  character rejection kills the focused suite.
