# CI-003: make the accessibility gate fast, and make the gate see template JS

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** agreed (49 acceptance criteria, `/plan-cycle` 2026-08-08)
**Lenses run:** `lens-security`, `lens-qa`, `lens-simplicity`, `lens-operability`,
`lens-accessibility` · **Skipped:** `lens-product`, `lens-design`,
`lens-architecture`, `lens-data` — reasons at the head of the criteria section.

Carries tasks **T9** and **T12** of `specs/REMEDIATION-2026-08.md`. Both are
changes to the gate itself: no product code, no template output, no auth path.

**Corrected at planning:** the first draft justified the bundle by saying the two
parts land in the same files. They do not — Part A touches
`.github/workflows/ci.yml`, Part B touches `scripts/check_test_traps.py` and its
test, and they share nothing. The real reason is proportionality: two small,
low-risk changes to the same gate, taken through one review cycle instead of two.

## Problem

### Part A — the gate is slow to give an answer (T9)

Raised by the owner, 2026-08-07: the accessibility check feels like it takes
over ten minutes, which is too slow for a gate that runs on every push.

**Measured before scoping, and the framing needed correcting twice.** There is
no container build in that job; the separate `docker` job is a steady ~1m20s and
is unrelated. The `accessibility` job checks out, sets up Node and Python,
`pip install -r requirements.txt`, `npm ci`, `npx playwright install --with-deps
chromium`, then runs `--project=accessibility`.

Per-step timings over **23** successful `accessibility` jobs
(`gh api .../actions/runs/<id>/jobs`, then `.../actions/jobs/<job_id>`):

| Step | n | min | median | max |
|---|---|---|---|---|
| job total | 23 | 99 | 115 | 697 |
| Install Playwright browsers | 23 | 21 | 27 | **610** |
| Run accessibility tests | 23 | 46 | **51** | 55 |
| Install Python dependencies | 23 | 15 | 17 | 30 |

#### The number the owner actually experiences, measured 2026-08-08

**Every earlier version of this section measured the wrong thing, including the
two that were labelled corrections.** All of them reported the *job* duration and
concluded the report of "over ten minutes" needed correcting. The job duration
was never the complaint. Wall-clock from workflow start to the `accessibility`
verdict, n=12 successful runs:

    632  637  648  649  653  656  656  664  671  678  678  682

    median = 656s = 10 min 56s     min 632s     max 682s

**The owner's "more than 10 mins" was accurate to within seconds.** A second
independent measurement during this planning cycle returned median 666s over
n=13, so the figure is stable across samplers.

Median offsets from workflow start, n=10 runs, showing where it goes:

| job | starts@ | ends@ | duration |
|---|---:|---:|---:|
| ui-unit-tests | 0 | 24 | 22 |
| test (3.10–3.14) | 0 | 238 | 234 |
| ui-e2e-tests | 246 | 514 | 266 |
| **accessibility** | **516** | **654** | **138** |

**516 of the 656 seconds is spent queued behind a chain, before the job starts.**
The recorded job-total median of 115s above is from the older n=23 sample and is
superseded by 139s (n=13, range 123–155) — the direction of that drift does not
change any conclusion here, but the stale figure must not be quoted as the
baseline. Re-measure immediately before the change lands (AC-QA-61).

Two facts follow, and they set the whole shape of Part A:

1. **The single 697s outlier was entirely `npx playwright install --with-deps
   chromium`** — 610s of that one step. The test step took 51s on that same run.
   So `--fail-on-flaky-tests` retrying is ruled out as the cause. The browser
   download is the only mechanism that has ever produced an outlier here, and it
   runs uncached on every single push, in **two** jobs (`ui-e2e-tests:242` and
   `accessibility:340`).
2. **The ~51s test step is the floor**, and cutting it means cutting coverage,
   which is explicitly out of scope. So the job cannot go far below ~60s even
   with perfect caching.

**Therefore the priority order is the opposite of the one this spec originally
implied.** Caching the browser download was scoped as the headline change; on the
measurements above it is worth ~27s of a 656s wall-clock, about 4%. The
`needs: ui-e2e-tests` edge on the `accessibility` job (`ci.yml:316`) is worth
~516s, about 79%. Shipping only the cache would satisfy the letter of the
verification plan and leave the complaint entirely intact.

The edge itself has no stated reason. `git log -L 316,316:.github/workflows/ci.yml`
places it at `40539241` (2026-02-16, "ci: Update CI to run UI tests and update QA
findings") with no accompanying comment, and since T1.7 the job starts and seeds
its own server on its own runner (`ci.yml:342-350`), so there is no shared state
for the edge to sequence. It looks vestigial — but "looks vestigial" is not a
measurement, which is what AC-SIMP-6 and AC-OPS-8 are for.

So the cache is retained in scope for a different reason than it was proposed:
it is the **tail** fix. The 610s stall is the only mechanism that has ever
produced an outlier here, it runs uncached on every push in two jobs, and it is
what turns a bad day into the ten-minute experience even after the edge is gone.

`pip install -r requirements.txt` also runs with no pip cache in both jobs.

### Part B — a syntax error in template JS is invisible to the gate (T12)

Found by breaking it during PR #230: a missing `+` in a multi-line string inside
`couchpotato/ui/templates/suggestions.html`'s `<script>` block made the entire
Alpine component fail to parse, and four E2E tests went red — which is the only
reason it was caught at all.

Nothing in the gate looks at that code. Ruff sees Python. Vitest sees
`tests/unit/**/*.{test,spec}.{js,ts}` and nothing else (`vitest.config.ts:9`).
**There is no ESLint in this repo at all** — no config file, no devDependency;
an earlier draft of this spec asserted ESLint coverage that has never existed,
which is exactly the kind of confidently-wrong doc claim CLAUDE.md §7 warns
about. So inline `<script>` blocks in templates are seen by nothing whatsoever.

A page whose script breaks and which has no E2E coverage would ship dead, and the
failure mode is total: the component does not partially work.

Per the standing preference for enforced checks over remembered rules, this is a
`check-traps` rule: extract `<script>` blocks from templates and parse them.

## Not in scope

- **Reducing what the accessibility suite tests.** WCAG 2.2 AA in both themes
  and at phone width is this project's stated floor. Speeding the gate by
  lowering it is the wrong trade, and a faster gate that covers less is not the
  deliverable.
- **Diagnosing the 697s run further.** It was a slow download; T9.1 is answered
  and closed.
- **Linting template JS for style.** The deliverable is *does it parse*, not
  *does it match a style guide*. Jinja tags inside a `<script>` block are not
  valid JS, so a full ESLint pass over these blocks is a much larger change with
  a much larger false-positive surface. That larger change would have to be
  justified separately.
- **Any change to what the E2E or accessibility specs assert.**

---

## Acceptance criteria

Written by `/plan-cycle`, 2026-08-08. Lenses run: `lens-security`, `lens-qa`,
`lens-simplicity`, `lens-operability`, `lens-accessibility`. Skipped:
`lens-product` (no user-facing change; the success measure is stated in Part A),
`lens-design` (no rendered output changes), `lens-architecture` (no new module,
boundary or dependency), `lens-data` (no schema, no personal data, no
destructive operation).

### Decisions the criteria assume

Three lenses independently returned "the spec has not decided this" at High
severity. The decisions were taken at planning and bind the implementation.

1. **The parse is `node --check`, with the block fed on stdin.** Measured:
   `node --check -` exits 1 with `[stdin]:N` on a syntax error, needs no
   temporary file, and executes nothing (a body calling `writeFileSync` exits 0
   and creates no file). `actions/setup-node` is added to the `lint` job, which
   has none today. No new Python or Node dependency is added, so the pure-Python
   parser option is closed: the templates contain 17 optional-chaining and 2
   nullish operators that the last esprima-python release cannot parse.
2. **Jinja tags are replaced with a placeholder token before parsing, never
   skipped, and no template is excluded by path.** Measured: naive
   extract-and-parse fails today on
   `couchpotato/ui/templates/partials/movie_detail.html` (block line 5,
   `newProfile: '{{ movie.get('profile_id', '') }}'`); after substituting
   `{{...}}`, `{%...%}` and `{#...#}`, all 15 inline blocks parse clean.
   Skipping Jinja-bearing blocks is the cheaper rule but would permanently
   exempt the toast live regions (`base.html:210-226`) and the focus handling in
   `movie_detail.html`, so the accessibility floor overrides it.
3. **Branch protection is not changed and the job keeps the exact name
   `accessibility`.** Measured: the accessibility job starts at a median of 516s
   after workflow start and itself takes 139s, so the `needs:` edge owns the
   wall-clock complaint and the browser cache owns the tail. Merging jobs stays
   rejected.

### lens-security

- AC-SEC-1: The check parses without executing. Neither `scripts/check_test_traps.py` nor anything it invokes uses `eval`, `new Function`, `vm.runIn*`, `node -e`, `node -p`, `node --eval`, `os.system`, or `subprocess` with `shell=True`; the Node call is `node --check` with a list argv. Proved by a fixture template whose script body calls `require('child_process').execSync('touch <tmp>/pwned')`: the check reports that block as parsing fine AND `<tmp>/pwned` does not exist.
- AC-SEC-2: The check performs no network access and installs nothing at check time. No `npx <package>`, no `pip install`, no `npm install`/`npm ci` is added to the `lint` job beyond `actions/setup-node`. Proved by grep of the diff plus a run with no network route available returning an identical exit code and finding count.
- AC-SEC-3: Extracted script content is never written to a predictable filesystem path. Satisfied by feeding the block on stdin; if any temporary file is used at all it is `tempfile.NamedTemporaryFile`/`mkdtemp` (unpredictable, 0600) and is removed on both the success and failure paths. Proved by grep for a hard-coded `/tmp` path and an assertion that no temp file survives a failing run.
- AC-SEC-4: The check is read-only. After `make check-traps` and `python scripts/check_test_traps.py --require-git` on a clean tree, `git status --porcelain` is empty and every file under `couchpotato/ui/templates/` is byte-identical by hash before and after.
- AC-SEC-5: Every `path:` on a new `actions/cache` step (or `setup-*` cache option) is a package-manager directory outside the workspace, from the allowlist `~/.cache/ms-playwright`, `~/.cache/pip`, `~/.npm` and no others. `node_modules/` is NOT cached (restoring it skips `npm ci`'s integrity check against `package-lock.json`), and no run artefact or data directory is cached (`test-results/`, `playwright-report/`, `.e2e-data*`, `.config/`, any SQLite data directory), because a cache saved on `master` is restorable by every later run including fork PR runs. Proved by reading the built workflow and asserting the cached-path set against that allowlist.
- AC-SEC-6: The browser cache cannot supply an unverified binary. The Playwright cache key includes `hashFiles('package-lock.json')`, and the `npx playwright install ... chromium` step is NOT gated on `cache-hit`, so a partial, stale or tampered cache is repaired by the install step rather than trusted; if `restore-keys` prefix matching is used, a comment at the step says that the unconditional install is what makes an older partial match safe. Proved by reading the built workflow plus one CI run with a deliberately mismatched key that still passes. (merges AC-QA-63)
- AC-SEC-7: No new trust and no new privilege. The trigger stays `pull_request` (never `pull_request_target`), workflow-level `permissions: contents: read` is unchanged, no job's `permissions:` block gains a scope relative to `master`, and every `uses:` is an action already present on `master` at the same or a newer pinned version, or else pinned to a full 40-character commit SHA. Proved by reading the diff.
- AC-SEC-8: Artefact exposure is not broadened. Every `actions/upload-artifact` step whose `path:` includes `test-results/` still carries `if: failure()` (never `always()`), and no job uploads a data directory, a SQLite database, a `.config` directory or a seeded E2E data dir. The (path, condition) set is a subset of master's: `playwright-report/` + `test-results/` on `if: failure()` (ui-e2e-tests), `playwright-report/` on `if: always()` and `test-results/` on `if: failure()` (accessibility).
- AC-SEC-9: No required status check is removed or weakened. `git diff master -- .github/workflows/` shows every job name in the required set (`lint, test-summary, ui-unit-tests, ui-e2e-tests, claude-review, Analyze (python), Analyze (javascript), dependency-review, docker, accessibility, conformance, secrets`) still exists and still publishes a result, and the change contains no branch-protection API call.

### lens-qa

- AC-QA-60: Median wall-clock from workflow `run_started_at` to the `accessibility` job's `completed_at` is at most 300s across at least 3 successful post-change runs on the same branch, measured by the same `gh api` method as the baseline. Baseline measured 2026-08-08, n=13 successful runs: median 666s, min 634s, max 684s. A single run does not satisfy this, and the after-median must beat the before-median by more than the 50s before-range.
- AC-QA-61: Median `accessibility` job duration (its own `started_at` to `completed_at`) across those same runs is at most 145s, i.e. no regression against the measured baseline median of 139s (n=13, 123-155). The spec's recorded 115s figure is from an earlier sample and is superseded; the baseline must be re-measured immediately before the change lands and recorded with its n.
- AC-QA-62: At least one of the measured post-change runs is a demonstrated Playwright browser-cache HIT (the log shows the cache restored from the expected key, not a restore-key fallback and not a miss) AND that run is green, with its run ID recorded. A caching change proven only on cold-cache runs is unproven. (merges AC-OPS-1)
- AC-QA-64: The first post-change run, whose cache key does not yet exist, is green and installs the browser. A cache-restore miss or failure must not fail the job or leave no browser installed.
- AC-QA-65: A test parses `.github/workflows/ci.yml` (PyYAML is already a dependency of `scripts/check_test_traps.py`) and fails unless a job exists whose reported check-run name is exactly `accessibility`. Proven in both directions: renaming the job in a scratch copy makes the test red, restoring it makes it green.
- AC-QA-69: `make check-traps` exits non-zero and names `couchpotato/ui/templates/suggestions.html` at the template's own line number when the exact #230 defect is reintroduced (delete the trailing `+` from `console.warn('[suggestions] focus did not reach ' + ref +` at suggestions.html:226). Run in both directions: break it, hash the file, watch the gate go red for that reason, restore it, confirm the file is byte-identical by SHA-256, confirm the gate is green. Hashes pasted. (merges AC-A11Y-8)
- AC-QA-70: The rule reports zero findings across every currently tracked template's inline `<script>` blocks, INCLUDING `couchpotato/ui/templates/partials/movie_detail.html`. An exclusion entry for that file does not satisfy this criterion.
- AC-QA-71: Extraction is anchored positively, not by absence. A test asserts the rule discovers at least 15 non-empty inline `<script>` bodies across the template roots, discovery is by directory walk rather than a hardcoded file list (a NEW template with a broken block is flagged with no edit to the checker), and the rule's output states how many blocks were parsed and how many were skipped, with any skipped block listed by path and line. (merges AC-OPS-10)
- AC-QA-72: Non-classic `<script>` blocks are handled explicitly, each pinned by its own fixture: (a) `<script src=...>` with an empty body produces no finding; (b) `type="module"` containing a top-level `import`/`export` produces no finding (real case: `base.html:47`) while the same content in a plain `<script>` is still parsed as a classic script; (c) a non-JS type (`application/json`, `text/template`) is not parsed as JS. Node 22+ auto-detects module syntax, so the fixture must pin the intended handling rather than the interpreter's default.
- AC-QA-74: Behaviour when Node is unavailable is explicit and non-silent, following the PyYAML precedent at `scripts/check_test_traps.py:693-702`, and both branches have a test: under `scripts/verify.sh`, `make check-traps` and the CI `lint` job a missing `node` is a hard non-zero failure naming what is missing and how to install it, and it never prints "test-trap check passed"; the pytest cases for this rule skip with a visible reason when `node` is absent, so the Alpine run in `scripts/test-local.sh` (no node, no git) does not go red on an environment that never had it. (merges AC-OPS-9)
- AC-QA-75: A parser invocation that fails for a reason OTHER than a syntax error (binary absent, killed, non-zero for an unrelated reason, unparseable output) is reported as "the check could not run" and never as "this template has a syntax error". Pinned by a test pointing the rule at a failing or absent parser binary.
- AC-QA-76: Findings are per-block and at the template's own line numbers. A fixture with two broken blocks yields two findings, not one; a fixture whose first block is clean and second is broken still produces the finding, so a per-file short-circuit cannot pass; and each finding prints as `couchpotato/ui/templates/<file>:<line>: <parser message>` where `<line>` is the line in the .html file, proved by breaking a block that starts well down a file (`wanted.html` script opens at 191, `partials/movie_detail.html` at 363) and confirming the printed line equals the actual line. (merges AC-OPS-11)
- AC-QA-78: The rule's root set covers every tracked template the running app renders, and any exclusion is recorded at the root list with its reason, using the convention at `scripts/check_test_traps.py:772-779`. Specifically `couchpotato/templates/login.html` (two non-empty inline blocks, both parsing clean today) is either in scope or excluded with a written reason; `docs/design-system/*.dc.html` are documentation and need no argument.
- AC-QA-79: `make check-traps` completes in under 3s on a developer machine (baseline measured 2026-08-08: 0.88s for 200 files; 15 separate `node --check` invocations measured at 0.75s), and the CI `lint` job stays under 30s (baseline: 8s median, n=5). Parser invocations are bounded at one per non-empty script block, not one per template line or per file re-parse.

### lens-simplicity

- AC-SIMP-1: The change adds no dependency. `requirements.txt`, `requirements-dev.txt`, `package.json` and `package-lock.json` are byte-identical to master in the merged diff.
- AC-SIMP-2: The change adds no configuration surface: no new environment variable, no new command-line flag on `scripts/check_test_traps.py`, no new Makefile target, and no on/off switch for the new rule. `make check-traps` and `make verify` keep their current names and invocation.
- AC-SIMP-3: No new CI job and no new workflow file. `.github/workflows/` gains no file, and the set of job keys in `ci.yml` is unchanged: lint, conformance, secrets, security-lint, test, ui-unit-tests, ui-e2e-tests, accessibility, test-summary, docker. Branch protection on `master` is not modified (its twelve required contexts, verified 2026-08-08, still all publish).
- AC-SIMP-4: A job named exactly `accessibility` still exists in `ci.yml` and still runs `npx playwright test --project=accessibility`. The accessibility and E2E jobs are not merged, no step of `ui-e2e-tests` runs the accessibility project, `playwright.config.ts` retains a distinct `accessibility` project matching `*.a11y.spec.ts`, no a11y spec is moved into the `chromium` project, and `tests/unit/e2e_projects.test.ts` still passes unchanged. (merges AC-QA-68)
- AC-SIMP-5: `git diff --numstat master -- .github/workflows/ci.yml` shows at most 30 net added lines. The only third-party action newly introduced to the repo, if any, is `actions/cache`; adding `actions/setup-node` to the `lint` job is permitted because it is already used at `ci.yml:202`, `:223` and `:321`. No composite action, no reusable workflow, no matrix.
- AC-SIMP-6: The `needs: ui-e2e-tests` edge on the `accessibility` job (`ci.yml:316`) is either deleted, or retained with a comment on that line stating the reason it must stay. Measured baseline for comparison: on run 31237901328 the accessibility job started at +8m24s and finished at +10m34s while itself taking 2m10s.
- AC-SIMP-7: The template-script rule contains no per-file allowlist: no path under `couchpotato/ui/templates/` appears as a literal string in the rule's code, data or configuration.
- AC-SIMP-8: The rule lands inside `scripts/check_test_traps.py`, adding no new file under `scripts/` and no new top-level tool, and adds at most 120 net lines to that file. Existing `check_*` functions are unmodified apart from one added dispatch branch in `check_file`.
- AC-SIMP-9: No file under `couchpotato/` is modified by the merged diff: `git diff --stat master -- couchpotato/` is empty, and the deliberately broken template used to prove the guard is reverted with its SHA-256 matching master.
- AC-SIMP-10: The change adds no timing-measurement tooling: no script, workflow step or artefact upload whose purpose is collecting CI durations. The before/after evidence is `gh api` output on runs that would have happened anyway, recorded as prose in this spec or the PR body. `CLAUDE.md`, `AGENTS.md` and `docs/development-process.md` are either unchanged or changed only within an existing commands table.

### lens-operability

- AC-OPS-2: The before/after evidence is re-checkable by a third party: for at least three runs on each side it records the GitHub run ID, the `accessibility` job duration in seconds, and the wall-clock from workflow start to `accessibility` completion, each re-fetchable with `gh api repos/bassings/CouchPotatoServer/actions/runs/<id>/jobs`.
- AC-OPS-3: The gate cannot report green without running. The step invoking `npx playwright test --project=accessibility` carries no `if:` condition, and no step whose omission would leave the suite unrun is gated on a cache-hit output. Demonstrated with the cache absent and with the cache primed from a different version: the job either installs the correct browser and runs the suite, or fails; it never publishes a successful `accessibility` context having executed zero accessibility tests.
- AC-OPS-5: A status context named exactly `accessibility` is still published by a run on the merge commit, verified with `gh api repos/bassings/CouchPotatoServer/commits/<sha>/check-runs` and pasted into this spec.
- AC-OPS-6: Rollback is stated and real: reverting this change's commits restores a gate that runs green with no manual GitHub settings change, because branch protection is not touched (AC-SIMP-3). If that decision is reversed during implementation, the before and after required-context lists, the `gh api` command to restore the previous list, and who can run it are recorded here, together with the statement that the workflow revert alone would leave master blocked.
- AC-OPS-7: The Playwright browser cache key is a function of runner OS plus the resolved Playwright version, and contains no per-commit, per-run or per-branch component, so the number of distinct entries is bounded by dependency changes rather than by pushes. Checked against the 10 GB per-repo Actions cache limit with LRU eviction: an unbounded key would silently evict the existing npm and pip caches and make every other job slower with no error anywhere.
- AC-OPS-8: The change leaves its runbook entry at the line. The cache step carries a comment naming the symptom of it silently ceasing to work (the `accessibility` job back at several minutes with `Install Playwright browsers` dominating) and the check to run (the cache-hit line in the job log, or `gh cache list`). The `needs:` edge on `accessibility` is either removed with a comment recording the evidence that it carried no data dependency (the job seeds its own server, `ci.yml:342-350`), or kept with its reason stated at the line.
- AC-OPS-12: Local and CI run the identical rule with the identical invocation. `couchpotato/ui/templates/**` is reachable from `DEFAULT_ROOTS`, so `make check-traps`, `scripts/verify.sh:103` and the CI `lint` job (`ci.yml:52-53`) all execute it, and everything the rule needs is installed in both places. Verified by running the rule with the CI job's exact dependency set.
- AC-OPS-13: The rule states its own blind spots so it is not over-trusted. The module docstring and the finding message record that JS in Alpine and htmx attributes (`x-data`, `@click`, `hx-on:`) and JS in static files are not covered, following the existing "WHAT THIS RULE STILL DOES NOT SEE" convention at `scripts/check_test_traps.py:985-1019`.

### lens-accessibility

- AC-A11Y-1: The set of accessibility tests the gate executes is unchanged or larger. `npx playwright test --project=accessibility --list` on the merge base and on the branch produce the same set of test titles (measured floor: 40 tests across 3 spec files), the two listings are captured and diffed rather than reasoned about, no narrowing mechanism (`--grep`, `--grep-invert`, `--shard`, `test.skip`, a changed `testMatch`) reduces it, and all three a11y specs appear in the branch listing. (merges AC-QA-66)
- AC-A11Y-2: An accessibility failure still blocks merge. A deliberately introduced WCAG failure (for example removing the accessible name from an icon-only control the suite scans) turns the required `accessibility` check red on a real branch build; reverting it turns it green. Both directions run, with the run IDs recorded.
- AC-A11Y-3: Both themes and phone width remain enforced, in CI and in the local gate. The workflow still executes `--project=accessibility` and `--project=mobile-chrome`, `scripts/verify.sh` still runs both, and neither becomes conditional on a path filter, a label or a manual dispatch. Evidence: the branch run log shows the dark-theme test titles and the small-screen spec as executed, not skipped.
- AC-A11Y-4: `--fail-on-flaky-tests` is present on every invocation that runs a11y or mobile specs, in both `.github/workflows/ci.yml` (currently `:354` for accessibility and `:260`, `:262`, `:273` for ui-e2e-tests) and `scripts/verify.sh`, and `playwright.config.ts` retry behaviour for those projects is not loosened. (merges AC-OPS-4)
- AC-A11Y-5: Caching preserves the conditions the accessibility measurements are taken in. The cache key includes the `@playwright/test` version resolved from `package-lock.json`, a cache hit does not skip installation of the OS-level dependencies and fonts the browser needs to render text, and the accessibility project passes three consecutive post-change runs with no new contrast, focus-indicator or target-size failures, failure counts recorded. Contrast and size assertions are measurements of a rendered page: a different browser build or a missing font changes the answer without changing a single test.
- AC-A11Y-6: The rule scans every template containing an inline `<script>` block, at every directory depth. `couchpotato/ui/templates` is added to `check_test_traps.DEFAULT_ROOTS` (`scripts/check_test_traps.py:147-163`) and is covered by the existing `test_default_roots_all_exist_and_are_covered` pattern (`tests/unit/test_check_test_traps.py:1653`) with a NESTED representative asserted in scope, so downgrading `rglob` to `glob` or dropping the root fails a test rather than silently scanning nothing. A unit test enumerates `couchpotato/ui/templates/**/*.html` at runtime and fails if any file containing a `<script>` without `src` is not scanned. Measured floor at 2026-08-08, 11 files: base.html, suggestions.html, wanted.html, logs.html, wizard.html, partials/movie_detail.html, partials/movie_info_modal.html, partials/search_results.html, partials/charts.html, partials/suggestions.html, partials/settings/scripts.html. (merges AC-QA-77)
- AC-A11Y-7: Script blocks that embed Jinja tags are parsed, not skipped, via placeholder substitution for `{{ ... }}`, `{% ... %}` and `{# ... #}`. A test introduces a syntax error into a Jinja-bearing block (`base.html:189-309`, which holds `politeAnnouncement`/`assertiveAnnouncement` at `:210-226`, or `partials/movie_detail.html:363-648`) and asserts check-traps reports that file and line; a second test wraps `{% if %}...{% endif %}` around valid JS statements and asserts no finding, so the substitution cannot become a blanket silencer. Both directions run. (merges AC-QA-73)
- AC-A11Y-9: If the accessibility project is ever folded into a job that also runs other tests, its step runs regardless of whether an earlier step in that job failed (an `if: always()` equivalent), so an unrelated E2E failure cannot hide a WCAG regression behind an already-red job. Vacuously satisfied while the accessibility project keeps its own job, which AC-SIMP-4 requires.

### Vetoed at planning

`lens-simplicity` holds a veto on any requirement not traceable to the stated
goal, and cannot override irrecoverable data loss, security, or the
accessibility floor. Vetoes applied:

- **AC-QA-67, second half** (a unit test asserting that a comment exists on or
  above the `needs:` line). Dropped: a test that greps for the presence of a
  prose comment passes on the comment existing, not on it being true, and it
  needs maintaining forever. The requirement itself survives as AC-SIMP-6 (diff
  check) and AC-OPS-8 (the comment and its content). Not security, data loss or
  accessibility floor.
- **AC-OPS-10, second half** ("executed again with the templates directory
  renamed"). Dropped: the positive count anchor in AC-QA-71 already goes red if
  extraction stops matching, so renaming a directory on a read-only checker adds
  a manual step and no information. The reporting half of AC-OPS-10 (parsed and
  skipped counts printed) survives inside AC-QA-71.
- **AC-OPS-6, the `git revert` dry run on a scratch branch.** Dropped: with
  branch protection unchanged (AC-SEC-9, AC-SIMP-3, AC-QA-65) the change is
  workflow YAML plus a checker rule, both plainly revertible, and no out-of-band
  state is touched. The written rollback statement survives as AC-OPS-6.
- **The "new pinned dependency" allowance in AC-SEC-2.** Narrowed, not
  overridden: AC-SIMP-1 forbids any new dependency, which is strictly stronger
  than the security criterion it constrains, so the security floor is preserved.
- **`lens-operability`'s and `lens-security`'s "or a pure-Python JS parser"
  option.** Rejected on evidence rather than by veto: the templates contain 17
  optional-chaining and 2 nullish operators, and esprima-python's last release
  predates ES2020, so it would be red on arrival against correct code.

Vetoes NOT applied, and why:

- **`lens-simplicity`'s proposal to skip any block containing `{{` or `{%`.**
  Overridden by the accessibility floor (precedence item 3): the four
  Jinja-bearing blocks include the toast live regions and the focus handling
  after restore-to-wanted, which is the a11y-critical inline JS this rule most
  needs to cover. Measured cost of the alternative is a two-line regex
  substitution, well inside the AC-SIMP-8 budget.
- **`lens-simplicity`'s proposal to implement the rule as a vitest test rather
  than a check-traps rule.** Overridden by the spec's own statement that this is
  a `check-traps` rule and by AC-OPS-12 (local and CI run the identical rule):
  vitest would leave `make check-traps` and `scripts/verify.sh` blind to it.
  Simplicity's underlying concern (no new dependency, no new job) is satisfied
  in full by the `node --check` decision.

---

## Spec gaps and AC conflicts found at implementation

Recorded per the harness contract: a finding with no AC behind it is a spec bug,
and so is an AC that cannot be satisfied alongside another.

- **AC-SIMP-5 (≤30 net added lines in `ci.yml`) conflicts with AC-OPS-8 and
  AC-SIMP-6.** Measured at implementation: net **+36**. The functional change is
  14 lines (one `setup-node` step, two `actions/cache` steps, one deleted
  `needs:`); the other 22 are comments that AC-OPS-8 explicitly requires (the
  cache step must carry its symptom and its check) and that AC-SIMP-6 requires
  for the removed `needs:` edge (the evidence it carried no data dependency).

  Not resolved by trimming, because the surrounding file's idiom is heavily
  commented — the `secrets` job carries a ~30-line block explaining a single
  `docker run` — and CLAUDE.md's maintainability rule says to match the
  surrounding style. Cutting the runbook notes to hit a line count would satisfy
  the letter of AC-SIMP-5 by deleting the thing AC-OPS-8 asks for.

  **Resolution taken:** the cap is breached by 6 lines, deliberately and on the
  record, with the duplicated cache comment reduced to a cross-reference on the
  second occurrence. Flagged for the review cycle to arbitrate rather than
  decided silently. The lesson for the next planning cycle is that a net-line
  budget on a file whose house style is long explanatory comments should count
  **code** lines, not total lines.

- **AC-SEC-7 caught a real defect in the first implementation of Part A.** I
  wrote `actions/cache@v4` while the repo already pins `actions/cache@v6` at
  `ci.yml:168` — older, not "the same or newer", so the criterion as written was
  violated. Fixed to `@v6`. Worth noting the criterion earned its place: nothing
  else in the gate would have caught a silently downgraded action.

---

## Constraints that already have teeth

Recorded here because they are hard failure modes discovered during planning,
not opinions, and any AC set must respect them:

1. **`accessibility` is a REQUIRED status check on `master`.** Verified:
   `lint, test-summary, ui-unit-tests, ui-e2e-tests, claude-review,
   Analyze (python), Analyze (javascript), dependency-review, docker,
   accessibility, conformance, secrets`. Folding the accessibility project into
   `ui-e2e-tests` — the largest available win — deletes the job that reports that
   context, and branch protection then waits forever for a check nothing
   publishes, blocking this PR and every one after it. Either keep a job named
   `accessibility` that reports the result, or change branch protection in the
   same change. Not one without the other.
2. **Merging the two jobs also merges their failures.** A gate's job is to name
   what broke; `ui-e2e-tests` red and `accessibility` red currently mean
   different things to whoever reads the PR.
3. **A single before/after comparison cannot distinguish an improvement from
   runner variance.** The wall-clock baseline is n=12 spanning 632–682s; any
   claimed win must beat that 50s spread by more than the spread, over at least
   three runs (AC-QA-60).
4. **A `check-traps` rule is itself a guard**, so project rule 10 applies to it:
   it must be proven to fail on the real defect (the actual missing `+` from
   #230, reintroduced and then reverted, with the file hashed before and after)
   and proven not to fire on every currently-passing template.

   **This constraint was oversold in the first draft and the correction matters
   for how the guard is proven.** A dropped `+` is a syntax error only where
   automatic semicolon insertion cannot terminate the expression. Verified with
   `node --check`: `console.warn('a'\n'b');` is red, but the same typo between
   two statement-position string literals (`var x = 'a'\n'b';`) parses clean. So
   this rule catches the #230 defect and a large class like it — it does not
   catch every dropped operator, and the PR must not claim it does.

## Verification plan

- **Part A:** a measured before/after of BOTH numbers — job duration and
  wall-clock from workflow start to `accessibility` completion — over at least
  three runs each.
- **Part B:** `make check-traps` fails on a deliberately broken template script
  block and passes on `master`'s templates unchanged; both directions run, not
  reasoned about.
