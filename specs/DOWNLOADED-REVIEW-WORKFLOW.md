# Manual-Confirmation Download Workflow ("Downloaded / review" gate)

> Status: **DRAFT for review** (Scott to approve before implementation).
> Supersedes the open question in `specs/RENAMER-EVENT-CHAIN.md` about whether to
> auto-mark releases `done` — the answer is **no; introduce a review gate**.

## Problem / motivation

The downloader frequently fetches a bad copy of a movie (wrong cut, bad
encode, mislabeled). Today the searcher has no "stop and let a human confirm"
state: a movie is either `active` (searching **and upgrading**) or `done`.
Because the profile drives an *upgrade-until-finish-quality* loop
(`couchpotato/core/media/movie/searcher.py:125,188-200`), a movie keeps
grabbing higher-quality candidates after the first successful download — the
"continuously downloads unnecessarily" behavior. There is no first-class way to:

1. Stop after the first good download and wait for manual confirmation.
2. Reject a specific bad copy and have the searcher find another.
3. Skip a known-bad release/link so the searcher never grabs it again.

## Key finding — most of this already exists

Verified against `origin/master`:

- **`downloaded` is already a first-class release status** — set by the scanner
  (`couchpotato/core/plugins/renamer/scanner.py:137`
  `release.update_status(..., status='downloaded')`), and already treated as a
  "completed" status in the UI (`ui/templates/partials/movie_cards.html:13`,
  `movie_detail.html:19`). It does **not** currently exist at the *movie* level.
- **`ignored` and `failed` release statuses already exist**, and the searcher
  **already excludes them from being re-grabbed**: `searcher.py:188` only
  reconsiders releases whose status is in `['available','ignored','failed']`
  for the *has-better-quality* comparison, and a `snatched`/`downloaded`/`done`
  release already counts as "have it" and stops the search for that quality and
  below. So the *blacklist* mechanism for point 3 is already written.
- `release.update_status` (`couchpotato/core/plugins/release/main.py`) already
  supports transitioning a release to `done` / `failed` / `ignored`.
- Movie statuses currently observed in production: only `active` (13) and
  `done` (1078); 0 releases sit in `snatched`/`downloaded` (no stuck backlog).

**Implication:** point 3 ("skip a link") is largely a UI exposure of the
existing `ignored` status; the genuinely new work is the movie-level review
gate + the searcher-stop + a per-profile setting + the UI actions.

## Decisions (confirmed with Scott)

- **Scope of the gate: per-profile toggle.** A profile option controls whether
  its movies auto-upgrade-to-done (current default) or stop at first download
  for manual review. Lets "auto" and "manual review" profiles coexist.
- **On "Mark Failed": re-search immediately** (don't wait for the next cycle).
- **Notify** when a movie enters "Downloaded / review".

## Design

### New movie status: `downloaded` (review gate)

Add `downloaded` as a movie (`media`) status meaning "a copy has landed and is
awaiting the user's confirmation". Behavior:

- The searcher treats a movie in `downloaded` like `done` for **gating** — it is
  NOT selected by the `active`-only batch search (`searcher.py:80`) and
  `single()` skips it — so **no upgrade loop, no further grabbing**.
- Visually distinct from `done` (label "Downloaded / review"), filterable in the
  wanted/manage lists.
- Reached only when the owning profile has the manual-review toggle ON.

### Completion path change

Where a completed download currently drives the movie toward `done`
(`media.restatus`, `couchpotato/core/media/_base/media/main.py:723-742`, and the
scanner completion path):

- **Auto profile (default):** unchanged — release → `done`, movie → `done` via
  `restatus` (preserves everyone else's behavior).
- **Manual-review profile:** release → `downloaded`, movie → `downloaded`
  (review gate). Do **not** advance to `done` automatically. Fire the
  notification + the renamer enrichment events (see below) at this point.

`media.restatus` must learn the profile toggle and choose `downloaded` vs `done`
accordingly, and must treat `downloaded` as a terminal-for-search state (don't
demote it back to `active`).

### User actions (UI)

Per-movie (when in `downloaded`):
- **Mark Done** → movie `done`, owning release `done`. Terminal.
- **Mark Failed & re-search** → current release `failed`; movie back to
  `active`; **immediately** trigger `searcher.single(movie, manual=True)` so it
  finds the next candidate (the `failed` release is already excluded by
  `searcher.py:188`).

Per-release / link (in the releases panel):
- **Skip / Ignore link** → `release.update_status(id, 'ignored')` (already
  excluded from future grabs).
- **Mark failed** → `release.update_status(id, 'failed')`.

These call existing `release.update_status`; the work is exposing buttons +
htmx endpoints + wiring the immediate re-search.

### Per-profile setting

Add to the profile model/editor a boolean, e.g.
`manual_confirmation` / "Stop after first download for manual review"
(default **off** = current auto-upgrade behavior). Surfaced in the profile
editor UI. `media.restatus` / searcher read it via the movie's `profile_id`.

**Phase 2 status:** the field exists, persists (`ProfilePlugin.save()`,
`couchpotato/core/plugins/profile/main.py`), defaults `False` for profiles
that don't set it, and is read by `restatus()` for completion routing.
**UI exposure deferred:** the new-UI profile editor
(`couchpotato/ui/templates/partials/settings/profiles.html` +
`couchpotato/static/scripts/ui/profile-editor.js`) is a large, 100%-mutation-
tested surface (`TEST-001`) with its own a11y-parity follow-up already
tracked; adding a checkbox there (plus the matching Alpine state, save-payload
wiring, unit/mutation tests, and any conformance/E2E touch-up) is left for a
Phase 3 follow-up rather than folded into this phase. Until then the toggle
is settable only via the `profile.save` API directly.

### Notification

On entering `downloaded`, fire `notify.frontend` (and the configured
notification providers) with a "‹title› downloaded — awaiting review" message.
This rides on the renamer-completion hook.

### Ties into renamer #13 (enrichment)

The dead `renamer.before`/`renamer.after` chain (subtitles, trailers,
notifications, metadata — see `specs/RENAMER-EVENT-CHAIN.md`) should fire at the
**completion/`downloaded`** point, NOT at an auto-`done`. Since production shows
**no stuck backlog** (0 releases moved-but-unfinalized), the feared
"storm on upgrade" is moot — enrichment fires only for genuinely-new
completions going forward. Wiring the enrichment events is folded into this
feature's completion-path change rather than a separate reconstruction.

## Rollout / safety

- Ship behind `-beta`; the default profile setting is OFF so nothing changes for
  existing users until a profile opts in.
- Test against a **copy** of production data before deploying (the media/release
  state machine is being touched on a live server).
- Existing 1078 `done` movies are unaffected (the change only alters how *new*
  completions behave under a manual-review profile).

## Phased plan (each its own reviewed PR)

1. ✅ **DONE (#168).** **Status + gating (no behavior change yet):** register
   the `downloaded` movie status + label/filter; make the searcher gate on it
   (skip like `done`). Tests: searcher does not select/act on a `downloaded`
   movie.
2. ✅ **DONE.** **Per-profile toggle + completion routing:** add
   `manual_confirmation` to the profile; teach `media.restatus`/completion to
   route release+movie to `downloaded` vs `done` by the toggle. Tests: auto
   profile → `done` (unchanged); manual profile → `downloaded` + no further
   search.

   **Completion-path decision point (traced for this phase):** a completed
   release drives `couchpotato/core/plugins/release/main.py`'s `download()`
   (renamer-disabled path, ~line 361-372) or `renamer/scanner.py`'s
   `checkSnatched()` to set the *release* to `done`/`downloaded`/etc., which
   then calls `fireEvent('media.restatus', ...)`. `MediaPlugin.restatus()`
   (`couchpotato/core/media/_base/media/main.py`) is the single funnel that
   decides the *movie* status: the one insertion point is the branch where a
   `done` release satisfies `quality.isfinish` and the movie was about to be
   set to `done` (~line 757). That branch now checks
   `profile.get('manual_confirmation')` and, only for a genuinely new
   completion (`previous_status != 'done'`), sets the movie to `downloaded`
   instead. The Phase-1 top-level preservation check
   (`previous_status == 'downloaded'` stays `downloaded`) runs first and is
   untouched, so an already-gated movie never reaches the new branch and is
   never auto-advanced to `done`. Release-level status is unchanged by this
   phase (the release itself still ends up `done`); only the movie's status
   field is routed differently. Scope note: this phase only touches
   `restatus()`'s existing decision point, not the full per-release
   `downloaded` routing sketched in the Design section above — that nuance
   (if still wanted) is Phase 3/4 territory.

   **Status-list sites fixed (found in Phase 1 review):**
   - `couchpotato/core/plugins/release/main.py:118` (weekly stale-release
     cleanup): `media.with_status(['done','active'])` →
     `media.with_status(['done','active','downloaded'])` — a review-gated
     movie's stale/duplicate releases still get cleaned up like a `done`
     movie's would.
   - `couchpotato/core/plugins/profile/main.py:53` (`forceDefaults()` orphan
     profile-reference repair): `media.with_status('active')` →
     `media.with_status(['active','downloaded'])` — a `downloaded` movie still
     depends on a working `profile_id` (read by every `restatus()` call, and
     by the future "mark failed & re-search" action), so a dangling reference
     needs the same repair-to-default an `active` movie gets.
   - Audited and **left unchanged** (each is a deliberate exclusion, not an
     oversight): `couchpotato/core/plugins/dashboard.py:48`
     (`media.with_status('active', ...)` for the "Coming Soon" widget — a
     `downloaded` movie isn't coming soon, it already landed); the searcher's
     own `media.with_status('active', ...)` batch-search selects
     (`movie/searcher.py:80`, `profile/main.py`'s `dashboard`-adjacent uses —
     these are exactly the Phase-1 gating points and must keep excluding
     `downloaded`); `release/main.py:196` (`allowed_restatus=['done']` in the
     library-scan `release.add()` path) — mostly moot for `downloaded` since
     that path adds a *brand-new* movie with `profile_id=None` (routed to
     `done` regardless of any profile toggle), but it is reachable for a
     **pre-existing** movie already carrying a `manual_confirmation` profile
     (a rescan hits the "release already tracked" branch and keeps the
     existing `profile_id`); in that case the `allowed_restatus=['done']`
     filter simply skips persisting the `db.update(m)` write when `restatus()`
     computes `'downloaded'` — harmless (the in-memory return value isn't used
     by this caller) and not a regression introduced by this phase, so left
     as-is.
   - **Blocking finding from the phase-2 local review, now fixed (not left
     safe as originally audited):** `couchpotato/core/plugins/manage.py:139`
     (`fireEvent('media.list', status='done', release_status='done',
     status_or=True, ...)`) is an **OR union** (`status_or=True` in
     `MediaPlugin.list()`), so a `downloaded` movie whose release is `done`
     (the normal state for a movie awaiting review) was landing in
     `done_movies` and could be silently `fireEvent('media.delete', ...,
     delete_from='all')`-ed by a routine full library scan (`cleanup` config
     defaults on). The same OR-exposure existed in
     `MediaPlugin.delete(delete_from='manage')`
     (`couchpotato/core/media/_base/media/main.py`), which deletes a release
     when `release.status == 'done' OR media.status == 'done'` — a
     `downloaded` movie's `done` release qualified via the first arm. Both are
     now guarded: the manage cleanup loop `continue`s past any `done_movie`
     whose `status == 'downloaded'` before the deletion/dedup logic runs, and
     the manage-delete release loop adds `media.get('status') != 'downloaded'`
     to its condition so a review-gated movie's release is never swept up by
     that path. Neither guard changes behavior for a genuinely `done` movie.
   - **Second blocking gap in `MediaPlugin.delete`, found in the phase-2
     re-review, now fixed:** the sibling branch `if delete_from in
     ['wanted','snatched','late']` was also unguarded. For a `downloaded`
     movie with a `done` release (the feature's steady state) the release
     survives (`status == 'done'`), but that iteration unconditionally set
     `new_media_status = 'done'`; after the loop `total_releases(1) !=
     total_deleted(0)` fell to `elif new_media_status:`, which overwrote
     `media['status']` to `done` **and** nulled `profile_id` — silently
     bypassing the review gate. For `delete_from='late'` it was worse: the
     post-loop `(not new_media_status and delete_from == 'late')` clause would
     delete the movie doc outright. Reachable (not theoretical):
     `couchpotato/ui/templates/wanted.html` `bulkDelete()` hardcodes
     `delete_from='wanted'` with no status check (stale-selection race — a
     movie can complete to `downloaded` in the background between select and
     click), and the documented public API `movie.delete?delete_from=wanted`
     reaches it directly. Fixed by adding a top-level branch **before** the
     generic release loop: `elif media.get('status') == 'downloaded' and
     delete_from in ['wanted','snatched','late']:` → treat as a no-op that
     only calls `media.restatus`, leaving the movie in `downloaded` with its
     releases and `profile_id` intact. A guard inside the loop (a `continue`)
     would have been insufficient for `late`, since `new_media_status` staying
     falsy makes the post-loop `late` clause fire — the top-level branch
     sidesteps that entirely. A genuinely non-`downloaded` movie's
     wanted/snatched/late behavior is unchanged.
3. **UI actions:** Mark Done / Mark Failed&re-search (movie); Skip/Ignore &
   Mark-failed (release); immediate re-search on Fail. Tests + E2E.
   **Also fold in here — the re-add guard (deferred from Phase 2, found in the
   round-3 completeness sweep):** `MovieBase.add()` defaults `force_readd=True`,
   and the live "Add" buttons (`ui/templates/partials/search_results.html`,
   `movie_info_modal.html`) call `movie.add` with no `force_readd`, so re-adding
   an already-present movie hits the `elif force_readd:` branch — it deletes the
   movie's completed release (`['downloaded','snatched','seeding','done']`),
   nulls `profile_id`/`category_id`/`tags`, resets `status` to `active`, and
   re-searches. For a `downloaded` (review-gated) movie a single stray "Add"
   click thus destroys the confirmed copy and the gate. **Important scope note:**
   this is *not* a Phase-2 regression — the exact same destruction already
   happens to a `done` movie today (all existing `done` movies share it), because
   Phase 2 never touched `add()`; it is a pre-existing, app-wide property of the
   `force_readd` default + an ungated Add button. The correct fix is therefore
   app-wide, not `downloaded`-only (guarding only `downloaded` would create a
   confusing asymmetry with `done`): treat re-adding an already-*completed*
   movie (`done` **or** `downloaded`) as a no-op or require explicit
   confirmation, so a naked "Add" can't silently wipe a completed/under-review
   copy. Belongs with the UI actions since the real fix is UI-level (the Add
   surface should reflect "already in library / under review" state). Tests
   mirroring `TestWantedDeleteExemptsDownloadedMovies`.
   **Minor (defense-in-depth, note for this phase):** a `downloaded` movie with
   **zero** releases + `delete_from='manage'` would still fall to the full
   `db.delete(media)` (the Phase-2 top-level `wanted/snatched/late` guard covers
   it regardless of release count, but the `manage` path relies on the
   "≥1 release" invariant). No reachable live caller sends `delete_from='manage'`
   post-#148, and the invariant holds in practice; widen the top-level guard to
   include `manage` for symmetry when convenient.
4. **Notification + renamer enrichment hook:** fire notify + `renamer.after`
   enrichment on entering `downloaded`; wire the dead listeners
   (per `specs/RENAMER-EVENT-CHAIN.md`). Tests: listeners fire once, only on
   genuine completion.
5. **Docs + beta + prod-copy validation**, then release.

## Acceptance criteria

- A profile with `manual_confirmation` ON: a completed download leaves the movie
  in `downloaded` (not `done`), the searcher stops (no upgrade grabs), and a
  notification fires once.
- **Mark Done** → `done` (terminal). **Mark Failed** → release `failed`, movie
  re-searches immediately and does not re-grab the failed release.
- **Skip/Ignore** a release → excluded from future grabs.
- A profile with the toggle OFF behaves exactly as today (auto-upgrade → `done`).
- Existing `done` movies unchanged; no mass reprocessing on upgrade.
- Full unit + E2E suites green; ruff clean.
