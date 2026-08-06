# Known Technical Debt & Lessons Learned

> Moved out of `CLAUDE.md` on 2026-07-13 during a restructure. Refresh entries
> against `origin/master` before relying on them — these are point-in-time
> snapshots, and several older claims have already gone stale once.

## Known technical debt

> Refreshed 2026-07-07 — most of the old list was stale (verified against
> `origin/master`). Kept as an accurate current-state snapshot.

- **Bare `except:` clauses: 0 in `couchpotato/`** (the old "367" is stale —
  cleared). The vendored `libs/CodernityDB/` still has ~13 (it's imported by
  `codernity_adapter.py` for the one-time CodernityDB→SQLite migration, so it's
  live, not dead code — left as-is per the "don't remove CodernityDB" upgrade
  path). Broad `except Exception:` handlers still remain in places and swallow
  errors; keep ratcheting the ruff `S`/`BLE` codes into the blocking `lint`.
- **Read-modify-write DB races: partially fixed.** `_rev` compare-and-swap +
  `update_with_retry` added to `SQLiteAdapter.update()` (#167), and the four
  clear RMW hotspots (`markWatched`, `markUnwatched`, `markDone`,
  `Release.updateStatus`) are converted. ~30 other `get`→mutate→`update` callers
  now degrade to a *logged, swallowed* conflict rather than a silent lost
  update — per-caller conversion to `update_with_retry` is the remaining
  follow-up.
- **CSRF protection absent.** (CORS middleware now exists —
  `couchpotato/__init__.py`; the old "no CORS" note is stale.)
- Passwords bcrypt-hashed (was plaintext before PR #44).
- **API auth via URL key.** Rate limiting now exists
  (`couchpotato/core/rate_limit.py`; the old "no rate limiting" note is stale);
  the api_key is still the URL-embedded bearer.
- **`Plugin._locks` is per-instance now** (`couchpotato/core/plugins/base.py:47`)
  — the shared-class-var thread-safety bug is fixed. The remaining class-level
  `_cache_locks` is correctly guarded by its own `_cache_locks_lock`.
- **Renamer post-processing gap** (pre-existing migration regression): the
  `renamer.before`/`renamer.after` event chain is dead (subtitles/trailers/
  notifications/metadata don't auto-fire); being addressed by the
  Downloaded/review workflow — see `specs/DOWNLOADED-REVIEW-WORKFLOW.md` +
  `specs/RENAMER-EVENT-CHAIN.md`.
- **RESOLVED (T1.7).** `wanted.html`'s arrow-key handler used to move focus
  by TWO cards per keypress, not one: `x-data="movieList()"
  x-init="init()"` called `init()` twice (once via Alpine's own
  auto-invoke-a-data-object's-`init()` convention, once via the explicit
  `x-init`), double-registering the keydown listener. Invisible before
  T1.7a/T1.9, when the Wanted grid seeded 1-2 movies (a double-step and a
  single-step clamp to the same result there); seeding 3 exposed it. Same
  bug class already fixed once in `base.html`'s `<body>` and in
  `partials/movie_detail.html`'s `restoreToWanted()` component (see that
  file's comment at `:199`) -- this makes `wanted.html` the third fix, not
  a new pattern. Confirmed the fix is load-bearing: reverted, watched
  `tests/e2e/interactions.e2e.spec.ts`'s "arrow keys navigate movie cards"
  fail 3/3, restored, hash-verified.

  **`x-init="init()"` is still redundant (same live bug, not yet visibly
  broken) in `wizard.html`, `logs.html`, `settings.html`,
  `partials/movie_detail.html`'s `profileEditor()`, and
  `partials/movie_releases.html`.** Each double-runs its own `init()`
  exactly like `wanted.html` did.

  What that costs, read from the code rather than assumed. `settingsPanel`
  (`partials/settings/scripts.html:231`) issues `GET /settings/` and
  `GET /updater.info/` twice per page load, and registers
  `$watch('activeTab')` and `$watch('showAdvanced')` **twice**, so every tab
  change recomputes twice. `logsPanel`'s `init()` also calls
  `startAutoRefresh()` -- which does NOT leak an interval, because it calls
  `stopAutoRefresh()` first (`:69-72`); the doubled poll a first reading
  suggests is not there.

  So the accurate severity is doubled work on page load and on every watched
  state change, on hardware that is often a low-powered home server -- not a
  second live bug. That is worse than the original entry implied ("not yet
  proven to cause a user-visible failure") and better than an interval leak.
  The doubled `$watch` is the same mechanism as the arrow-key bug, so the
  claim that this shape is only theoretical does not hold.

  **Still deferred, deliberately.** Not because it is unimportant, but
  because PR 1 already failed AC-SIMP-1/4/5/6 (see the outcome box in
  `specs/REMEDIATION-2026-08.md`) and sweeping five more templates in the PR
  that just recorded "amending the scope criterion whenever it would fail is
  what broke it" would be the same mistake with a different file list. It is
  five one-attribute deletions plus the E2E updates hard rule 5 requires;
  it wants its own PR and its own review, not a tenth round on this one.
- **Events fired with no handler.** `fireEvent()` returns `[]` for an
  unhandled name, indistinguishable from "handled, found nothing", so a
  mis-wired event never fails — the feature behind it silently does nothing.
  `tests/unit/test_event_wiring.py` now fails CI when a new one appears, and
  `fireEvent()` warns once per name at runtime. Two known gaps stay
  allowlisted in `couchpotato/core/event.OPTIONAL_EVENTS`:
  - `movie.info.release_date` — no provider handler, so the `{theater, dvd}`
    mapping the ETA gate reads was always empty and the gate was a no-op:
    every movie downloaded regardless of release date (BUG-017). Worked
    around in #201 by deriving a theatrical date from the `released` string
    the TMDB provider already stores (`releaseDatesFromInfo()` in
    `media/movie/_base/main.py`, used as `updateReleaseDate()`'s fallback).
    The real fix is a provider handler using TMDB's per-country
    `release_dates` endpoint, which would give a genuine **digital/physical**
    date as well; until then `dvd` is always unknown, so the dvd-based unlock
    paths in `couldBeReleased()` are dead code and the dashboard's "late"
    view falls back to the theatrical date.
  - `cp.source_url` — **`SourceUpdater.doUpdate()` calls `.get()` on what
    this returns, so every update attempt on a source install dies with
    `AttributeError: 'list' object has no attribute 'get'`** (an unhandled
    `fireEvent` returns `[]` before it reads `single`, so it is an empty list,
    not `None`).
    Reachable: `release-to-prod.yml` attaches `.tar.gz`/`.zip` source archives
    to each stable release, and running one outside Docker leaves no `.git`,
    which is exactly how `SourceUpdater` is selected. Either implement the
    handler or delete that update path.
- **The legacy `/old` UI's `movie.js` reads `info.release_date`** for display
  and has therefore always shown nothing. Harmless — that stack is
  unreachable (`/old/*` redirects) — but it goes away with UI-CLEANUP.
- **Review + implement Dependabot dependency PRs** — keep the dependency
  update PRs Dependabot opens triaged and merged (bump, verify CI, `--admin`
  merge if they predate a CI change — see Lessons Learned #7); don't let them
  pile up.
- **E2E suite: RESOLVED 2026-07-31** (kept as a record because the failure shapes
  recur). Three separate problems, all root-caused rather than retried away:
  - *Two specs failed locally and passed in CI.* Both waited on
    `page.waitForLoadState('networkidle')`, which never settles on the
    suggestions page: `/partial/charts` fetches external chart providers and was
    measured at ~85s. They passed in CI only because CI cannot reach those
    providers, so the request failed fast — green for the wrong reason. Fixed by
    stubbing the charts route and waiting on the `#main-content` landmark.
  - *The suite was pinned to `workers: 1`*, costing ~3 min a run, because
    categories/profiles mutate global singleton config under fixed fixture names.
    Fixed with `test.describe.configure({ mode: 'serial' })` on those two files
    (other files still run in parallel) plus stubbing the TMDB search lookup that
    `search.spec` depended on. **4.1 min -> 1.0 min**, verified green over four
    consecutive parallel runs.
  - *`release_controls.spec.ts:111` was flaky* (2 of 3 parallel runs). Its wait
    was `expect(#movie-releases).toBeVisible()` on the htmx swap *target*, which
    is already visible — so it passed instantly and the assertion then read
    stale, pre-filter rows. Replaced with a retrying `expect(...).toPass()`.
  Shared helpers now live in `tests/e2e/helpers.ts` rather than being copied per
  spec: the duplication is precisely why the good pattern (mock the slow route,
  wait on an element) sat in `accessibility.a11y.spec.ts` while the broken one
  sat in `interactions.e2e.spec.ts`.

  Remaining, not currently a problem: the suite still shares one server, so a
  spec that mutates global config must declare serial mode. A server per worker
  would remove that constraint entirely.
- **Shipped public application keys are DELIBERATE — do not "clean them up".**
  CouchPotato is self-hosted software expected to work out of the box, so it
  ships public app keys for the third-party read APIs it uses:
  `themoviedb.py` carries a base64 pool (`ak`) and falls back to it whenever the
  user has not configured their own, and `tmdb_charts.py` logs "using built-in"
  when it does. `fanarttv.py` follows the same pattern for extra artwork.

  This is recorded as debt because the mistake has already been made once: on
  2026-07-31 the fanart.tv key was removed and replaced with a required
  per-install setting. That silently disabled extra artwork (logos, banners,
  discs) for every existing install, and — because the settings group was
  registered on the hidden `providers` tab — the replacement key could not even
  be entered from the UI. It bought nothing: the key is public in every copy of
  upstream and grants access to fanart.tv's public art API, nothing of this
  project's. Reverted the same day; `tests/unit/test_providers.py` now pins both
  the shipped fallback and the user override.

  If you want per-install keys, ADD a setting that takes precedence and KEEP the
  shipped fallback — which is what `fanarttv.py` now does.

  Note for anyone auditing: `make check-secrets` reports clean, but that reflects
  the base64 encoding (gitleaks' hex rules do not match it), not the absence of a
  shipped key. Nothing is hidden — see the comments in `fanarttv.py` and
  `.gitleaksignore`.
- **The settings UI hides the `providers` tab, so metadata-provider settings are
  unreachable.** `couchpotato/ui/templates/partials/settings/scripts.html` has
  `hiddenTabs: new Set(['providers', 'automation'])`, and nothing remaps
  `providers`, so any group declaring `'tab': 'providers'` never enters
  `tabOrder`. That affects **TheMovieDB's `api_key`** (`themoviedb.py`) — masked
  by its shipped fallback, which is why it went unnoticed. fanart.tv sidesteps it
  by registering under `general`, and
  `tests/unit/test_providers.py::TestFanartTVSettingIsReachable` fails if that
  regresses. The real fix is to surface the Providers tab so metadata providers
  are configurable like everything else; that is a UI change and wants its own
  commit.

- **Accepted: the E2E search specs do not cover the `/partial/search` handler.**
  Decided 2026-07-31 (Scott). The specs stub the provider response, so their
  content assertions echo test-supplied markup — blanking
  `partials/search_results.html` leaves them green. They still exercise the
  client wiring (typing → debounce → `hx-get` → swap; a typo'd `hx-target` fails
  four of them), and both sides of the seam are covered:
  `tests/unit/test_search_results_template.py` pins the template and `movie.search`
  has unit coverage. What is unguarded is the ~15 lines of handler between them.

  Accepted because the alternative — a live TMDB call in the suite — is what made
  those tests slow and flaky and blocked parallel runs (4.1 min → 1.0 min). This
  is a decision, not an oversight: please do not "restore real coverage" by
  putting the network call back. If it is ever worth closing, fake the provider
  *inside the server* so the real handler and template run with no internet.

- **PARTIAL (T1.7).** E2E specs used to be state-coupled through one shared
  server at `workers: 1` (a spec clicking "Mark as Done" changed what
  `release_controls.spec.ts` saw). `tests/e2e/fixtures.ts` now gives every
  Playwright worker its own CouchPotato server, port and data dir, and
  `test.describe.configure({ mode: 'serial' })` on categories/profiles is gone.
  `isolation-a-mutate.spec.ts` + `isolation-b-assert.spec.ts` run as their own
  project at `--workers=2` as a direct proof rather than a green suite.

  **Parallelism did NOT land, and `workers: 1` stays** (`playwright.config.ts`).
  Measured on the T1.7 tree: **0 of 5 parallel runs passed**. Per-worker
  isolation cannot remove cross-file coupling when Playwright runs fewer
  workers than spec files, so two coupled specs still share a worker.
  AC-SIMP-12 made parallelism conditional on the isolated suite being both
  faster and green; it was neither.

  **Method note, retained deliberately:** n=3 and n=4 both came back all-green
  before the n=5 run found the flake. Do not conclude "parallel is safe" from a
  handful of runs; this failure mode needs ten or more.

  **Residual, ~2 runs in 10 on the full chromium suite.** Eliminated by
  measurement during PR 1, each individually: seeding (15/15 clean standalone,
  and a failed seed can no longer be skipped), the data (all seeded documents
  intact at the moment of failure), server latency (74 ms peak across 63 polls
  during a failing run), rate limiting (localhost exempt; 340 consecutive
  requests all 200), scheduled jobs (every interval is 12-24 h with its first
  fire at now-plus-interval), and any one spec's mutation
  (`movie-detail.spec.ts` passes 8/8 alone; preceding it with either
  `interactions.e2e.spec.ts` or `filters.spec.ts` reproduces at the same rate).
  What remains correlates with elapsed time and volume, not with which tests
  ran. ~~Host contention on longer runs is the standing hypothesis and is not a
  code defect.~~

  **ROOT CAUSE FOUND, 2026-08-06. It was a code defect, and the "host
  contention" conclusion above was wrong.** The per-worker application log this
  branch started retaining (`tests/e2e/fixtures.ts` → `test-results/`) carried,
  in one failing run, ten of:

  ```
  sqlite3.InterfaceError: bad parameter or other API misuse
    File ".../core/db/sqlite_adapter.py", line 308, in get
      row = conn.execute("SELECT ... WHERE _id = ?", (key,)).fetchone()
  ```

  driving `Failed doing api request "media.list"` and `"profile.list"` — which
  is exactly the reported symptom, an empty grid and a release table that never
  appears. `open()`/`create()` build ONE `sqlite3.Connection` with
  `check_same_thread=False`, FastAPI runs sync route handlers in a threadpool,
  and only WRITES were serialised, so concurrent reads (and reads racing
  writes) interleaved on the same connection. Some interleavings surface as
  `KeyError('Document not found')` for a document that IS present, or
  `TypeError: the JSON object must be str, bytes or bytearray, not NoneType`.

  Reproduced deterministically in `tests/unit/test_sqlite_adapter_concurrency.py`
  (8 threads, one adapter: 127 errors from `get()`, 316 from `query()`), and
  fixed by serialising every connection touch.

  **This was never test-only** — but the reason given here first was the wrong
  half. "A read interleaving with a write is the same misuse" sounds right and
  is the one configuration that measured **zero** errors: CPython runs the
  connection in SQLite's *serialized* threading mode, so read-vs-write is
  already mutexed. What actually breaks is read-vs-read on the SAME SQL text,
  because `sqlite3` keeps a per-connection prepared-statement cache and two
  threads running the same statement reset each other's mid-flight (measured:
  same SQL 334 errors, different SQL 0, reader-vs-writer 0, same SQL with
  `cached_statements=0` 0). The claim that stands is the plain one: a
  self-hosted install serves concurrent requests from an ordinary browser, and
  `get()` issues one identical SELECT from every thread. The full measurement
  is in `tests/unit/test_sqlite_adapter_concurrency.py`'s docstring, which was
  honest about this while this entry was not — the doc a reader consults was
  the weaker of the two.

  Why the earlier elimination round missed it: every measurement was taken from
  OUTSIDE the app (latency, rate limits, seed integrity, spec ordering). The
  evidence was in the application's own log, which nothing kept until this
  branch made the harness retain it. That is the lesson, not the SQLite detail.

### Deferred at PR 1's review (2026-08-06)

Raised by the multi-lens review of `m0-safety-net`, investigated, and
deliberately not fixed there. Each is pre-existing unless noted; the ones the
branch caused were fixed in it.

**Accessibility**

- **`focus:outline-none` on ~93 remaining controls.** Tailwind's `outline-none`
  compiles to `outline: 2px solid transparent` (verified in the vendored CDN
  bundle) and at specificity (0,2,0) beats `base.html`'s `:focus-visible`
  (0,1,0), so those controls have no visible keyboard focus ring. The two on
  axe-scanned pages (`wanted.html` filter, `add.html` search) were fixed;
  `wizard.html` alone holds 63. Use the `movie_releases.html:88` idiom.
- **Reorder focus management, profiles and categories.** The quality list keys
  `x-for` by INDEX, so the DOM node stays put and the item under the focused
  button changes: pressing "move down" twice ping-pongs one item and the
  control's accessible name changes with no announcement. The profile list keys
  by `_id` and fails the opposite way: reaching a boundary disables the focused
  button, which drops focus to `<body>`. Neither list announces the move.
- **`#movie-grid` is an `aria-live` region wrapping the whole library.** On load
  a screen reader hears every card; the filter mutates the region on each
  keystroke. The count is already computed (`countText`) and should be
  announced from a small `sr-only` region instead, as the empty state already is.
- **Arrow keys move horizontally when the grid holds fewer cards than columns**
  (`cols` is read from `gridTemplateColumns`, always 6). `Home`/`End` skip
  `preventDefault` when already at the target, so `End` scrolls the page.
- **The bulk-select checkbox's focus ring is clipped by `sr-only`** — it is the
  first tab stop inside every card, and the only signal is the graphic
  appearing, identical to hover.

**Operability**

- **`Dockerfile`'s HEALTHCHECK hardcodes 5050** while `--port` now ships in the
  production image. An operator who adopts the flag gets a permanently
  `unhealthy` container, and under a health-acting supervisor a restart loop
  caused by a working change. Cheapest honest fix: say so in the `--port` help.
- **Three `return`-on-error paths in `runCouchPotato` still exit 0** having
  bound nothing (soft-chroot init failure, the generic soft-chroot exception,
  and under-100 MB free space), and `CouchPotato.py:148`'s bare
  `except OSError: pass` shadows the more careful handler below it, so an
  `OSError` from `Loader.__init__` exits 0 with **no log line anywhere**. With
  `restart: unless-stopped` that is a silent restart loop. T1.7 fixed only the
  uvicorn call site.

**Testing**

- **~13 tests in `interactions.e2e.spec.ts` still assert nothing** about the
  behaviour they name; their only assertion is `checkNoErrors`, which checks for
  three console error strings. "clear logs button works" clicks Clear and
  asserts nothing was cleared. AC-SIMP-7 measured `if (await` occurrences
  (63 → 34) as a proxy, and the proxy moved while the population largely did
  not.
- **The unknown-path response is FastAPI's raw `{"detail":"Not Found"}`** —
  measured 2026-08-06. Correct status, no traceback, but no HTML and no
  navigation for a user who mistypes a URL. An error page is product surface,
  not a safety net, so it was recorded rather than added.
- **`removePyc` reaches into other workers' data dirs.** Every worker's startup
  `os.rmdir`s any empty directory under the repo root, and T1.7 sites the
  per-worker data dirs there. Self-healing in microseconds; it disappears if the
  dirs ever move under the system temp dir.

### Deferred at PR 1's SECOND review round (2026-08-06)

**`transaction()` holds the connection-wide lock across arbitrary event
handlers, including blocking HTTP.** Introduced by the connection-serialisation
fix above and knowingly left in. Before it, `transaction()` held a write-only
lock, so a slow handler blocked writes; now it blocks reads too.
`media/_base/media/main.py`'s `delete` fires `media.restatus` inside the
transaction, `restatus` fires `<type>.downloaded`, and every enabled
notification provider does a blocking `urlopen` with a 30 s default. With a
provider configured and unreachable, every database read in the process stalls
for up to 30 s per provider, and the container healthcheck can trip a restart
that kills the transaction.

Nothing is lost when it does (verified: SIGKILL mid-transaction leaves
`PRAGMA integrity_check = ok`, an empty `foreign_key_check` and zero of the
in-flight documents committed), so this is availability rather than
recoverability. **The symptom on-call will actually be handed** is worth naming
so nobody chases it as a phantom: the transaction in question wraps
`media.delete`, so a healthcheck restart mid-delete rolls the delete back and
the user sees a movie they deleted reappear. That is correct behaviour, not
data loss. Review found no deadlock: `media_lock` is always taken before the connection lock, always for
the same key, and nothing inside joins another thread.

`fireEventAsync` was tried and reverted: it breaks three tests that assert the
notification synchronously, and making them wait on a daemon thread trades an
availability bug for a flaky one. The real fix is the design rule **no network
I/O inside a database transaction** -- hoist the `media.restatus` calls out of
the `with transaction:` block, which is what the sibling `notify.frontend` call
already does. That belongs with the per-thread-connection work, not in a safety
net PR.

**The soft chroot is a LEXICAL boundary, not a real one.** `chroot2abs`
normalises and refuses `..` escapes, and `initialize` now absolutises the
chroot root, but neither resolves symlinks BELOW the jail: a symlinked
directory inside the chroot reaches its target, so `directory.list` can
enumerate outside it. Accepted, but the reachability argument is NOT
"only the operator can do this". A link can also arrive as content: the
download and extraction paths write third-party archives into a directory that
is normally inside the jail, which is exactly why
`scanner/folder_scanner.py` defends against planted symlinks for SCANNING
(PR #151). It does not defend the browse path. The impact stays low because
`directory.list` is api-key authenticated on a single-key install, and because
the class docstring has always said "since it is not real chroot" -- but the
reason should be the real one.
Recorded here because it was accepted verbally at the second review round and
**nothing was written down** -- an accepted risk with no record is
indistinguishable from one nobody noticed, and the next person to read
`softchroot.py` would reasonably conclude the boundary is real. Closing it
means comparing `os.path.realpath` on both sides, which is a behaviour change
(it rewrites a symlinked chroot into its target, changing every directory value
the settings UI shows) and wants its own criterion.

Related and same class: a chroot setting containing `..` AFTER a symlink
component (`srv/link/..` where `srv/link` points elsewhere) passes
`os.path.isdir`, which follows symlinks, while `abspath` resolves it lexically
to `srv/` -- a lexical ancestor. Wider by REACHABILITY rather than lexically: the
symlink still sits inside the new jail, so its target stays reachable, while
`is_subdir` on the target itself returns False. `realpath` at `initialize` would close both; it was not taken for
the reason above.

**`compact()` now blocks every read for the duration of a VACUUM.** Not on a
weekly *schedule*, which "weekly" here previously implied: `compact()` is wired
to `database.setup.after` (`core/database.py:34`), i.e. it runs at STARTUP, and
only if `last_db_compact` is more than 604800s old (`:325`). So a container that
is never restarted never compacts at all, and one restarted daily compacts on
the first start after each 7-day mark. Correct as far as it goes, since it previously took no lock
at all, which was the misuse being fixed. VACUUM is atomic, so a restart
mid-VACUUM cannot corrupt the file. Disappears with per-thread connections.

**Rule 6 of `check_test_traps.py` is a partial substitute for the review step
`AGENTS.md` retired.** Five shapes remain invisible: a non-braced single
statement `if`, a ternary, a logical-and short circuit, a destructured binding,
and `test.skip(cond, ...)`. None is currently used in `tests/e2e/**`. They are
listed in the rule's own module docstring; closing them properly needs a JS
parser, at which point the rule should become an ESLint plugin rather than be
extended again.

**No behavioural test covers the adapter's write path under concurrency.**
Two attempts were written and both were incidentally passing, which is recorded
in `tests/unit/test_sqlite_adapter_concurrency.py`'s docstring: a mixed
read/write hammer passed 30/30 against a deliberately split lock, and a
"read must wait for a write" test passed too, because CPython runs the
connection in SQLite's *serialized* mode and the C library already mutexes each
API call. The write path is covered by construction (every write method carries
the same decorator on the same lock as every read), not by a test.

### STOPPED after four rounds: `moveFile`'s composite-call class (2026-08-06)

**This is a frame problem, recorded rather than fixed a fourth time**, per
CLAUDE.md rule 11 ("after three failed fixes, question the frame, not the
fix"). Four consecutive review rounds have each found the same class in the
same function, each fix correct and each incomplete:

| Round | Fixed | Missed |
|---|---|---|
| 2 | `copy` and `symlink_reversed` clean up a partial destination | the `link` fallback, which is the shipping default |
| 3 | `shutil.copy` -> `copyfile` (copymode can fail alone) | `shutil.move`, the same composite shape |
| 4 | `shutil.move(..., copy_function=copyfile)` (copystat) | `shutil.move`'s trailing `os.unlink(src)` |
| 5 | -- | the frame |

**The measurement.** Reproduced with no monkeypatching at all: a download
directory the process cannot delete from (a `:ro` volume, a CIFS share
without delete permission, `chflags uchg`, or on Windows the seeding client
holding the file open, which is `symlink_reversed`'s entire reason to exist):

```
RESULT: raised PermissionError [Errno 13] Permission denied: .../downloads/movie.mkv
source exists: True
dest exists:   True   complete: True
--- retry, as the next renamer run would ---
RETRY: raised FileExistsError Destination ".../library/movie.mkv" already exists
```

Both `shutil.move` sites, and the default branch's inline recovery too: its
recovery step IS `os.unlink(old)`, the call that just failed.

**Why chasing sub-calls does not converge.** `shutil.move` is
`copy_function(src, dst)` **then** `os.unlink(src)`; `shutil.copy` is
`copyfile` + `copymode`; `copy2` is `copyfile` + `copystat`. Each fix removed
one failing half and left another. The property that matters is not "which
sub-call can fail" but **"what is true on disk afterwards"**: the bytes are
complete at the destination and the run reports failure, so the `lexists`
guard blocks every retry for ever and the reverse symlink is never created.

**DO NOT DESIGN THE FIX HERE.** That instruction is itself a finding. Three
review rounds were spent on a sketch of the shape a fix should take, and the
sketch produced one Critical and two Highs -- each time correct-looking prose
that destroyed the user's download when implemented literally. Designing a
change to the renamer's most destructive path, inside a debt note, without a
test harness around it, does not work; that is now measured rather than
suspected.

What this branch DID establish, and what is worth carrying forward, is a set
of constraints any fix must satisfy. Each was learned by writing a remedy that
violated it and watching the film disappear. Treat them as a checklist for the
change that closes this, not as a design:

**Getting any of these wrong destroys the download.** The first draft said "if the destination survives at the
same SIZE as the source, let the caller treat it as done". Review implemented
that literally and measured the result; so did I:

```
moveFile returned True -> caller treats it as DONE
library bytes are the DOWNLOAD? False
cleanup called on source folder: True     (driven through _moveRenamedFiles)
download still on disk:          False
```

The user's film is replaced by whatever bytes happened to be at the
destination, and the only other copy is deleted. The constraints:

1. **The end-state test must verify CONTENT, not size.** This file already
   knows that: `tests/unit/test_renamer_mover.py` carries an
   `xfail(strict=True)` for exactly this
   (`test_failed_move_with_equal_size_but_different_content_should_not_be_accepted`,
   AC-DATA-4), which XPASSes and reds the suite the day a checksum is added.
   A remedy that reintroduces size-as-proof walks straight into it.
2. **An end-state "success" must NOT authorise cleanup.** At most it should
   unblock the RETRY. Returning True hands `_moveRenamedFiles` permission to
   delete the source folder, which is the whole mechanism T1.8 exists to
   guard. Unblocking a retry is safe; declaring the move done is not.
3. **Establish that `old` and `dest` are DIFFERENT FILES before comparing
   anything.** Content equality is necessary and not sufficient; identity is
   the disqualifier. Measured with all the other constraints in place and a
   library entry that is a symlink back to the download: the comparison opens
   `dest`, follows the link to `old`, reports SAME, and the resume path
   unlinks `old`.

   ```
   BEFORE real files: 1
   moveFile returned: True
   AFTER  source lexists: False
   AFTER  dest lexists: True   isfile: False     <- dangling symlink
   AFTER  real files remaining: []               <- THE FILM IS GONE
   ```

   A hardlink gives the same verdict, and `link` is the shipping
   `file_action` while `default_file_action` is a separate setting, so
   `link`-then-`move` is an ordinary configuration. Use `os.path.samefile`,
   or `st_dev`+`st_ino` via `os.lstat`, and refuse to resume when they are
   the same file or when `dest` is a symlink. Today's `os.path.lexists(dest)`
   refusal is `lexists` precisely because symlinks reach that line.
4. **The comparison has THREE outcomes, not two: same, different, and
   cannot tell.** Only *different* may authorise removing the destination.
   A helper that returns a bool collapses cannot-tell into different, and
   that re-creates the AC-DATA-6 defect: measured, the source-vanished race
   then takes the `else` branch whose `os.unlink(dest)` removes the only
   copy left, and `test_failed_move_when_the_source_vanished_mid_flight_...`
   reds with "the only good copy must not be touched". This is exactly the
   "hardening" the spec already warns against -- today's code lets
   `os.path.getsize(old)`'s `FileNotFoundError` propagate rather than
   catching it, and that propagation IS the guard.

   Constraint 1 as worded invites the bool; this constraint is why it must
   not be taken.

Note also what the sketch silently broke in that run: `symlink(dest, old)`
then raises `FileExistsError` and is swallowed, so the reverse symlink is
never created. This entry's stated harm is "a seeding path never restored";
the naive remedy turns that into "the seed is deleted".

**The retry is blocked at TWO levels, and a fix that only addresses one is
inert.** `moveFile`'s `lexists` refusal is the second; the first is
`_moveRenamedFiles`'s own `os.path.exists(dst)` skip in `renamer/main.py`.
Measured: driving the poisoned state through the real `_moveRenamedFiles`
never calls `moveFile` at all, so a remedy satisfying every constraint above
changes nothing for the user while the unit-level tripwire goes green. The
obvious next step -- relax the caller skip -- is exactly what makes
constraints 3 and 4 load-bearing rather than theoretical. Handle both in one
change, and put the closure condition at the `_moveRenamedFiles` level.

That is a behaviour change on the renamer's most destructive path and belongs
in its own change with its own criteria, not as a fifth patch inside a
safety-net PR. **PR 4 also rewrites `renamer/main.py`'s pre-existing-`dst`
refusal, which is currently the last thing standing between the poisoned
state and this outcome, so the two must be designed together.**

**Nothing is lost today**, which is why this is deferred rather than
blocking: the source survives in every measured case, `_moveRenamedFiles`
sets `skipped` so cleanup is suppressed, and the state is strictly better
than master's (which swallowed the failure and deleted the download). The
harm is a film that is never re-processed and, for `symlink_reversed`, a
seeding path never restored.

**It stops being safe in PR 4.** `specs/REMEDIATION-2026-08.md` schedules
upgrade replacement, which adds a delete to this path. "The library copy is
complete but the run reported failure" is a much worse question once
something is deleting on the strength of that answer. **Close this before
PR 4 touches `moveFile`.**

### Recorded at the eighth review round (2026-08-06)

**`Suggestions Page > tabs switch content` asserts that nothing crashed, not
that anything switched.** `tests/e2e/interactions.e2e.spec.ts` clicks each tab
and finishes on `checkNoErrors`, so it passes if clicking a tab does nothing
at all. Both panels are `x-show`-driven and observable, so a real assertion is
available. Pre-existing, and the sibling of an AC that is already satisfied
(`AC-QA-40`), which is why it does not block this branch. Recorded because it
has been raised in three separate review rounds with no home, and an
unrecorded finding costs a round every time it is rediscovered -- the same
lesson as spec gap 27.

**Rule 6 has known blind spots, and the corpus now distinguishes them from
correct silence.** `tests/unit/rule6_guard_corpus.py` shape 20 (a vacuous
guard written with a multi-line condition) expects 0 because the rule cannot
see it, not because silence is right. Any shape whose name says BLIND SPOT
carries that contract: if a future change makes it report 1, that is good news
and the table should be updated, not reverted.

**`db.get(index, None)` returns the FIRST row of that index, for every
index.** Measured on a four-row quality fixture: `get('quality', None)`
returned `bd50` (first inserted), while `get('quality', '')` correctly raised
`KeyError`. All 22 branches of `_query_index` drop their `WHERE` clause when
the key is `None`, and `get()` then returns `results[0]`. This is the family
that produced two live defects already (`_query_index`'s `'media'` branch,
its missing `'release_identifier'` branch).

PR 1 fixed the one instance it could prove reachable (`movie/searcher.py`'s
`:419` fallback). One more caller passes a profile-supplied identifier
straight through (`searcher.py:319`), which would resolve to an arbitrary
quality if a profile ever held a `None` entry -- reachability unproven, and
byte-identical to `master`, so not a regression.

The durable fix is at the seam, not per caller: make `get()` (as distinct
from `query()`/`all()`, where "no key" legitimately means "everything") raise
on a `None` key. That closes the whole family at one place instead of
chasing callers, which is what this branch spent four rounds learning about
`moveFile`.

**The image shipped two fixable HIGH CVEs for as long as the layer cache hid
them, and three of my diagnoses were wrong before the fourth was right.**

PR #225's `docker` job failed Trivy on `setuptools` 70.3.0 (CVE-2025-47273) and
`msgpack` 1.1.2 (GHSA-6v7p-g79w-8964). Neither is in `requirements.txt`, and
`pip show` and `importlib.metadata` both reported them ABSENT from the built
image. The scanner was right and both of those tools were, in a sense, also
right:

    /usr/local/lib/python3.14/site-packages/pip/_vendor/vendor.txt
        msgpack==1.1.2
        setuptools==70.3.0

**pip vendors them, the base image ships pip, and Trivy reads the vendored
manifest.** Vendored code is not an installed distribution, so every
"is it installed?" check says no while the vulnerable code sits in the image.

Why it surfaced now: the CI build used `cache-from: type=gha`, and the cache
held layers from an older base whose pip vendored unaffected versions. A cached
build scanned CLEAN while the image that would actually ship was vulnerable --
the dangerous direction of a nondeterministic gate, and it had been that way
silently. Removing the cache from the scanning build is what exposed it.

Fixed by removing pip (and setuptools/pkg_resources/wheel) from the runtime
stage. Correct on its own merits: this image never installs a package at
runtime, and build tooling is a recurring CVE surface with no runtime purpose.
Verified: Trivy clean with the CI flags, container starts healthy, no import
errors, nothing in `couchpotato/`, `libs/` or `CouchPotato.py` imports any of
them.

**The diagnostic path is the lesson, not the fix.** In order, I concluded: (1)
a new CVE needing a `cryptography` bump -- true, but a different finding; (2)
a stale base image, "fixed" with `pull: true` -- wrong, the next run still
reported every layer CACHED; (3) the layer cache itself, "fixed" with
`no-cache: true` -- wrong as a diagnosis, though right as a policy, and it is
what made the real cause visible; (4) speculative removal of the packages plus
a `msgpack>=1.2.1` pin -- wrong, and reverted: msgpack is not a dependency of
this project at all.

What broke the loop was giving up on inference and running `find / -iname
'*msgpack*'` inside the image, which pointed straight at `pip/_vendor/`. Three
rounds of plausible reasoning lost to one directory listing. `--no-cache` also
mattered: with the cache on, the local image was clean and the bug was
invisible, so every local reproduction of CI's failure quietly disagreed with
CI and I trusted the local one.

Still open, and **less blocked than this entry first claimed**:
`FROM python:3.14-alpine` remains a floating tag. Two corrections to what was
written here, both found by review and verified:

- `GITLEAKS_IMAGE` (`Makefile:89`) is `zricethezav/gitleaks:v8.30.1` -- a TAG
  pin, not a digest pin. It was cited here as the digest-pinning example to
  follow; it is the same class of pin the Dockerfile already has, just a
  narrower tag.
- `.github/dependabot.yml:53` **already** declares
  `package-ecosystem: "docker"`. The prerequisite this entry described as
  needing to land "in the same change" has been in place all along.

So the follow-up is simply: pin the base by digest and let the existing
Dependabot docker config raise the bumps. It is a small, self-contained PR, not
the two-part change recorded here before.

Worth noting where the wrong version came from: both claims were written from
memory of what the repo *probably* looked like, in an entry whose own subject
is a bug that survived because three diagnoses were reasoned rather than
measured. One `grep` of each file would have caught them.


**Redundant double-locking in `sqlite_adapter.py` (`insert`, `update`,
`delete`).** Raised by the cloud review on PR #225 and confirmed: those three
carry `@_synchronised` AND take `with self._conn_lock:` inline
(`:381`, `:440`, `:575`). `_conn_lock` is an `RLock` (`:107`), so it is
harmless -- but it is confusing in exactly the file where confusion has already
cost one production defect, and a future reader could remove the decorator
believing the inline lock covers the method, or the reverse.

**Deliberately NOT fixed on this branch, and the reason is the point.** The
change is a dedent of roughly forty lines of concurrency-critical code, and
because the RLock makes both versions behave identically, **the test suite
cannot tell them apart**. That is an unverifiable edit to the highest-risk file
in the PR, proposed after thirteen review rounds, on a branch where a fix has
twice introduced a fresh defect (`AGENTS.md` and CLAUDE.md rule 11 both say to
treat the next one as new work). A readability improvement that no test can
confirm does not clear that bar at the end of a long branch.

The right shape for it: its own small PR, where the diff is the only thing in
scope and a reviewer can read the dedent directly against the original.

1. Read `CLAUDE.md` at the START of every session before touching code.
2. Always run `pytest tests/unit/ -q` + `ruff check .` before pushing — don't
   rely on CI.
3. For UI changes, update `tests/e2e/` or CI will fail.
4. Spawn Sonnet sub-agents (`Agent` tool, `model: "sonnet"`) for
   implementation; don't do it all inline.
5. `diskcache` was replaced with `SQLiteCache` (CVE-2025-69872 — pickle RCE,
   lib abandoned).
6. Branch protection check names must match exactly — matrix jobs report as
   `test (3.10)`, not `test`.
7. Dependabot PRs may need `--admin` merge if they predate CI changes.
8. Docker image is **Alpine**-based: use `apk`/`su-exec`/`adduser` in the
   Dockerfile, not `apt`/`gosu`/`useradd`. The entrypoint is `#!/bin/sh` (no
   bash). Heavy deps (cryptography, lxml, bcrypt, pydantic-core) all ship
   `musllinux` wheels, so multi-arch builds don't compile from source.
9. Scan the image before release with Trivy; target 0 CVEs (see
   `docs/development-process.md` → Release).
