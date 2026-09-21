# PERF-001: make the page-speed budgets an automated check rather than a manual command

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** dependency remediation implemented; CI-gating decision remains draft
**Lenses run:** security, QA, simplicity, architecture, product
**Owner decision that opened this:** 2026-09-04, choosing "wire it into CI" over
recording a hold or dropping Lighthouse, when the recurring `extract-zip`
advisory forced the question of whether the tool earns its place.

## Problem

The project's engineering standards make Core Web Vitals a must-do for any user
interface and ask for lab budgets enforced as tests in CI. At the time this
plan opened, the repository had tooling for that and ran none of it
automatically.

The former `lighthouserc.js` was complete and carefully written. `package.json`
exposed it as `npm run test:lighthouse`. Nothing invoked it: `git grep -nI "lhci\|lighthouse"
-- .github/ Makefile scripts/` returns nothing, `scripts/verify.sh` has seven
stages and none is Lighthouse, and the pre-push hook does not run it. It fires
only when a person types the command.

Three costs follow.

1. **The standard is not met and nothing says so.** A performance regression
   ships and is discovered by the person using the software.
2. **The risk is carried without the benefit.** `@lhci/cli` drags in
   `lighthouse`, `puppeteer-core` and `@puppeteer/browsers`, which is the whole
   of the `extract-zip` advisory GHSA-jmr9-qjv8-65gv (no patched release exists;
   `extract-zip@2.0.1` is newest). That finding has now been held twice with
   identical reasoning, in #274 and #299, re-derived by hand each time.
3. **The safety work around it is unexercised.** `lighthouserc.js`'s upload block
   and `tests/unit/lighthouse_upload_stays_local.test.ts` exist because the tool
   was previously POSTing rendered reports, embedding full-page screenshots of
   the user's media library, to a public Google endpoint (fixed in #291, T47).
   That guard protects a command almost nobody runs.

The measurement that makes this concrete: the four URLs `lighthouserc.js`
collects are `/`, `/available/`, `/add/` and `/settings/` on port 5050, and no
automated check has ever loaded any of them with a stopwatch.

## Not in scope

- **Field data.** CrUX is the metric Google actually ranks on, and a lab score is
  necessary-but-not-sufficient. This spec buys the lab budget only. Watching
  Search Console or PageSpeed Insights stays manual.
- **INP.** Lighthouse lab runs cannot measure Interaction to Next Paint; Total
  Blocking Time is the accepted lab proxy and is what this spec budgets.
- **Making Lighthouse a required CI gate.** This dependency-remediation change
  keeps the existing opt-in commands. Job placement, runtime variance and
  blocking versus reporting remain the separate decision this spec originally
  opened.
- **Changing the upload-safety outcome from #291.** The LHCI-specific mechanism
  is replaced because that tool is removed, but reports must remain local,
  bounded, gitignored and excluded from Docker exactly as before.
- **A production performance monitor.** Nothing here reaches the running server.

## Design intent, for the lenses to challenge

Three choices that want scrutiny rather than assumption:

**Reuse Playwright's Chromium instead of letting Lighthouse fetch its own.** The
runner passes Playwright's installed executable directly to `chrome-launcher`.
Lighthouse 13's Puppeteer browser package no longer depends on `extract-zip`,
and the runner has no browser-download path, so the vulnerable package is
absent rather than merely unreachable.

**A guard whose assertions are all warnings is a guard that cannot fail.** The
former `lighthouserc.js` set every performance assertion to `warn`. Wiring
that into CI unchanged would produce a green job that proves nothing, which is
worse than no job because it launders an unknown into a tick. At least the core
budgets must be `error`.

**Budget numbers must be derived, not asserted.** The standards name LCP 2.5s,
CLS 0.1, TTFB 800ms and FCP 1.8s. Whether this app currently meets them on a CI
runner is unknown. The honest sequence is to measure first, then set the budget
at or tighter than the standard where the app already passes, and record an
explicit, dated gap where it does not, rather than setting a number the app
fails on day one and immediately learning to ignore.

## Open questions for the planning cycle

1. Does the performance check block the merge, or report only at first? A gate
   that flaps teaches people to re-run until green (§11, flaky guards), and
   Lighthouse on a shared runner is a known source of variance. What evidence
   would settle it?
2. Where does it run: a new job, or inside `accessibility`, which already has
   the server, the seed and the browser? A new required status check has to be
   added to branch protection by hand.
3. `numberOfRuns: 3` across four URLs is twelve page loads. What is the wall
   clock, and does it belong in the merge path at all or on a schedule?
4. The direct policy asserts `categories:accessibility` at `error`, which the
   axe suite already covers more precisely. Does that assertion earn its place,
   or is it duplicated scope for `lens-simplicity` to cut?

## Acceptance criteria

### Dependency and architecture

- **AC-SEC-1 / AC-ARCH-1:** `package.json` directly pins
  `lighthouse@13.5.0` and every package imported by repository code. It removes
  `@lhci/cli` and `@lhci/utils` without an override or compatibility shim.
- **AC-SEC-2 / AC-QA-12:** A clean `npm ci` followed by
  `npm ls extract-zip @lhci/cli @lhci/utils --all` finds none of those packages;
  the lockfile has no entries for them, and `npm ls lighthouse --all` resolves
  the intended direct version.
- **AC-ARCH-3:** The replacement is one project-specific runner and, at most,
  one declarative policy module. It does not recreate LHCI config discovery,
  inheritance, uploads, server management or a general assertion framework.
- **AC-ARCH-4:** The runner uses Lighthouse's supported programmatic API and an
  explicitly declared browser-lifecycle dependency. It runs on the repository's
  Node 24 baseline and never downloads or unpacks a browser.

### Stable command and audit policy

- **AC-PROD-1 / AC-QA-1:** `npm run test:lighthouse` remains the public command
  and performs exactly three runs for each fixed local route: `/`,
  `/available/`, `/add/` and `/settings/` on `localhost:5050`. Each result must
  remain on the fixed origin and reach its declared final page; the historical
  `/available/` redirect is expected to finish at `/wanted?filter=available`.
- **AC-SIMP-4 / AC-PROD-4:** Preserve simulated mobile throttling, the existing
  skipped audits and the explicit thresholds and severities: performance 0.8
  warn, accessibility 0.9 error, best-practices 0.9 warn, SEO 0.8 warn;
  `http-status-code`, `image-alt`, `link-name` and `button-name` error;
  `color-contrast` 0.9 warn; FCP 3000 ms, LCP 4000 ms, TBT 500 ms and CLS 0.1
  warn. The HTTP-status assertion is the one reliability invariant retained
  explicitly from the old recommended preset, preventing a 4xx document from
  passing as the requested page. PWA, text compression and render-blocking
  remain non-gating. Do not reproduce LHCI's broad `lighthouse:recommended`
  preset.
- **AC-QA-2 / AC-QA-5:** Pure unit tests prove every route/run pair is invoked,
  threshold boundary semantics are correct, warning failures remain visible but
  non-blocking, and error failures make the command fail.
- **AC-QA-3 / AC-PROD-3:** Browser launch, server preflight, Lighthouse,
  malformed-result and report-write failures exit nonzero with concise stage-
  specific guidance. The server is checked before any audit begins.
- **AC-OPS-1 / AC-QA-3:** Every Lighthouse invocation has a 120-second
  deadline. A stalled audit exits nonzero with its route and run number, then
  closes Chromium through the normal cleanup path.
- **AC-ARCH-7:** Browser cleanup is guaranteed through `finally` paths without
  replacing the primary failure.

### Privacy and bounded evidence

- **AC-SEC-3 / AC-PROD-6:** The runner contains no upload phase, remote-report
  target, upload environment override or report-artifact workflow. Reports,
  screenshots, URLs and audit results are never published to a third party.
- **AC-SEC-4 / AC-QA-7:** Each successful route/run pair writes deterministic,
  distinguishable JSON and HTML reports only beneath repository-root
  `.lighthouseci/`. Filenames are repository-controlled, traversal-safe and
  bounded; a completed machine-readable summary is written only after all 12
  results have been processed.
- **AC-QA-8:** Each invocation safely removes and recreates only the
  runner-owned output root before preflight. A directory symlink is removed as
  an entry rather than followed, stale evidence cannot masquerade as current
  success, and a partial failure cannot leave a successful summary.
- **AC-SEC-5:** `.lighthouseci/` remains ignored by Git and excluded from the
  Docker build context. Tests use Git as the ignore oracle and retain the
  existing Docker-owned exclusion rather than modelling ignore syntax.
- **AC-SEC-8 / AC-ARCH-10:** Audit URLs and output locations cannot be changed
  by positional arguments or environment variables; only the fixed loopback
  origin and repository-owned output root are accepted.
- **AC-SEC-6 / AC-ARCH-11:** Delete the obsolete LHCI configuration and its
  private-API guard. Replacement tests inspect the new runner's real fixed
  policy, output confinement, bounded filenames, lack of upload behavior and
  ignore protections.

### Scope and verification

- **AC-PROD-7:** `npm run test:all` continues to invoke
  `npm run test:lighthouse` after unit and E2E tests.
- **AC-PROD-9 / AC-SIMP-7:** This change does not add Lighthouse to GitHub
  Actions, `make verify`, `make verify-fast` or pre-push. PERF-001's CI timing,
  placement and gating questions remain open.
- **AC-QA-15:** A real run against a seeded local CouchPotato instance completes
  all 12 Lighthouse 13 audits, writes the expected local evidence and records
  wall-clock time and score variance for the later CI decision.
- **AC-QA-16:** Red/green and mutation evidence demonstrates that changing the
  fixed routes or run count, weakening an error threshold, escaping the output
  root, accepting an incomplete result or reintroducing a removed dependency
  makes the focused guard fail before restoration.

## Implementation sequence

1. Add failing focused tests for the direct dependency graph, fixed policy,
   threshold evaluation, complete 12-run orchestration, output confinement,
   failure propagation and local-only report behavior.
2. Replace the LHCI dependencies, configuration and command with the smallest
   direct Lighthouse 13 runner that satisfies those tests.
3. Regenerate the lockfile from a clean install and prove the three removed
   packages are absent from both the lockfile and installed graph.
4. Run focused mutation checks, the JavaScript unit suite, dependency audit and
   one real local Lighthouse run. Record any environmental limitation rather
   than weakening the policy.
5. Run the multi-lens review gate; CI integration remains separate follow-up
   work after runtime and variance are measured.

## Implementation evidence

- 2026-09-21: The red test failed because the repository-owned direct runner
  did not exist. The green implementation replaced both LHCI packages with
  exact `lighthouse@13.5.0` plus direct `chrome-launcher@1.2.1`, and a clean
  install reports zero npm vulnerabilities. `npm ls extract-zip @lhci/cli
  @lhci/utils --all` is empty and the lockfile contains none of their package
  entries.
- 2026-09-21: The focused policy/orchestration suite passes 30 tests and the
  complete JavaScript unit suite passes 247 tests. A no-server invocation exits
  1 with an actionable preflight message after stale reports are safely cleared
  but before Chromium is launched.
- 2026-09-21: First-round QA review found two mechanism gaps. The runner now
  verifies the declared final path and query for every route, so a same-origin
  fallback cannot masquerade as the requested page. One shared stage wrapper
  adds contextual failures for output reset, browser launch, HTML/JSON report
  writes and summary writes while retaining each original error as its cause;
  table-driven tests cover every boundary.
- 2026-09-21: Operability review found that a never-settling Lighthouse call
  could prevent both command completion and browser cleanup. Each audit now has
  a documented 120-second deadline; a fake never-settling audit proves the
  route/run timeout error and Chromium cleanup without waiting in real time.
- 2026-09-21: Fresh verification found that the old recommended preset's HTTP
  validity check and the old explicit `color-contrast` warning had not survived
  the replacement. Both are now explicit load-bearing thresholds: HTTP error
  documents block the command, while contrast regressions remain visible as
  warnings without duplicating the separate axe gate.
- 2026-09-21: Final verification found that a preflight failure preserved the
  previous successful `summary.json`. A first attempted summary-only deletion
  was rejected at review because an existing `.lighthouseci` directory symlink
  could redirect that child deletion outside the repository. The final command
  instead removes and recreates the whole fixed output-root entry before
  preflight. A checked-in filesystem test invokes the production reset helper
  against a directory symlink and proves the external sentinel survives, the
  symlink is replaced by a real local directory, and stale local results are
  gone.
- 2026-09-21: A real run against an isolated seeded CouchPotato instance
  completed all 12 audits in 77.92 seconds, wrote 12 HTML reports, 12 JSON
  reports and one final summary, and recorded zero error-level findings. Across
  the three runs, performance ranges were home 0.60-0.66, available 0.65-0.66,
  add 0.69-0.70 and settings 0.57-0.60; accessibility was 0.98, 0.98, 1.00 and
  0.99 respectively, best-practices was 1.00 throughout and SEO was 0.66
  throughout. The existing performance/SEO/FCP/LCP gaps remain visible warnings
  rather than being relaxed during the security migration.

## Spec gaps found at review

- **Resolved — per-audit deadline:** the initial criteria covered rejected
  audit calls but not calls that never settle. `AC-OPS-1` now bounds that
  external-tool boundary and requires cleanup evidence.
- **Resolved — implicit preset invariant:** removing the broad recommended
  preset also removed its HTTP-status protection. The policy now states that
  narrow invariant explicitly, and its regression test supplies a 404 result
  whose other audit scores pass.
- **Resolved — stale success and symlink confinement:** the initial ordering
  preserved old success when the server was unavailable; a summary-only fix
  then introduced child-path symlink traversal. `AC-QA-8` now requires the
  fixed output-root entry itself to be removed before preflight, which both
  invalidates stale evidence and avoids following a directory symlink.
