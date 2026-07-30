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

## Lessons learned

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
