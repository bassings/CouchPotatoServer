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

1. **Status + gating (no behavior change yet):** register the `downloaded` movie
   status + label/filter; make the searcher gate on it (skip like `done`).
   Tests: searcher does not select/act on a `downloaded` movie.
2. **Per-profile toggle + completion routing:** add `manual_confirmation` to the
   profile; teach `media.restatus`/completion to route release+movie to
   `downloaded` vs `done` by the toggle. Tests: auto profile → `done` (unchanged);
   manual profile → `downloaded` + no further search.
   **Forward-looking (found in Phase 1 review — must handle here):** two call
   sites key off a fixed movie-status list and would silently *exclude* a
   `downloaded` movie once this phase starts producing them —
   `couchpotato/core/plugins/release/main.py:117`
   (`media.with_status(['done','active'])`, the weekly stale-release cleanup) and
   `couchpotato/core/plugins/profile/main.py:53` (`media.with_status('active')`).
   Audit these (and any other hardcoded status lists) and include `downloaded`
   where a review-gated movie should still be considered.
3. **UI actions:** Mark Done / Mark Failed&re-search (movie); Skip/Ignore &
   Mark-failed (release); immediate re-search on Fail. Tests + E2E.
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
