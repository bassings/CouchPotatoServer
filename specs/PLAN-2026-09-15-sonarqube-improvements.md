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
- **AC-QA-22:** The AppleTrailers provider keeps all eleven FilmId behavior and
  boundary tests green, and a structural regression test prevents `getMovie`
  from reintroducing the builtin-shadowing local name.
- **AC-SIMP-18:** Resolve live `python:S5806` issue
  `3e8c98da-8ab3-4710-97b8-b41d8f72e349` by renaming only the local FilmId
  variable, without changing parsing, requests, logging, or provider behavior.
- **AC-QA-23:** A hermetic characterization executes the real
  `SynologyRPC._req` method with a successful JSON response and a transport
  failure. It proves the success result is the complete decoded server payload,
  the handled-failure result is exactly `{'success': False}`, and the two
  outcomes differ.
- **AC-QA-24:** The characterization is load-bearing: temporarily removing the
  successful response assignment makes the new success assertion fail because
  `_req` returns the failure sentinel, restoring production byte-for-byte makes
  it pass, and no production change remains in the slice.
- **AC-QA-25:** Before every push, the focused Synology suites, Ruff, trap
  checks, applicable fast/full repository gate, Harness review, and at least
  two independent local code reviews are clean. Hosted CI and cloud review
  must pass before merge.
- **AC-SEC-11:** The test uses only synthetic host, payload, and task data,
  performs no live NAS or Sonar request, and contains no credential, API token,
  private path, LAN address, media title, or captured server response.
- **AC-SEC-12:** False-positive adjudication occurs only after a fresh
  successful exact-master analysis reports the merge SHA as both revision and
  project version and the exact issue still identifies `python:S3516` on
  `SynologyRPC._req`; any identity drift aborts the action.
- **AC-SEC-13:** Read the owner-only administrator token as data rather than
  sourcing it, expose it only to the fixed trusted Sonar origin, disable
  environment proxies and redirects, apply a bounded timeout, and never place
  it in argv, environment, output, logs, comments, temporary files, repository
  files, or shell history.
- **AC-SEC-14:** The adjudication comment contains only the exact merge and
  analysis identities, synthetic executable evidence, the distinct-return
  rationale, and an expiry condition requiring re-evaluation if `_req`'s
  return contract or exception boundary changes.
- **AC-OPS-15:** The slice changes characterization and plan evidence only; it
  does not alter Synology requests, authentication, TLS behavior, timeout,
  retry behavior, logging, dependencies, workflows, or deployment.
- **AC-OPS-16:** No administrator action occurs before protected `master`
  contains the reviewed test and all required hosted checks have passed. Record
  the exact PR head and merge SHA.
- **AC-OPS-17:** Run `make sonar` from a clean checkout of fetched
  `origin/master`; require Compute Engine `SUCCESS`, plausible coverage inputs,
  and full-SHA equality among checkout, revision, project version, and merge.
- **AC-OPS-18:** Re-fetch issue
  `b6e7673f-30ed-4cf5-aa62-8298652e195f` after that analysis. If it remains
  open with the same rule, component, and method, transition only that issue to
  false positive and verify its changelog; if Sonar already closes it, perform
  no administrator mutation.
- **AC-PROD-3:** Preserve the complete Synology response contract consumed by
  login and task creation. Do not restructure working production control flow
  merely to influence the analyzer.
- **AC-SIMP-19:** Add no helper, dependency, alternate return type, logging
  change, exception-boundary change, or production refactor for this evidenced
  analyzer mistake.
- **AC-SIMP-20:** Continue the live backlog in descending severity, prioritising
  real reliability, security/privacy, data-loss, external-input, and production
  operability risk within each severity. Each later slice covers one coherent
  behavior class and is re-ranked only after merge and exact-master analysis;
  no severity-wide, rule-wide, path-wide, or bulk dismissal is permitted.
- **AC-QA-26:** A focused AST test identifies the two dictionary-draining loops
  by their `movie_files.popitem()` and `valid_files.popitem()` bodies and
  requires each predicate to be exactly `not self.shuttingDown()`. It fails on
  the current redundant predicates and passes after the production edit.
- **AC-QA-27:** Independently reintroducing `True and` into either targeted
  predicate makes that focused test fail for the intended loop. Restoring the
  reviewed source returns the focused scanner suite to green.
- **AC-DATA-1:** The production diff changes only the two exact loop headers.
  It preserves loop bodies, dictionary traversal and item order, filtering,
  callbacks, partial results, exception boundaries, shutdown call cadence,
  and the separate active-thread throttling loop.
- **AC-SEC-15:** The slice adds no logging, filesystem or network operation,
  credential handling, dependency, configuration, workflow, or external
  mutation. Test inputs and diagnostics contain no media paths or titles.
- **AC-OPS-19:** Shutdown remains checked exactly once before every attempted
  iteration; a true result prevents entry and a false result permits entry,
  exactly as before.
- **AC-PROD-4:** The change is intentionally invisible to users: scan results,
  processing order, callbacks, logs, configuration, and UI remain unchanged.
- **AC-SIMP-21:** Resolve only live `python:S5797` issues
  `8c3654e9-4617-4fdd-b1cf-22ee48fbca2c` and
  `d0f3bd28-4e54-498f-a17d-0bd9ba958741` by removing their redundant constant
  operands; add no helper, abstraction, or adjacent cleanup.
- **AC-OPS-20:** Before each push, focused scanner tests, Ruff, repository gates,
  Harness review, and two independent local code reviews are clean. After
  merge, an exact-master Sonar analysis closes both issue keys without a
  replacement finding before the backlog is re-ranked.
- **AC-QA-28:** A focused `searchSingle` test supplies multiple
  `subtitle_language` entries with overlapping available languages and one
  genuinely missing configured language. It proves every nested value is
  flattened and deduplicated and only the missing language is requested.
- **AC-QA-29:** A focused AST regression test rejects empty-list-seeded
  `sum(..., [])` flattening in `Subtitle.searchSingle` and requires the linear
  `chain.from_iterable(...)` mechanism. It fails on the pre-change source and
  passes after the production edit.
- **AC-QA-30:** Restoring the old `sum(..., [])` expression makes the structural
  test fail, while independently replacing `chain.from_iterable(values)` with
  non-flattening `chain(values)` makes the multi-entry behavior test fail.
  Restoring the reviewed source returns the focused suite to green.
- **AC-SEC-16:** The subtitle slice changes only in-memory flattening and its
  synthetic tests. It adds no logging, filesystem or network operation,
  credential handling, dependency, configuration, workflow, or external
  mutation, and fixtures disclose no real media title, path, host, or secret.
- **AC-OPS-21:** For the scanner-produced `dict[path, list[alpha2]]` contract,
  flattening remains eager and preserves all current operational decisions:
  available languages suppress downloads unless forced, empty mappings remain
  valid, and logging, exception boundaries, return values, provider calls, and
  save behavior do not change.
- **AC-OPS-22:** The replacement traverses nested language lists linearly,
  without repeated cumulative list allocation, a runtime dependency, or a new
  configuration requirement, and remains compatible with the production
  Python 3 environment.
- **AC-OPS-23:** Before push, focused subtitle tests, Ruff, repository gates,
  Harness review, and two independent local reviews are clean. After merge, an
  exact-master Sonar analysis closes issue
  `49dfbcdf-5c02-4e1a-bf65-294730029b44` without a replacement finding before
  the backlog is re-ranked.
- **AC-PROD-5:** With the same configured languages, detected sidecars, and
  `force` setting, users receive exactly the same search decisions: every
  available alpha-2 language is skipped, every missing configured language is
  eligible, duplicates do not matter, and force mode searches all configured
  languages.
- **AC-PROD-6:** The slice is otherwise invisible: it changes no setting,
  provider selection, request payload beyond the preserved language set, saved
  path, log, UI behavior, return value, or failure behavior. Its only user
  benefit is avoiding increasingly expensive intermediate-list construction.
- **AC-SIMP-22:** The production change is limited to importing
  `itertools.chain` and replacing the exact empty-list-seeded `sum` expression
  with `set(chain.from_iterable(group['subtitle_language'].values()))`.
- **AC-SIMP-23:** Add only focused proof for complete linear flattening. Add no
  helper, abstraction, compatibility layer, dependency, cache, normalization,
  or speculative support for new subtitle-language shapes.
- **AC-SIMP-24:** Do not sweep other `sum(..., [])` occurrences, refactor
  adjacent subtitle download/save logic, alter scanner production code, or
  combine another Sonar finding into this slice.
- **AC-QA-31:** Two-result BinSearch coverage passes the real `ResultList` into
  `_search` and proves `append` consumes each `extra_check` before the next row:
  a passworded first row is rejected and a clean second row is accepted.
- **AC-QA-32:** Two-result Pirate Bay coverage passes the real `ResultList` into
  `_search` and proves `append` consumes each `extra_score` before the next row:
  a Trusted-only first row scores 10 and a Moderator-only second row scores 50.
- **AC-QA-33:** The characterization is load-bearing through the real handlers:
  bypassing `extra_check` in `MovieSearcher.correctRelease` or `extra_score` in
  `Score.calculate` makes its focused assertion fail; restoring production
  byte-for-byte returns the parser suite to green.
- **AC-SEC-17:** Preserve the synchronous `trusted_only` rejection boundary.
  The characterization changes neither ranking nor provider admission and must
  not add logging or expose titles, paths, credentials, or network details.
- **AC-OPS-24:** The slice changes characterization and plan evidence only. It
  does not alter provider HTTP behavior, result schema, parsing failure handling,
  timeouts, proxy selection, scoring, validation, or callback invocation.
- **AC-OPS-25:** After merge, an exact-master Sonar analysis must still report
  all four S1515 issues with the same rule, component, and captured variable
  before they are accepted individually as false positives with their exact
  synchronous execution boundary and expiry condition.
- **AC-SIMP-25:** Do not add default bindings or rewrite any of the four safe
  closures merely to silence the analyzer. Re-evaluate if event dispatch,
  either production handler, `ResultList.append`, `list(filter(...))`, or
  `sorted(..., key=...)` ever defers or stores its callback beyond the current
  iteration.
- **AC-QA-34:** No production module that imports BeautifulSoup may pass the
  deprecated `text=` keyword to `find` or `find_all`. A repository-wide AST
  guard discovers the calls dynamically and fails if the keyword returns.
- **AC-QA-35:** HDTrailers keeps its provider-link and no-match behavior on
  complete and unfinished HTML, including the currently characterized failure
  for a matching alternative heading. IPTorrents keeps traversing the real
  multi-page `Next` navigation path and returns the same result fields.
- **AC-OPS-26:** The keyword migration changes no request, parser, pagination,
  provider admission, logging, response-body handling, or failure behavior.
- **AC-SIMP-26:** Limit production changes to the three BeautifulSoup keyword
  replacements. Do not combine the adjacent complexity, naming, or comparison
  findings into this slice.
- **AC-QA-36:** TMDB search preserves the existing truthy explicit
  `search_type` override and otherwise selects `ngram` only when `limit > 1`,
  with `phrase` for the single-result case.
- **AC-QA-37:** `parseMovie` keeps the original request order and identity
  boundary: the English request uses the caller's movie id, then default and
  additional language requests use the canonical id returned by that response.
- **AC-QA-38:** Extended and non-extended parsing send the same
  `append_to_response` value to every language request and preserve the merged
  title result. A module-wide AST guard rejects nested conditional expressions.
- **AC-SEC-18:** TMDB request parameters remain server-controlled and the slice
  adds no logging, response disclosure, credential handling, or outbound host.
- **AC-OPS-27:** Preserve request count, order, paths, language iteration,
  fallback behavior, exception handling, and the `None` result on a failed
  initial request.
- **AC-SIMP-27:** Replace only the nested conditional expressions and their
  immediately repeated literals. Add no helper, dependency, cache, retry, or
  adjacent provider cleanup.
- **AC-A11Y-6:** The enabled tracker controls, Usenet client controls, and
  torrent client controls use native `fieldset` grouping with the same dynamic
  or heading-derived accessible names. No generic `role="group"` remains in the
  wizard template.
- **AC-DESIGN-3:** At the repository's phone viewport, two simultaneously
  enabled private trackers and both selected downloader types keep every group
  and interactive descendant within the layout viewport, with no document
  overflow.
- **AC-QA-39:** A structural guard pins all three native groups, and a real
  browser test drives the wizard through provider and downloader selection
  before measuring the rendered controls. The test must not pass with an
  absent or hidden group.
- **AC-PROD-7:** Provider enabling, downloader selection, labels, values,
  transitions, conditional visibility, and wizard navigation remain unchanged.
- **AC-SIMP-28:** Limit production changes to replacing the three generic
  grouping containers with native fieldsets. Add no wrapper, JavaScript state,
  layout utility, copy, or unrelated wizard cleanup.
- **AC-A11Y-7:** The profile-mismatch message uses the native `output` status
  semantics without a redundant role. The horizontally overflowing releases
  table is contained by a natively named `section`, remains in the tab order,
  shows a visible focus indicator, and scrolls from the keyboard.
- **AC-DESIGN-4:** At phone width, the release region genuinely overflows and
  its own bounds remain inside the viewport; focusing and scrolling it changes
  the region's horizontal position without moving or widening the document.
  This semantic-only slice does not claim to repair the page's measured,
  pre-existing document-wide overflow from other content.
- **AC-QA-40:** Route tests pin the native elements and absence of redundant
  roles. Mobile browser tests prove implicit status exposure and the real
  focus/ArrowRight scrolling path rather than only inspecting markup.
- **AC-DATA-2:** Browser coverage for the profile-mismatch state owns a
  dedicated movie, profile, and release. The fixture verifier asserts their
  exact relationship and existing protected seed movies cannot be consumed by
  E2E specs.
- **AC-PROD-8:** Release filtering, displayed copy, table contents, status
  updates, action controls, and seed-data behavior outside the dedicated test
  fixture remain unchanged.
- **AC-SIMP-29:** Limit production UI changes to the native `output` and
  `section` substitutions. Retain the existing accessible name and tabindex;
  add no JavaScript keyboard handler, role duplication, or style refactor.
- **AC-QA-41:** rTorrent recognizes both and only the existing `httprpc://`
  and `httprpc+https://` prefixes through one tuple-based `startswith` call.
  Focused connection tests retain rewriting and SSL-upgrade behavior for both
  schemes and ordinary RPC URLs remain outside that branch.
- **AC-SEC-19:** The refactor does not broaden accepted URL schemes, weaken
  certificate verification, change credential transport, or alter the
  configured `ssl` upgrade from HTTP RPC to HTTPS RPC.
- **AC-OPS-28:** Preserve the rewritten endpoint, adapter selection, connection
  attempt, failure logging, and return behavior for every existing scheme.
- **AC-SIMP-30:** Replace only the duplicated prefix predicate. Add no helper,
  URL normalization, dependency, or adjacent downloader cleanup.
- **AC-A11Y-8:** Replacement candidates are native same-name radios in a
  fieldset with a native legend. Space selects, arrow keys move focus and
  selection, the group contributes one Tab stop, and each filename is the
  radio's accessible name without custom ARIA state.
- **AC-DESIGN-5:** Candidate rows preserve their selected/unselected styling,
  truncation, minimum touch target, bounded scrolling, and phone-width layout
  after the control changes from a button to a labelled radio.
- **AC-QA-42:** Unit and browser tests pin the native structure and full
  keyboard model, confirm disabled/enabled transitions, mobile overflow, and
  exact request submission for a filename containing quote, script, and HTML
  payload characters.
- **AC-SEC-20:** Candidates remain server-produced choices with no free-text
  path input. Hostile filenames render only as text, execute no script or image
  handler, and round-trip verbatim as the selected `source` parameter.
- **AC-PROD-9:** Loading, error, empty, selection, cancellation, confirmation,
  focus trapping/return, and replacement request behavior remain unchanged.
- **AC-SIMP-31:** Delete the custom radio role, ARIA checked state, and manual
  arrow-key state machine in favor of native controls. Add no replacement
  interaction abstraction or unrelated modal refactor.
- **AC-A11Y-9:** Categories, Quality profiles, and Qualities in this profile
  are native labelled ordered lists whose repeated rows are native list items;
  each `ol` retains the documented `role="list"` compatibility mechanism so
  Safari/VoiceOver exposes markerless lists, while no explicit `listitem` roles
  remain. The conversion adds no tab stops and preserves every existing control
  name, disabled boundary, focus treatment, keyboard action, and phone-width
  touch target.
- **AC-DESIGN-6:** The three ordered lists retain their existing list and row
  classes and render without visible markers, native indentation, or native
  margins. At the real 393px viewport in both themes, rows, text, and controls
  remain within their panels and the layout viewport with no new document
  overflow or change to spacing, borders, backgrounds, radii, or padding.
- **AC-QA-43:** A repository-anchored structural test pins exactly the three
  labelled `ol` elements, their `template[x-for]` and keys, and their repeated
  `li` rows, while requiring the WebKit compatibility `list` role on each `ol`
  and rejecting explicit `listitem` roles in the two target templates. The test
  is observed failing on the current generic elements before production markup
  changes and on native markerless lists without the compatibility role.
- **AC-QA-44:** Non-vacuous Chromium coverage makes all three lists visible
  and populated, resolves them by list role and exact accessible name,
  proves their rendered `OL`/`LI` identity, compatibility `list` roles, and
  absence of explicit `listitem` roles, and verifies marker/margin/padding reset
  plus phone-width containment. Existing category, profile, and quality reorder
  tests retain exact-order, reload-persistence, boundary, and restoration
  assertions without a new conditional assertion body.
- **AC-SEC-21:** Preserve every existing `x-for`, key, text-only binding,
  event, disabled state, item/index binding, request, submitted id/order value,
  and private-path exposure boundary. Add no HTML-capable rendering,
  authentication or authorization change, logging, telemetry, or third-party
  request.
- **AC-PROD-10:** Categories, profiles, and qualities render in the same
  application-defined order with unchanged visible contents, controls,
  loading/error/empty states, CRUD behavior, quality finish behavior, and
  persisted/reloaded order. The semantic conversion adds no visible numbering,
  indentation, copy, or workflow change.
- **AC-SIMP-32:** Limit production changes to substituting the three list
  containers and paired repeated rows with `ol`/`li`, retaining `role="list"`
  only as the shared Safari/VoiceOver compatibility mechanism and deleting the
  three redundant `listitem` roles. Update only directly coupled
  structural/browser tests; add no helper, component abstraction, dependency,
  JavaScript behavior, test-only production attribute, style redesign, broader
  role sweep, or adjacent settings cleanup.
- **AC-A11Y-10:** Flattening the release-table `aria_sort` calculation
  preserves its complete semantic matrix: the default view exposes `none` on
  every sortable header; exactly the active header exposes `descending` or
  `ascending` for the current direction; every inactive header remains `none`.
  Native sort links, accessible names, stable focus-restoration ids, 44px
  targets, focus treatment, htmx attributes, Tab order, and Enter activation
  remain unchanged.
- **AC-QA-45:** A parameterized unit truth table covers inactive/active crossed
  with `asc`/`desc`. Every row asserts `is_active`, current `aria_sort`, and the
  next `sort`/`dir` in both `href` and `hx_get`; inactive columns remain `none`,
  returned key/label order remains `SORT_COLUMNS`, filters remain in both URLs,
  and the default sort still marks no column active.
- **AC-QA-46:** A repository-anchored, CWD-independent AST guard proves the
  module and `sort_columns` function exist and rejects any conditional
  expression nested inside another conditional expression in
  `couchpotato/ui/releases_view.py`. It fails on the current line 271, passes
  after the flat branch, and kills both the exact old syntax and a wrapped
  nested equivalent.
- **AC-QA-47:** TDD evidence records the behavior characterization green on the
  base, the AST guard red for line 271, both green after the minimum refactor,
  and independently killed mutations that reintroduce nested syntax, invert
  active ascending/descending ARIA state, assign a direction to an inactive
  column, and alter active/inactive next-click direction.
- **AC-SEC-22:** Change only fixed-string `aria_sort` derivation. Preserve
  normalized sort/direction allowlists and defaults, `_query()` URL encoding,
  `quote(movie_id, safe='')`, `href`/`hx_get` construction, and malformed-query
  success behavior. Add no HTML-capable value, logging, telemetry, network or
  authorization change, or exposure of release names, titles, identifiers,
  paths, or credentials.
- **AC-PROD-11:** The refactor is user-invisible: column order and labels,
  visible active arrow, filters, row ordering, focus behavior, and URLs remain
  unchanged. An inactive column starts descending, the active column reverses,
  and current ARIA state never reuses the intentionally opposite next-click
  direction. Add no copy, control, persistence, analytics, or telemetry.
- **AC-SIMP-33:** Replace only the nested `aria_sort` expression with a local
  `none` default and a direct active-column branch selecting `descending` or
  `ascending`. Add no helper, abstraction, dependency, configuration,
  template/browser change, broader conditional sweep, or adjacent sorting,
  filtering, validation, query, or URL refactor.
- **AC-QA-48:** A focused parameterized `getMeta` characterization drives a
  fake `enzyme.MKV` result through AVC, HEVC, unknown, exact-match near-miss,
  empty, explicit-`None`, and missing-`codec_id` cases. It asserts AVC remains
  `H264`, HEVC remains `x265`, every other present value is returned unchanged,
  and a missing attribute returns `''` without collapsing the result to `{}`.
- **AC-QA-49:** A repository-anchored, CWD-independent AST guard proves the
  module and `getMeta` method exist and rejects a conditional expression nested
  beneath another conditional expression anywhere in
  `couchpotato/core/plugins/scanner/media_parser.py`. It fails on the current
  lines 165-167 and on a wrapped equivalent, then passes after flattening. This
  module-wide guard is the recurrence mechanism while separately planned
  nested expressions remain elsewhere in the repository.
- **AC-QA-50:** TDD evidence records AC-QA-48 green on exact master, AC-QA-49
  red on the intended expression, and both green after the minimum refactor.
  Independently applied and diff-confirmed mutations restore exact and wrapped
  nested syntax, swap each fixed mapping, discard the unknown fallback, alter
  the missing-attribute default, and broaden an exact comparison; each intended
  test must fail before restoration returns the focused suite to green.
- **AC-SEC-23:** Change only the in-memory exact-string normalization of the
  first parsed video track's `codec_id`. Add no dynamic evaluation, logging,
  error detail, filesystem/database/network operation, authorization change,
  or new exposure of codec metadata, titles, media paths, identifiers, or
  credentials; retain the parser exception and serialization boundaries.
- **AC-DATA-3:** Preserve the complete video-codec data contract: AVC maps to
  `H264`, HEVC maps to `x265`, exact-match near misses and all other present
  values (including `None`) pass through unchanged, and a missing attribute
  yields `''`. Audio, titles, dimensions, channels, quality scoring, NFO output,
  database state, and media files remain outside the production diff.
- **AC-PROD-12:** The refactor is user-invisible: scanning identical media
  returns identical codec, audio, title, dimension, and channel metadata;
  empty-track and parse-failure behavior are unchanged, and enzyme duration
  remains unexposed. Add no setting, copy, persistence, analytics, or telemetry.
- **AC-SIMP-34:** Replace only the nested video-codec expression with one local
  `codec_id` read and a direct `if`/`elif` mapping for AVC and HEVC, retaining
  the original value otherwise. Add no helper, abstraction, dependency,
  configuration, broader conditional sweep, or adjacent scanner cleanup.

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
- [x] **T22 — bound AppleTrailers FilmId parsing** — state: merged #381.
  Replace live issue `893fdc54-72f9-4fdd-a6c8-ff7503ecdb14` while preserving
  valid provider behavior and failing closed before the metadata request.
  Covers AC-QA-21, AC-OPS-14, and AC-SIMP-17.
- [x] **T23 — remove AppleTrailers builtin shadow** — state: merged #382.
  Resolve the S5806 finding introduced on T22's touched method with a local-only
  rename and a structural regression guard. Covers AC-QA-22 and AC-SIMP-18.
- [x] **T24 — adjudicate the Synology response-contract blocker** — state: merged #384.
  Preserve the working downloader, merge a load-bearing characterization of its
  distinct success and handled-failure results, then accept only exact issue
  `b6e7673f-30ed-4cf5-aa62-8298652e195f` if an exact-master analysis still
  reports the same false-positive identity. Covers AC-QA-23..25, AC-SEC-11..14,
  AC-OPS-15..18, AC-PROD-3, and AC-SIMP-19..20.
- [x] **T25 — simplify scanner loop predicates** — state: merged #385.
  Remove the redundant constant from the two exact S5797 predicates without
  touching scanner behavior or adjacent high-risk data flow. Covers AC-QA-26..27,
  AC-DATA-1, AC-SEC-15, AC-OPS-19..20, AC-PROD-4, and AC-SIMP-21.
- [x] **T26 — flatten available subtitle languages linearly** — state: merged #390.
  Replace live reliability issue `49dfbcdf-5c02-4e1a-bf65-294730029b44`
  without changing subtitle search decisions or the scanner-produced data
  contract. Covers AC-QA-28..30, AC-SEC-16, AC-OPS-21..23, AC-PROD-5..6, and
  AC-SIMP-22..24.
- [x] **T27 — characterize synchronous loop callbacks** — state: merged #392.
  Prove the production `ResultList.append` boundary consumes provider callbacks
  before their loops advance, then adjudicate all four non-escaping S1515
  closures only after exact-master verification. Covers AC-QA-31..33,
  AC-SEC-17, AC-OPS-24..25, and AC-SIMP-25.
- [x] **T28 — replace deprecated BeautifulSoup text filters** *(needs: T27)*
  — state: merged #393. Replace the three deprecated keywords without changing
  provider parsing or pagination, and enforce the production-wide recurrence
  guard. Covers AC-QA-34..35, AC-OPS-26, and AC-SIMP-26.
- [x] **T29 — flatten TMDB nested conditionals** *(needs: T28)* — state: merged #394.
  Make the three existing choices explicit while preserving TMDB request
  identity, order, parameters, and title merging. Covers AC-QA-36..38,
  AC-SEC-18, AC-OPS-27, and AC-SIMP-27.
- [x] **T30 — use native wizard groups** *(needs: T29)* — state: merged #395.
  Replace three generic group roles with native fieldsets while preserving the
  complete wizard flow and phone layout. Covers AC-A11Y-6, AC-DESIGN-3,
  AC-QA-39, AC-PROD-7, and AC-SIMP-28.
- [x] **T31 — use native release status and region semantics** *(needs: T30)*
  — state: merged #396. Replace redundant roles with native elements while
  preserving live status, keyboard scrolling, phone behavior, and isolated E2E
  fixture ownership. Covers AC-A11Y-7, AC-DESIGN-4, AC-QA-40, AC-DATA-2,
  AC-PROD-8, and AC-SIMP-29.
- [x] **T32 — simplify rTorrent URL-prefix checks** *(needs: T31)* — state: merged #398.
  Use one tuple prefix check while preserving endpoint and TLS behavior.
  Covers AC-QA-41, AC-SEC-19, AC-OPS-28, and AC-SIMP-30.
- [x] **T33 — use native replacement-choice radios** *(needs: T32)* — state: merged #399.
  Replace the custom radio-button state machine with native radios while
  retaining security, keyboard, focus, mobile, and exact-submission behavior.
  Covers AC-A11Y-8, AC-DESIGN-5, AC-QA-42, AC-SEC-20, AC-PROD-9, and AC-SIMP-31.
- [x] **T34 — remove obsolete iframe border attributes** *(needs: T33)*
  — state: merged #401.
- [x] **T35 — use native ordered settings lists** *(needs: T34)*
  — state: merged #402.
  Replace the three generic ordered settings collections with native lists
  while preserving layout, accessible names, controls, and persisted order.
  Covers AC-A11Y-9, AC-DESIGN-6, AC-QA-43..44, AC-SEC-21, AC-PROD-10, and
  AC-SIMP-32.
- [x] **T36 — flatten release-view sort conditionals** *(needs: T35)*
  — state: merged #403.
  Covers AC-A11Y-10, AC-QA-45..47, AC-SEC-22, AC-PROD-11, and AC-SIMP-33.
- [ ] **T37 — flatten scanner codec conditionals** *(needs: T36)* — state: awaiting-ci #404.
  Covers AC-QA-48..50, AC-SEC-23, AC-DATA-3, AC-PROD-12, and AC-SIMP-34.
- [ ] **T38 — make movie re-add category precedence explicit** *(needs: T37)*
  — state: queued.

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
- 2026-09-19: PR #381 merged as
  `87296567d8df208d10ea461987dd2577ef5d5ab3` after all hosted checks. Exact-
  master analysis `4564146d-7bc8-425a-86c3-cca52c0b4848` closed T22's S8786
  issue as `FIXED`, reduced code smells from 825 to 824, and held coverage at
  61.5%. It also created one S5806 finding on the touched method because the
  existing local name `id` shadows a builtin. T23's structural test failed red
  on that name and passed after the local-only rename to `film_id`; all twelve
  focused provider tests and Ruff are green. The fast gate collected 4,380
  Python unit-test items (4,361 passed, 14 skipped, 5 xfailed), then passed 42
  integration tests and 214 UI-unit tests with conformance and the 324-file
  trap guard clean.
- 2026-09-19: T23 merged as PR #382 at
  `2603014677e74c2cf47d0aa8fe53e361c76c2bd9` after the hosted gate passed.
  The next exact-master analysis, `12d7de29-472f-4924-b1aa-18f43605b8c5`,
  measured current master `d39cc1cb108a9f70fe58804ac1b9e2be3caf15b1`,
  closed T23's S5806 issue, and reported 823 open code smells: 1 blocker, 197
  critical, 328 major, 295 minor, and 2 info, with 61.5% coverage and 1.6%
  duplication. T24 starts from the sole blocker.
- 2026-09-19: T24 plan review found the blocker is an analyzer mistake, not a
  downloader defect: successful `_req` calls return the decoded server payload,
  while handled transport failures return `{'success': False}` and downstream
  login/task creation consume the success payload. The test-first
  characterization is green on production; a temporary mutation that discarded
  the decoded payload failed the success assertion for the intended reason,
  and restoring production byte-for-byte returned all 35 focused and adjacent
  Synology tests to green. Security, QA, simplicity, product, and operability
  lenses require a test-only slice, full review/delivery gates, exact-master
  analysis identity, and a single verified false-positive transition with an
  expiry condition.
- 2026-09-19: PR #384 merged at
  `2d1d7f3c92869278e9265068724e0f4080757c2c` after all hosted checks.
  Exact-master analysis `797f6bed-a383-4ef0-831e-ffa814e19915` retained the
  sole S3516 blocker with the same identity, so only issue
  `b6e7673f-30ed-4cf5-aa62-8298652e195f` was transitioned to false positive
  with its executable evidence and expiry condition. The verified backlog now
  has no blocker findings and 197 critical findings.
- 2026-09-19: T25 planning selected the two remaining S5797 findings as one
  behavior-neutral scanner slice. Security, QA, data, operability, product,
  and simplicity lenses constrain the production diff to the two redundant
  constant operands. A focused AST test failed on both original predicates,
  passed after the exact edits, and independently failed when either redundant
  operand was restored; all 69 focused and adjacent scanner tests are green.
- 2026-09-19: T25 passed the full local gate: Ruff, conformance, and the
  326-file trap scan; 4,368 unit tests (14 skipped, 5 expected failures), 42
  integration tests, 214 UI-unit tests, 176 Chromium tests, 2 isolation tests,
  10 mobile tests, and 96 accessibility tests. Two independent code reviewers
  and the security, QA, data, operability, product, simplicity, and fresh-
  verification Harness lenses returned clean on the complete worktree.
- 2026-09-19: T25 merged as PR #385 at
  `9258ffea3a5861b8cfc985090a182267f8522e47`; exact-master Sonar analysis
  closed both S5797 issue keys as `FIXED`. Subsequent reliability work through
  PR #389 left exact master at `41e860703d2b3a012ab5fa3f54bbb5f6c3584f23`
  with zero open bugs and 820 open code smells. T26 selects the remaining
  non-complexity HIGH reliability finding before broader maintainability work.
- 2026-09-19: T26 plan review selected one local `itertools.chain` replacement
  plus deterministic structural and multi-entry behavioral proof. Security,
  QA, operability, product, and simplicity lenses vetoed adjacent subtitle or
  scanner refactors, broader input contracts, timing tests, new dependencies,
  and any change to logging, network, filesystem, provider, or failure behavior.
- 2026-09-19: T26 red evidence isolated the old `sum(..., [])` expression while
  32 surrounding tests stayed green. The exact `chain.from_iterable`
  replacement passes all 33 focused tests. Restoring `sum` kills the structural
  guard, while replacing `from_iterable` with plain `chain` kills the
  multi-entry behavior test. The fast gate passed Ruff, conformance, the
  327-file trap scan, 4,381 unit tests (14 skipped, 5 expected failures), 42
  integration tests, and 214 UI-unit tests.
- 2026-09-19: T26 merged as PR #390 at
  `45e51430bd137418097ec8ecf810d2eb14fe459c`. Exact-master analysis closed
  `49dfbcdf-5c02-4e1a-bf65-294730029b44` as `FIXED`, reduced open code smells
  from 820 to 819, and reported zero bugs and vulnerabilities with 61.6%
  coverage and 1.6% duplication. Three renamer S1515 callbacks were then
  accepted as false positives after independent lifetime review proved they are
  invoked synchronously before their loop advances; the open count fell to 816.
- 2026-09-19: T27 planning initially misclassified two provider callbacks as
  deferred because its reproduction passed a plain list directly to `_search`.
  A clean reviewer followed the public `Provider.search` boundary and found it
  always supplies `ResultList`, whose `append` invokes `searcher.correct_release`
  and `score.calculate` before returning to the provider loop. With the proposed
  bindings removed, production-shaped runs still observed BinSearch outcomes
  `[False, True]` and Pirate Bay scores `[10, 50]`; only the impossible plain-list
  harness failed. The production edits and false-boundary assertions were
  removed. Real-`ResultList` characterization through
  `MovieSearcher.correctRelease` and `Score.calculate` now proves both callbacks
  are consumed per row; bypassing either handler invocation kills its focused
  test. The other two findings are likewise synchronous:
  `list(filter(...))` is exhausted before `os.walk` advances and `sorted` calls
  its key before the surrounding mapping iteration advances. T27 is therefore
  a test-only false-positive evidence slice for all four issues, with an expiry
  condition if any callback becomes stored or deferred.
- 2026-09-19: T27's final fast gate passed Ruff, conformance, the 327-file trap
  scan, 4,383 unit tests (14 skipped, 5 expected failures), 42 integration
  tests, and 214 UI-unit tests. Two fresh independent reviewers returned clean
  after separately bypassing each real handler invocation and observing the
  intended focused failure. The test-only slice is ready for hosted CI and
  cloud review; all four Sonar transitions remain post-merge work.
- 2026-09-19: T28 starts from T27's reviewed head while its required cloud
  review is quota-blocked. Red evidence found all three production `text=`
  filters; the production-wide AST guard, HDTrailers behavior coverage, and
  real two-page IPTorrents navigation are green after the exact keyword-only
  replacements. Restoring any one deprecated keyword kills the guard. T29
  through T38 are recorded as a strictly sequential local queue; no additional
  remote branch is created before T27 merges and receives exact-master Sonar
  verification.
- 2026-09-19: T28 review found the first IPTorrents fixture never reached the
  changed pagination selector. A production-shaped two-response test now
  asserts both page URLs and both result payloads; changing `Next` to a missing
  label kills it. The repaired 34-test provider/parser suite, Ruff, the
  327-file trap scan, and security, QA, product, and fresh-verification lenses
  are clean. External delivery remains blocked on the preceding merge and its
  exact-master Sonar verification.
- 2026-09-19: T27 merged as PR #392 at
  `98282f89497c95e3978d250d48aeb8b38f91c231` after every required hosted
  check passed, including the post-quota Claude review. Exact-master analysis
  `93ec27c6-9c2b-4bc9-953b-8b63f3cbd7d4` reported that same full SHA as both
  revision and project version after 4,425 Python/integration tests and 214 UI
  unit tests passed. All four S1515 issues retained their reviewed identities;
  each was individually transitioned to false positive with its distinct
  synchronous-consumption evidence and expiry condition, and each comment and
  changelog transition was re-fetched and verified. T28 is now unblocked.
- 2026-09-19: T28 rebased cleanly onto the exact T27 merge. Its final local
  fast gate passed Ruff, conformance, the 327-file trap scan, 4,386 unit tests
  (14 skipped, 5 expected failures), 42 integration tests, and 214 UI unit
  tests. The complete rebased diff is at the mandatory independent local
  review gate before push.
- 2026-09-19: T29 starts locally on T28's pinned reviewed tree. Its focused 58
  provider tests and Ruff are green; external delivery remains strictly
  blocked on the preceding merges and exact-master Sonar checks.
- 2026-09-19: T28 merged as PR #393 at
  `0df966e121589a20d45137d2e266ca1eb020531d` after all hosted checks passed,
  including CodeQL for Python, JavaScript, and Actions, Claude review, Docker,
  accessibility, and the full UI E2E matrix. Exact-master analysis
  `539d32c3-69aa-4c92-b336-245dd0c936d7` reported the same merge SHA as its
  revision and project version after 4,428 Python/integration tests and 214 UI
  unit tests passed. Exact issue `38a71bc3-be40-4f6d-9773-85aeb9db87fa`
  closed as `FIXED`; open code smells fell from 812 to 811 and major findings
  from 320 to 319. T29 is now unblocked on the exact merge.
- 2026-09-19: T29 rebased onto T28's exact merge and retained the response-ID
  behavior where later language requests use the canonical ID returned by the
  English response. Its final local fast gate passed Ruff, conformance, the
  327-file trap scan, 4,396 unit tests (14 skipped, 5 expected failures), 42
  integration tests, and 214 UI unit tests. The complete rebased diff is at
  the mandatory independent local review gate before push.
- 2026-09-19: T29's first final review found the new characterization covered
  only one successful additional language, allowing reversal, truncation,
  `languages=None` breakage, exception swallowing, falsey `search_type` drift,
  and loss of the default-language fallback to survive. The recurring branch-
  coverage class was addressed as one mechanism: 65 focused provider tests now
  pin two-language order and titles, `None` and empty lists, secondary-request
  exception propagation, all supported falsey search-type inputs, and fallback
  to the English response. The full fast gate was rerun clean after the repair.
- 2026-09-19: T30 starts locally on T29's clean focused-test tree. The three
  generic wizard groups are native fieldsets with pinned accessible names; a
  Pixel 5 browser test drives two tracker groups and both downloader groups,
  asserts visible controls, group bounds, descendant bounds, and document
  width. The unit guard, 10 existing wizard Chromium tests, and the new mobile
  test are green. Removing the speculative `min-w-0` utility did not fail the
  browser proof, so no layout class was added solely to clear the finding.
- 2026-09-19: T29 merged as PR #394 at
  `12b43ff1c9dd51989465849c0b2a58e6039c10f9` after all hosted checks passed,
  including CodeQL for Python, JavaScript, and Actions, Claude review, Docker,
  accessibility, and the full UI E2E matrix. Exact-master analysis
  `4731ea90-1d08-432c-a86a-efc9b1057c08` reported the same merge SHA as its
  revision after 4,457 Python/integration tests and 214 UI unit tests passed.
  All four targeted TMDB findings closed as `FIXED`; open code smells fell
  from 811 to 807, with critical findings falling from 195 to 193 and major
  findings from 319 to 317. T30 is now rebased onto that verified merge.
- 2026-09-19: T30's rebased local gate passed Ruff, conformance, the 328-file
  trap scan, 4,439 Python tests (14 skipped, 5 expected failures), 214 UI unit
  tests, 10 existing wizard Chromium tests, and its Pixel 5 flow. The three
  exact pre-merge S6819 issues remain open: `cb6900a6-9f36-4991-ae8e-1f14639caea0`,
  `2a0abba3-eabd-4f8a-af30-52ceb777ab00`, and
  `eb60a0ce-4ac6-478c-a761-9e62f78a6b65`. Two independent clean reviewers
  verified accessible group names, the focused axe scan, and phone bounds;
  reverting a fieldset killed the structural test and forcing a 500px minimum
  width killed the mobile test at 541px in a 393px viewport.
- 2026-09-20: T30's first hosted run correctly rejected the unsupported plan
  state word `done`; `merged #394` passes the 30-test lifecycle guard. Cloud
  review then alleged native fieldset border chrome. A real Pixel 5 run before
  any production change measured `0px` on all four computed border widths for
  every new group, disproving the visual-regression hypothesis. The mobile
  test now pins those computed widths so a future reset regression cannot make
  the same claim true silently; no speculative production class was added.
- 2026-09-19: T31 starts locally on T30. The release mismatch status and table
  scroller use native output/section semantics while retaining the focusable
  named overflow region. Review converted the original markup-only proof into
  a Pixel 5 test with genuine overflow, visible focus, and ArrowRight scrolling,
  then isolated the mismatch state behind a dedicated seeded movie/profile/
  release and an executable fixture-ownership guard. The focused 83 unit tests
  and full 12-test mobile project are green; two reviewers are clean.
- 2026-09-20: T30 merged as PR #395 at
  `9faf9bae720c18f00692ef5fcf35dd46cfb33481` after the complete hosted matrix
  passed. Exact-master analysis `7732d9d2-ef45-4969-a817-5823629572dd`
  reported that merge SHA after 4,439 Python tests (14 skipped, 5 expected
  failures) and 214 UI unit tests passed. All three targeted S6819 findings
  closed as `FIXED`; open code smells fell from 807 to 804 and major findings
  from 317 to 314. T31 is rebased onto that verified merge. Its exact open
  S6819 targets are `777e51e0-37ac-49d3-b1d7-847b18a02ab9` and
  `1ed8125d-8b2a-4ae5-a46c-f2aed668e9e2`; the adjacent S6845 finding remains
  outside this replacement because keyboard scrolling requires the overflow
  region to stay focusable and is covered by executable browser evidence.
- 2026-09-20: T31's exact-base gate passed Ruff, conformance, the 329-file
  trap scan, 4,441 Python tests (14 skipped, 5 expected failures), 214 UI unit
  tests, 113 focused route/fixture/plan tests, and all 13 mobile tests. The
  complete rebased diff is at the mandatory independent local review gate.
- 2026-09-20: T31's first independent review found three mechanisms that were
  weaker than their claims. The focus assertion accepted a transparent
  outline, the mobile criterion overclaimed repair of document overflow that
  is already present on the exact T30 base, and `verify()` checked only the
  mismatch movie's status. The test now requires a non-transparent rendered
  outline, keeps the scroller's bounds inside the viewport and proves keyboard
  scrolling neither moves nor widens the document. The criterion now names
  that owned boundary explicitly. A seven-case database-mutation matrix now
  requires `verify()` to reject the wrong movie/profile link, an included
  release quality, wrong release status or quality, missing or extra release,
  and a missing profile. After the first-round corrections, 4,444
  Python tests passed (14 skipped, 5 expected failures), all 214 UI unit tests
  passed, and all 13 mobile-browser tests passed.
- 2026-09-20: T31 merged as PR #396 at
  `1fab0f163ecc8218172c04a97e0b6ffb0b5801d2` after every hosted check passed,
  including Python, UI E2E, mobile accessibility, Docker, three-language
  CodeQL, and Claude review. Exact-master analysis
  `6fc87502-613c-4f12-b436-30c224e95005` used 4,448 passing Python tests
  (14 skipped, 5 expected failures) and 214 passing UI unit tests. Both S6819
  targets closed as `FIXED`; open smells fell from 804 to 803 and major
  findings from 314 to 312. The expanded fixture verifier also introduced
  critical S3776 `99cc2f87-9499-4e84-9243-2935710f9f49`; its relationship
  checks are now extracted behind the already load-bearing seven-case mutation
  matrix before T32 begins.
- 2026-09-20: The T31 corrective extraction merged as PR #397 at
  `463d5f2734277448ba28244fb297c938c909e590` after the complete hosted matrix
  passed; the one unrelated accessibility contrast flake passed its automatic
  test retry and a clean failed-job rerun. Exact-master analysis
  `1929e2cc-02df-4bf0-a0ba-a994d5b5baaf` reported that SHA as both revision and
  project version after 4,448 Python tests (14 skipped, 5 expected failures)
  and 214 UI unit tests passed. The introduced S3776 issue closed as `FIXED`;
  open smells fell from 803 to 802 and critical findings from 194 to 193.
- 2026-09-20: T32 starts on that exact verified merge. The two rTorrent
  HTTP-RPC scheme
  predicates are one tuple prefix check, with an AST guard that pins both and
  only those schemes. Seventy rTorrent-selected downloader tests are green;
  independently removing either scheme kills the guard while the restored tree
  passes Ruff and two clean reviews.
- 2026-09-20: T32 reached PR #398 at reviewed SHA
  `588ab5df57496b459abeac4e179b28879fd0f7b9`. Its exact-base fast gate passed
  Ruff, conformance, the 329-file trap scan, 4,407 unit tests (14 skipped,
  5 expected failures), 42 integration tests, and 214 UI unit tests. Hosted CI
  and cloud review are in progress.
- 2026-09-20: T32 merged as PR #398 at
  `172339ae2c9634b97ff9e94c1276b0b9462777fb` after the full hosted matrix
  passed, including Claude review, three-language CodeQL, accessibility,
  Docker, and desktop/mobile E2E. Exact-master analysis
  `8bd7c1ac-1a5a-41db-b579-8e114151a184` reported that SHA as revision and
  project version after 4,449 Python tests (14 skipped, 5 expected failures)
  and 214 UI unit tests passed. S8513 issue
  `25d90f0e-3318-4a1e-81d5-9dce379e67f9` closed as `FIXED`; open smells fell
  from 802 to 801 and major findings from 312 to 311. The post-CI Harness
  security, QA, operability, product, and fresh-verification lenses all
  measured tree `827c8a56f722ca688079d3bf5188352e03851d53` and returned clean.
- 2026-09-20: T33 starts on that exact verified merge. Native same-name radios
  and a fieldset replace the custom ARIA/button state machine and its manual
  arrow-key method. Backend/template coverage, nine functional browser tests,
  27 accessibility tests, and five mobile tests are green. Three targeted
  production mutations (native control type, exact bound value, and accessible
  group name) were killed; the configured mutation runner correctly reports
  this template outside its scope. The broad local gate passed 4,408 Python
  unit tests, 42 integration tests, and 214 UI unit tests. Two independent
  code reviewers and fresh acceptance-criteria verification were clean at
  `4065b768b04c27fe45f55694323843e715afe9ee`; PR #399 is open for hosted CI.
- 2026-09-20: T33 merged as PR #399 at
  `c21b1e9512fc2e46449675e77f15e316d1d0f684` after every hosted check passed.
  The post-CI security, QA, accessibility, design, and product lenses were
  clean on matching tree `f335bf47c2a1dbd8cf64c6d5f649a731f1c95c91`.
  Exact-master analysis `41aedabe-d60a-462b-8621-69fade0663b6` reported the
  merge SHA as both revision and project version after 4,450 Python tests
  (14 skipped, 5 expected failures) and 214 UI tests passed. Web:S6819 issue
  `c40680a6-882f-494d-853d-b886f05f2140` closed as `FIXED`. The scan also
  raised Web:S6853 against a wrapping label whose runtime `x-text` filename
  and exact accessible name are browser-tested; that static-analysis false
  positive was documented and accepted. Open smells fell from 801 to 800 and
  major findings from 311 to 310. T34 starts on that exact verified merge.
- 2026-09-20: T34 removes both production `frameborder` instances and adds a
  guard across all 35 production HTML templates. The guard failed red on the
  two base offenders and killed independent recurrence mutations in each
  template. Two Chromium trailer workflows, 4,409 Python unit tests, 42
  integration tests, and 214 UI unit tests passed. Two independent code
  reviews and fresh verification were clean at
  `2e354a1f62b97137725ab5c31c8b16fbacd55c92`; PR #400 subsequently passed
  every hosted check and merged at
  `2e82a52e053ef34d327ca57d7b1e1d0a455ba1f9`.
- 2026-09-20: Exact-master analysis
  `8165cee6-e767-400a-8e72-61c058c817a6` reported the T34 merge SHA as both
  revision and project version after 4,451 Python tests (14 skipped, 5
  expected failures) and 214 UI tests passed. Web:S1827 issue
  `fe8e9347-1432-4dd1-ac8b-68b47d9b9a5d` closed as `FIXED`; removing both
  obsolete instances closed two major findings, taking open smells from 800
  to 798 and major findings from 310 to 308. Post-CI QA then reproduced a
  vacuous-pass path in the recurrence guard when pytest runs outside the
  repository root. T34 remains open while a correction anchors discovery to
  the test file and asserts the production template set is non-empty.
- 2026-09-20: The T34 correction reproduced the former false-green from
  `tests/unit`, then anchored template discovery to the test file and added
  explicit missing-root and empty-set failures. The corrected guard discovers
  all 35 tracked production HTML templates from either working directory;
  missing-root, empty-set, and reintroduced-attribute mutations all fail as
  intended. The proportionate gate completed with 4,409 Python unit tests, 42
  integration tests, and 214 UI unit tests passing. Two independent code
  reviewers and an independent verifier were clean at
  `7e8cd6760d15e8f4ece56c7faba4435b7bf01344`; correction PR #401 is open for
  hosted CI.
- 2026-09-20: T34 correction PR #401 passed every applicable hosted check,
  including three-language CodeQL, Python, Docker, and cloud review, then
  merged at `e13f4ef3a8321c5f76cad6f90c59ce597e203ecf`. Post-CI security, QA,
  accessibility, design, product, and fresh-verification lenses were clean.
  Exact-master Sonar analysis `0fc32caf-63e2-4b03-ab94-f3ec9e492c55`
  reported that SHA as both revision and project version after 4,451 Python
  tests (14 skipped, 5 expected failures) and 214 UI tests passed. The T34
  issue remains closed as `FIXED`; open smells remain 798, with 308 major, 193
  critical, 295 minor, 2 info, and 0 blocker findings. Coverage remains 62.0%
  and duplication 1.6%.
- 2026-09-20: T35 plan cycle completed with security, QA, simplicity,
  product, design, and accessibility coverage. It scoped the work to the
  three labelled ordered settings collections and their directly coupled
  tests, with native semantics, unchanged layout and persistence, and
  non-vacuous structural/browser proof.
- 2026-09-20: T35 failed red because Categories was not a native `ol`, then
  passed after the three list containers and repeated rows changed to native
  `ol`/`li` elements with all classes and Alpine bindings retained. Independent
  regressions of Categories, Quality profiles, and Qualities in this profile
  each killed the structural test. The complete local gate passed 4,410 Python
  unit tests, 42 integration tests, 214 UI unit tests, 177 desktop browser
  tests, 2 worker-isolation tests, 15 mobile tests, and 97 accessibility tests;
  the focused settings suites additionally proved all three populated lists,
  persisted ordering, and 393px light/dark containment.
- 2026-09-20: The mandatory general review gate found that Tailwind Preflight's
  marker reset can cause Safari/VoiceOver to remove otherwise-native lists from
  the accessibility tree. T35 therefore retains the documented `role="list"`
  compatibility mechanism on each native `ol`; tests require it and continue
  to reject redundant `listitem` roles. Any Sonar complaint about those three
  necessary roles must be adjudicated with this cross-browser evidence rather
  than removed.
- 2026-09-20: T35 merged as PR #402 at exact master
  `d4d59b733ef6d8aba87e5fabded463554c92382e`; every hosted gate and the post-CI
  Harness review passed. Exact Sonar analysis
  `61d87754-a369-4206-8369-47793c286517` closed all six targeted Web:S6819
  issues. Three new Web:S6822 complaints about the documented markerless-list
  Safari compatibility roles were commented with platform and mutation-test
  evidence and resolved `FALSE-POSITIVE`. Open smells fell from 798 to 792 and
  majors from 308 to 302; coverage stayed 62.0%, duplication 1.6%, and the
  reliability, security, and maintainability ratings remained A.
- 2026-09-20: T36 plan cycle completed with security, QA, simplicity, product,
  design, and accessibility coverage. It scoped the implementation to the
  single nested `aria_sort` expression and requires a four-row current-state /
  next-click truth table plus a module-scoped AST regression guard; no design
  criterion was added because markup and visible behavior must remain
  byte-identical.
- 2026-09-20: T36 behavior characterization passed on the base, then the new
  AST guard failed red on the nested conditional at line 271. The minimum flat
  branch made the focused suite green. Manual mutations independently
  reintroduced the exact and a wrapped nested expression, inverted active ARIA
  direction, assigned a direction to inactive columns, and changed next-click
  direction; the AST or four-row truth-table test killed each mutation. Ruff
  and 111 focused release/plan tests passed. The broad gate then passed 4,457
  Python tests (14 skipped, 5 expected failures) and all 6 release-control
  browser tests.
- 2026-09-20: T36 QA review found the AST collector was function-scoped even
  though AC-QA-46 deliberately requires a module-level recurrence mechanism.
  The collector now walks the parsed module while retaining the explicit
  `sort_columns` existence check; a behavior-preserving nested expression
  inserted into unrelated `_clean` failed at its own line, proving the shared
  S3358 mechanism is enforced across `releases_view.py`.
- 2026-09-20: T36's amended exact commit passed every Harness review lens and
  the final seven-criterion verification matrix. Two independent local code
  reviewers then returned clean; one compared base and head behavior across
  11,664 valid sort, direction, filter, identifier, and web-base combinations
  without a difference. PR #403 is open for hosted CI and cloud review.
- 2026-09-20: PR #403 merged as exact master `5a7119af`. All hosted checks and
  the post-CI Harness review were clean. Sonar CE task
  `26313856-4787-466f-86a9-f35aaaa12ac6` produced exact-version analysis
  `e003576d-3a3e-45ed-aeeb-6769a6ea4328`; issue
  `32683d94-37bc-4cf3-936b-06eb008fc3ec` closed as fixed. Open smells fell
  from 792 to 791 and majors from 302 to 301; coverage stayed 62.0%,
  duplication 1.6%, and all three ratings remained A.
- 2026-09-20: T37 plan cycle completed with security, data, QA, simplicity,
  and product coverage. The existing suite characterized only enzyme's absent
  path, so T37 requires a seven-case codec contract, a module-wide nested-
  conditional recurrence guard, and explicit mapping, fallback, default, and
  exact-comparison mutation evidence. The production scope is only the codec
  read plus flat AVC/HEVC branches; adjacent scanner metadata remains fixed.
- 2026-09-20: T37 behavior characterization passed seven AVC, HEVC, unknown,
  near-miss, empty, explicit-`None`, and missing-attribute cases on exact
  master. The module guard then failed red on the nested expression at line
  166, and both passed after the minimum flat branch. Independent mutations
  reintroduced exact and wrapped nested expressions, changed each fixed codec
  mapping, discarded unknown/`None` passthrough, changed the missing-attribute
  default, and broadened matching to be case-insensitive; the intended guard
  or contract row killed every mutation before restoration. The restored
  focused gate passed 121 tests with Ruff clean, and the broad gate passed
  4,465 Python tests (14 skipped, 5 expected failures).
- 2026-09-20: T37 passed every Harness review criterion and two independent
  local code reviews on exact commit `f22bd8e3`. Reviewers reproduced base/head
  equivalence across the required cases, 511 varied and hostile codec values,
  the structural failures, and all behavior mutation kills. PR #404 is open
  for hosted CI and cloud review.
