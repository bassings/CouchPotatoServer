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
- **Two E2E specs fail locally but pass in CI — `make verify` cannot currently go
  green on a dev machine.** Both time out at 30s, both verified pre-existing
  (identical failures on a clean tree, 2026-07-30), and both were invisible until
  the interpreter bug below was fixed, because the local E2E stage never actually
  started:
  - `interactions.e2e.spec.ts:35 › Navigation › sidebar links navigate correctly`
    — fails deterministically locally (3/3 runs). Carried in project memory as
    "flaky" rather than in any doc;
    locally it is not flaky, it is consistent, which makes it tractable.
  - `interactions.e2e.spec.ts:298 › Suggestions Page › tabs switch content` —
    genuinely flaky locally (1/3 runs).
  CI is green on both (it also has `retries: 2`, which would paper over the
  flaky one). Until they are fixed, hard rule 2 cannot be satisfied literally, so
  a push needs either these two triaged or an explicit, stated bypass — don't let
  "verify is red anyway" become the normal state, which is how a gate dies.
- **E2E specs are not worker-independent, so the suite runs single-worker.**
  `categories.spec.ts`, `profiles.spec.ts`, `search.spec.ts`,
  `interactions.e2e.spec.ts` and `release_controls.spec.ts` mutate *global* server
  state (categories, quality profiles) on one shared app instance, so parallel
  workers clobber each other's fixtures. `playwright.config.ts` previously used
  `workers: process.env.CI ? 1 : undefined`, which hid this: CI serialised and was
  green while a local run used one worker per core and failed ~20 of 142 specs —
  i.e. `make verify` could never pass locally, in direct conflict with hard rule
  2. Pinned to `workers: 1` everywhere on 2026-07-30.

  Verified on a clean tree: with default workers ~20 fail (the exact count varies
  run to run — it is a race), spread across categories×11, interactions×3,
  profiles×3, search×2, release_controls×1; with one worker, **all of those
  pass** and only the two unrelated failures above remain. The real fix is
  per-worker isolation — a fixture that namespaces the categories/profiles it
  creates, or a server per worker — after which `fullyParallel` can be restored
  and the suite gets its wall-clock back.
- **Two hardcoded third-party API keys inherited from upstream** — both
  baselined in `.gitleaksignore` (added 2026-07-30 with the `secrets` gate) and
  both already public in every copy of the upstream repo, so they leak nothing
  that is not already out:
  - `couchpotato/core/media/movie/providers/info/fanarttv.py:18` — fanart.tv v3
    key baked into the request URL. There is already a `fanart.tv` `api_key`
    setting (the provider errors at line 130 when it is blank), so the fix is to
    read the setting and drop the literal — a behaviour change (existing installs
    with no key set would lose fanart lookups), hence its own commit.
  - `couchpotato/core/media/movie/_base/static/movie.actions.js:378` — YouTube
    Data API key in a trailer-lookup URL. **This needs its own deliberate
    deletion — it will NOT resolve itself.** The file is an orphan that both UI
    cleanups left behind: UI-CLEANUP-02 shipped (`02d2eece`, merged as #148),
    `specs/UI-MIGRATION.md` records the legacy asset layer as fully retired,
    `/old/*` is now a bare 302, and `grep -rn "movie\.actions"` finds no live
    reference anywhere — yet the file and its key are still tracked. An earlier
    version of this entry claimed it "goes away with UI-CLEANUP-02, no separate
    work needed", which parked a live item behind a completed task. Deleting an
    unreferenced legacy file is a small change but a real one, so it belongs in
    its own commit rather than riding along with tooling work.
  Full git history holds ~37 findings in total (`make check-secrets-history`).
  Verified breakdown as of 2026-07-30 — the "all upstream, all pre-2013" framing
  that first accompanied this entry was wrong on both counts:
  - 29 by `ruud@crashdummy.nl` (upstream) spanning **2011–2016**, not 2011–2012
    (10 of those 29 are 2013 or later);
  - 2 by other upstream contributors, one of which is the only 2017 finding;
  - **6 by `bassings@gmail.com` — this fork's own commits.** One is the
    per-install `api_key` in `QA/QA_SESSION_2026-02-19.md` (redacted from HEAD on
    2026-07-30; still in history, which is why rotation rather than redaction is
    the remedy for anything that matters). The other five are under
    `migration_backup/` (2025-07-30) and are *copies* of the same upstream
    provider keys; that directory is no longer tracked.

  So there is no fork-introduced credential in history beyond the throwaway
  api_key. Rewriting history to purge upstream's keys is not proposed. What was
  worth fixing was the guidance: telling the next person to expect "~37 pre-2013
  upstream hits" would have filed this fork's own committed key under expected
  noise.

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
