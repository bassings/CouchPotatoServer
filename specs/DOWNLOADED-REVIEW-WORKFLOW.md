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

### User actions (backend) — Phase 3b: DONE. UI — Phase 3c: DONE

The three API views below (all `addApiView`, so reachable at `/api/<route>`)
are implemented and unit-tested
(`tests/unit/test_review_actions_backend.py`). Phase 3c wires the UI buttons
that call them (`couchpotato/ui/templates/partials/movie_detail.html`):

- **Mark Done** (movie, shown only when `status == 'downloaded'`) — single
  click, `fetch('/media.done/?id=<movie_id>')`, toasts "Marked done" and
  reloads on success. Non-destructive, no confirmation.
- **Mark Failed & Re-search** (movie, shown only when `status ==
  'downloaded'`) — `confirm()`-gated (destructive: discards the landed
  copy), then `fetch('/movie.searcher.mark_failed/?media_id=<movie_id>')`,
  toasts "Marked failed — searching for another copy" and reloads on
  success.
- **Mark failed** (per release, shown only for a release row with `status ==
  'downloaded'`) — `confirm()`-gated, then `fetch('/release.failed/?id=<release_id>')`,
  toasts and reloads on success. Sits alongside the pre-existing Skip/Ignore
  button (`release.ignore`, reused unchanged — it already handles the "hide a
  bad release from future searches" case).

All three follow the file's existing Alpine.js `fetch().then(r => r.json())`
pattern (mirroring the pre-existing "Mark as Done"/"Delete" buttons), use
inline Heroicons-outline SVGs (24×24, `stroke-width="1.5"`, per
`docs/design-system/CONFORMANCE.md`) rather than emoji, and reuse the shared
`toast()` helper defined on `appShell()` in `base.html` (reachable from the
nested `x-data` scopes via Alpine's parent-scope chaining). Each success
branch delays the `location.reload()` by 900ms (`setTimeout`) so the success
toast can paint before the full-page reload begins — the loading flag stays
set through the delay so the button can't be re-submitted before the reload
lands. The gating logic (which button shows for which status) is locked by a
Jinja render unit test, `tests/unit/test_review_actions_ui_template.py`, which
renders the actual partial with fabricated `movie` dicts and asserts:
`downloaded` → all three review buttons render and the generic "Mark as Done"
does not; `done`/`active` → the review buttons are absent (and `active` keeps
the generic "Mark as Done" — no regression); and the per-release "Mark failed"
keys off the *release* status, not the movie's. E2E coverage is in
`tests/e2e/movie-detail.spec.ts` — see the coverage-gap note there: there is
no fixture / test-only API to seed a `downloaded`-status movie (CI/local e2e
always start from a fresh, empty data dir), so the E2E suite asserts the
buttons are **absent** for a non-downloaded movie and exercises the
confirm-dialog behavior only when a `downloaded` movie happens to be present,
rather than faking one — the render test above is what deterministically
locks the "buttons ARE shown when downloaded" side that E2E can't reach.

Per-movie (when in `downloaded`):
- **Mark Done** → `media.done` (existing route,
  `MediaPlugin.markDone`, `couchpotato/core/media/_base/media/main.py`) —
  extended so that after the movie CAS-updates to `done`, it also fires
  `release.update_status(rel_id, status='done')` for each of the movie's
  releases currently `downloaded`/`snatched`/`seeding` (the landed-but-not-
  yet-finalized copy). Already-`done`/`available`/`failed`/`ignored`
  releases, and the no-release case, are left alone; the release-completion
  step is best-effort and never turns an already-successful movie update
  into a failure response.
- **Mark Failed & re-search** → new `movie.searcher.mark_failed` route
  (`MovieSearcher.markFailedView` / `.markFailedAndResearch`,
  `couchpotato/core/media/movie/searcher.py`). For each of the movie's
  releases currently `downloaded`/`snatched`/`seeding`/`done`, fires
  `release.update_status(rel_id, status='failed')` (a stronger signal than
  the pre-existing `movie.searcher.try_next`'s `'ignored'`); resets the
  movie to `active` via the CAS `update_with_retry` helper (same pattern as
  `markDone`/`markWatched`); then immediately fires
  `fireEvent('movie.searcher.single', media, manual=True)` so the searcher
  finds the next candidate right away rather than waiting for the next
  cycle (the `failed` release is already excluded by the has-better-quality
  check at `searcher.py:~191`).

Per-release / link (in the releases panel):
- **Skip / Ignore link** → existing `release.ignore` route
  (`release.update_status(id, 'ignored')`, already excluded from future
  grabs) — unchanged.
- **Mark failed** → new `release.failed` route (`Release.failedView`,
  `couchpotato/core/plugins/release/main.py`), calling
  `self.updateStatus(id, 'failed')` and mirroring `release.ignore`'s
  request/response shape.

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

### Notification — Phase 4a: DONE

On entering `downloaded`, fire a `movie.downloaded` event (mirroring the
proven `movie.snatched` notification path,
`couchpotato/core/plugins/release/main.py:387`
`fireEvent('%s.snatched' % data['type'], message = snatch_message, data =
media)` — **not** the dead `renamer.after` chain, see Phase 4b below) with a
"‹title› downloaded — awaiting review" message.

Fire site: `MediaPlugin.restatus()`
(`couchpotato/core/media/_base/media/main.py`), inside the existing
"only update when status has changed" guard (`if previous_status !=
m['status'] and (not allowed_restatus or m['status'] in allowed_restatus):`),
immediately after the successful `db.update(m)`. Conditioned on `m['status']
== 'downloaded' and previous_status != 'downloaded'`, so it fires exactly
once, only on a genuine transition into the review gate, and only when the
status change was actually persisted (a caller-supplied `allowed_restatus`
that excludes `'downloaded'` skips both the write and the notification).
`restatus()` is called repeatedly and from multiple call sites
(`searcher.py`, `release/main.py`), so this two-part guard (persisted status
change AND explicit `'downloaded'` check) is what prevents a re-fire on every
subsequent no-op restatus of an already-`downloaded` movie:

```python
fireEvent('%s.downloaded' % m.get('type', 'movie'),
          message = '%s downloaded — awaiting review' % getTitle(m),
          data = m)
```

Registered on both notification `listen_to` lists so configured providers
*and* the core (DB-persisted) notifier pick it up, exactly like
`movie.snatched`:

- `couchpotato/core/notifications/base.py` `Notification.listen_to` (fans out
  to every configured provider).
- `couchpotato/core/notifications/core/main.py` `CoreNotifier.listen_to`
  (persists a `notification` DB row, queryable via `notification.list`, and
  pushes `notify.frontend` to the legacy long-poll listener).

**Known gap (in scope, not a bug):** the new htmx/Alpine UI does not consume
the `notify.frontend` long-poll stream, so this reaches configured providers
+ the persisted DB notification + the legacy long-poll surface, but not a
new-UI live toast — that's separate work, not folded into this phase.

Tests: `tests/unit/test_downloaded_review_notify.py` — manual-confirmation
completion fires `movie.downloaded` exactly once with a message containing
the title and `data` equal to the persisted media doc; a second `restatus()`
call on an already-`downloaded` movie does not re-fire (idempotency); an auto
profile routing to `done` does not fire; a no-transition call (status
unchanged) does not fire; both `listen_to` lists carry `'movie.downloaded'`.

### Ties into renamer #13 (enrichment) — Phase 4b: DEFERRED

The dead `renamer.before`/`renamer.after` chain (subtitles, trailers,
notifications, metadata — see `specs/RENAMER-EVENT-CHAIN.md`) should, in
principle, fire at the **completion/`downloaded`** point, NOT at an
auto-`done`. Since production shows **no stuck backlog** (0 releases
moved-but-unfinalized), the feared "storm on upgrade" is moot — enrichment
would only fire for genuinely-new completions going forward.

**Deferred, not wired up in Phase 4a.** This is a large reconstruction
coupled to the separate `specs/RENAMER-EVENT-CHAIN.md` project, and must
**not** be naively wired into the review-gate completion point:

- `manage.py`'s `after_rename → release.add()` path finalizes a release
  straight to `done` as a side effect of the rename-completion flow — wiring
  `renamer.after` into the `downloaded` transition without first
  reconciling that path would let a "completion" enrichment call flip the
  release (and, via `restatus()`, the movie) past the review gate it's
  supposed to be waiting behind, defeating the whole point of Phase
  1–3's gating work.
- The file-touching listeners (subtitles/trailers/metadata/library-rescan
  providers on `renamer.after`) expect payload keys like `destination_dir`,
  `filename`, and `renamed_files` that the current, unported rename flow
  (see the `renamer-event-chain-unported` gotcha — the event chain was never
  reconnected during the FastAPI migration) no longer produces. Firing the
  event today would call real subtitle/trailer/metadata providers with an
  incomplete or stale payload shape rather than a controlled no-op.

Pending a prod-backlog decision on `specs/RENAMER-EVENT-CHAIN.md` and a
config gate (default **off**) so enrichment can be turned on deliberately
once the rename flow and its payload are reconciled, rather than firing
unconditionally the moment a movie enters `downloaded`.

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
3. ✅ **DONE (3b + 3c).** **UI actions:** Mark Done / Mark Failed&re-search
   (movie); Skip/Ignore & Mark-failed (release); immediate re-search on Fail.
   Tests + E2E.
   **Phase 3b (backend API views) is DONE** — see "User actions (backend)"
   above for the three routes (`media.done` extended, new
   `movie.searcher.mark_failed`, new `release.failed`) and
   `tests/unit/test_review_actions_backend.py`.
   **Phase 3c (frontend UI actions) is DONE** — the buttons wiring those
   routes into `movie_detail.html` (success toasts paint before a 900ms-
   delayed reload), a Jinja render unit test
   (`tests/unit/test_review_actions_ui_template.py`) that deterministically
   locks the per-status button gating, plus `tests/e2e/movie-detail.spec.ts`
   coverage (buttons absent for a non-downloaded movie; confirm-dialog
   behavior exercised when a `downloaded` movie is present). See "User
   actions (backend)" above for the button-by-button breakdown and the
   E2E coverage-gap note (no fixture produces a `downloaded` movie in this
   suite today — the render test covers the "shown when downloaded" side).

   **Re-add guard — IMPLEMENTED (Phase 3a):** `MovieBase.add()`
   (`couchpotato/core/media/movie/_base/main.py`) defaults `force_readd=True`,
   and the live "Add" buttons (`ui/templates/partials/search_results.html`,
   `movie_info_modal.html`) call `movie.add` with no `force_readd`, so
   re-adding an already-present movie used to hit the `elif force_readd:`
   branch — it deleted the movie's completed release
   (`['downloaded','snatched','seeding','done']`), nulled
   `profile_id`/`category_id`/`tags`, reset `status` to `active`, and
   re-searched. For a `downloaded` (review-gated) movie a single stray "Add"
   click thus destroyed the confirmed copy and the gate; the exact same
   destruction already happened to a `done` movie (pre-existing, app-wide —
   Phase 2 never touched `add()`).

   Fixed app-wide (not `downloaded`-only, which would create a confusing
   asymmetry with `done`): `add()` now tracks the pre-existing movie's
   `previous_status` (captured before `m.update(media)` overwrites it) and
   whether `force_readd` was **explicitly** requested by the caller
   (`force_readd_explicit = 'force_readd' in params`, e.g. the API's
   `force_readd=1`) versus left at the default. When `previous_status` is
   `done` or `downloaded` **and** `force_readd` was not explicit, the
   destructive branch is skipped entirely — no release wipe, no
   profile/category/tags reset, no persisted status change (`db.update` is
   never called, so the confirmed/review-gated doc is untouched), no
   re-search — identical to the pre-existing non-force_readd no-op branch. An
   **explicit** `force_readd` still runs the full destructive re-add
   unchanged (regression-locked). A non-completed existing movie (`active`,
   `wanted`, etc.) and a brand-new movie are both unaffected and keep
   force-readding by default exactly as before.
   Tests: `tests/unit/test_readd_guard_completed_movies.py` — implicit re-add
   of `done`/`downloaded` is a no-op (no wipe, no re-search); explicit
   `force_readd` on a `done` movie still wipes + resets (regression lock); an
   `active` movie is still destructively re-added by default (guard doesn't
   broaden); a brand-new movie is unaffected.
   **Minor (defense-in-depth) — fixed in Phase 2:** a `downloaded` movie with
   **zero** releases + `delete_from='manage'` used to fall to the full
   `db.delete(media)` via the generic loop's post-loop `total_releases == 0 and
   not new_media_status` clause (the top-level guard originally covered only
   `wanted/snatched/late`). The cloud review flagged it; the top-level guard now
   includes `manage` (`delete_from in ['wanted','snatched','late','manage']`), so
   a `downloaded` movie is a no-op restatus regardless of release count and the
   zero-release case is covered. The in-loop manage guard is now redundant for a
   `downloaded` movie (the top-level branch catches `manage` first) but is kept
   as harmless defense-in-depth. Locked by
   `TestManageDeleteExemptsDownloadedMovies.test_downloaded_movie_with_zero_releases_survives_manage_delete`.
4. **Notification + renamer enrichment hook:**
   - ✅ **DONE (Phase 4a).** Fire the `movie.downloaded` notification event
     exactly once on entering `downloaded`, via the proven `movie.snatched`
     path (see "Notification" above). Tests:
     `tests/unit/test_downloaded_review_notify.py` — fires once on a genuine
     transition, does not re-fire on a subsequent no-op restatus, does not
     fire when routed to `done` or when status is unchanged, and both
     `listen_to` lists register the event.
   - ⏸️ **DEFERRED (Phase 4b).** Wiring the dead `renamer.after` enrichment
     chain (subtitles/trailers/metadata/library rescans) into the
     `downloaded` transition (see "Ties into renamer #13 (enrichment)"
     above for why: it's coupled to the separate reconstruction in
     `specs/RENAMER-EVENT-CHAIN.md`, `manage.py`'s `after_rename →
     release.add()` path would finalize releases to `done` and defeat the
     gate, and the listeners' expected payload keys
     (`destination_dir`/`filename`/`renamed_files`) aren't produced by the
     unported rename flow). Pending a prod-backlog decision + a config gate
     (default off).
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
