# PERF-001: make the page-speed budgets an automated check rather than a manual command

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** draft
**Lenses run:** not yet run
**Owner decision that opened this:** 2026-09-04, choosing "wire it into CI" over
recording a hold or dropping Lighthouse, when the recurring `extract-zip`
advisory forced the question of whether the tool earns its place.

## Problem

The project's engineering standards make Core Web Vitals a must-do for any user
interface and ask for lab budgets enforced as tests in CI. This repository has
the tooling for that and runs none of it.

`lighthouserc.js` is complete and carefully written. `package.json` exposes it as
`npm run test:lighthouse`. Nothing invokes it: `git grep -nI "lhci\|lighthouse"
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
- **Removing `@lhci/cli`, or closing the `extract-zip` advisory by upgrade.**
  Neither is available: there is no patched release. This spec makes the
  vulnerable code path unreachable in CI rather than absent from the tree.
- **Re-auditing the upload safety work from #291.** It is correct. This spec must
  not weaken it, and that is an acceptance criterion, but it is not reopened.
- **A production performance monitor.** Nothing here reaches the running server.

## Design intent, for the lenses to challenge

Three choices that want scrutiny rather than assumption:

**Reuse Playwright's Chromium instead of letting Lighthouse fetch its own.** The
`accessibility` job already installs Chromium via `npx playwright install`.
Pointing Lighthouse at that binary through `CHROME_PATH` means
`@puppeteer/browsers`' download-and-unpack path, which is the only caller of
`extract-zip`, is never invoked in CI. That turns the held advisory from
"accepted risk we re-argue monthly" into "not reachable by anything automated",
which is a better answer than either of the options it was weighed against.

**A guard whose assertions are all warnings is a guard that cannot fail.** The
existing `lighthouserc.js` sets every performance assertion to `warn`. Wiring
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
4. `lighthouserc.js` asserts `categories:accessibility` at `error`, which the
   axe suite already covers more precisely. Does that assertion earn its place,
   or is it duplicated scope for `lens-simplicity` to cut?

## Acceptance criteria

*To be written by the planning cycle. Not drafted here on purpose: the numbers
in particular must come from a measurement, and pre-filling them would anchor
the lenses to a guess.*

## Spec gaps found at review

*(empty)*
