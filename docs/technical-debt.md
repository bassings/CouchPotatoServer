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
  - `movie.info.release_date` — no provider handler, so the ETA gate had no
    dates at all. Worked around by deriving a theatrical date from the
    `released` string TMDB already stores; the real fix is a provider handler
    using TMDB's per-country `release_dates` endpoint, which would also give a
    digital/physical date. Until then `dvd` is always unknown, so the
    dvd-based unlock paths in `couldBeReleased()` are dead code.
  - `cp.source_url` — **`SourceUpdater.doUpdate()` calls `.get()` on what
    this returns, so every update attempt on a source install dies with
    `AttributeError: 'list' object has no attribute 'get'`** (an unhandled
    `fireEvent` returns `[]` before it reads `single`, so it is an empty list,
    not `None`).
    Reachable: `release-to-prod.yml` attaches `.tar.gz`/`.zip` source archives
    to each stable release, and running one outside Docker leaves no `.git`,
    which is exactly how `SourceUpdater` is selected. Either implement the
    handler or delete that update path.
- **Review + implement Dependabot dependency PRs** — keep the dependency
  update PRs Dependabot opens triaged and merged (bump, verify CI, `--admin`
  merge if they predate a CI change — see Lessons Learned #7); don't let them
  pile up.

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
