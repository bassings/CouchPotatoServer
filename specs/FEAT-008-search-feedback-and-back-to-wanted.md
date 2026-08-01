# FEAT-008 — "Search for releases" must actually search, and "Move back to wanted"

Two user reports, 2026-07-31. They look separate and share one root cause: **1101
of 1101 library movies have `profile_id = None`**, and both the search path and
the wanted path are gated on having a profile.

---

## Problem 1 (BUG) — "Search for releases" silently does nothing

**Reported:** *"I went in to a release and click the search for release button, it
doesn't seem to refresh the search results on the screen. I have to manually hit
refresh. There is no way to know when the search is completed."*

**Measured on production:**

```
POST movie.searcher.search_releases  ->  0.0s   {"success": true, "found": 0}
releases before: 1      releases after: 1   (delta 0)
```

It is not slow and it is not a refresh problem. **No search ever runs.**

**Root cause.** The first gate in `MovieSearcher.single()`
(`couchpotato/core/media/movie/searcher.py`), as it stood on master:

```python
if not movie['profile_id'] or (movie['status'] in ('done','downloaded')
                               and not manual and not list_only):
```

`not movie['profile_id']` is an independent clause. `list_only` was threaded
carefully through every *other* gate in `single()` (the done/downloaded gate, the
`has_better_quality` break, the untitled-movie delete) — but not this one. Movies
imported by the library scanner never get a profile, so FEAT-005 is dead for
exactly the case it was built for: a movie you already have.

Verified on prod: 59 of 60 sampled movies are `status=done, profile_id=None`.
The one exception, and the 14 `active` movies, all have a profile.

**Second defect, on top.** `_searchReleases` reports
`{'success': True, 'found': 0}` whether the search ran and found nothing, or
never ran at all. The UI then says "Found 0 releases" and reloads, so the user
sees a successful-looking no-op. The report "no way to know when the search is
completed" is a fair description of a system that says it finished when it never
started.

### Acceptance criteria

1. `movie.searcher.search_releases` on a movie with **no** `profile_id` performs
   a real provider search, using the default profile (`fireEvent('profile.default')`
   — the same fallback `movie.add` already uses).
2. It does **not** assign that profile to the movie, or change `status`. A
   list-only search stays read-only with respect to library state.
3. The response distinguishes the three outcomes, so the UI can too:
   - searched, found N (`searched: true`)
   - searched, found nothing (`searched: true, found: 0`)
   - could not search, with a reason (`searched: false, reason: <str>`)
4. If no profile exists at all (fresh install, all profiles deleted), it returns
   `searched: false` with a reason naming that — never a bare success.
5. The UI updates the release list **in place** on completion and reports which
   of the three outcomes occurred. No full `location.reload()`.
6. While the search runs the control is disabled and says so; the user can tell
   the difference between "running" and "finished".

### Explicitly out of scope

Making the search asynchronous with polling. It is synchronous today, dispatched
off the event loop (`couchpotato/__init__.py:248`), so a slow search does not
block other requests. In-place update plus a disabled control is enough; a job
queue is a much larger change and is not what was reported.

---

## Problem 2 (FEATURE) — move a `done` movie back to wanted

**Reported:** *"I'd like the ability to take something that is done and move it
back to wanted."*

Today the only route from `done` back to `active` is deleting and re-adding,
which loses the release history.

The same `profile_id = None` fact matters here: a movie moved to `wanted` without
a profile is *unsearchable* — it would sit in Wanted forever, and the automatic
searcher would skip it on the very same gate. So this must assign a profile.

### Acceptance criteria

1. A new API view `movie.restore_to_wanted` (param `media_id`, optionally
   `profile_id`) sets the movie's status to `active` and ensures it has a
   profile: the caller's `profile_id` if given, else the movie's existing one,
   else the default profile.
2. It refuses, with a stated reason, if no profile can be resolved — rather than
   creating an unsearchable Wanted entry.
3. Existing releases are preserved — nothing is deleted, and the release
   history stays visible on the detail page.

   The releases the movie already **holds** (`done` / `seeding` /
   `downloaded`) are marked `ignored`. This is required, not incidental: a held
   release counts as satisfying the profile in two independent places, and the
   movie is not really "wanted" until both stop counting it —

   - `MediaPlugin.restatus` recomputes status from releases whose status is
     `done`, so the held one finishes the movie again on the very next sweep.
     With `manual_confirmation` (the default) `previous_status` is now `active`
     rather than `done`, which routes it into the `downloaded` review gate
     **and** fires a `movie.downloaded` "awaiting review" notification for a
     movie the user never re-downloaded.
   - `MovieSearcher.single`'s `has_better_quality` loop counts any release
     whose status is not in `('available', 'ignored', 'failed')`. A held
     release at the profile's top rung makes it break on the **first** quality,
     before contacting any provider.

   `ignored` (rather than `failed`) because nothing failed — the user simply
   wants something better. This mirrors `markFailedAndResearch`, which marks
   the landed release `failed` for the same structural reason.

   **Durability is `release.add`'s job.** A library rescan rebuilds the
   release doc with a hardcoded `'done'`, so the mark has to survive that. The
   rule there keys on the **copy**, not the quality rung: the deliberate status
   is preserved only while the scanned file set is the one that was set aside.
   This is a pre-existing platform bug, not something this feature introduced —
   `tryNextRelease` and `markFailedAndResearch` both mark by status and have
   both been silently undone by rescans.

   **Rejected alternatives**, each of which shipped a new defect before being
   caught:

   1. *A timestamp on the media doc, with `restatus` discounting older
      releases.* Addressed only `restatus`, not `has_better_quality`, so the
      movie sat in Wanted contacting zero providers; and `release.add` rewrites
      `last_edit` on any rescan, re-arming the bug.
   2. *Preserving the status in `release.add` keyed on `release_identifier`.*
      That identifier is `<imdb>.<audio>.<quality>` — a quality RUNG — so it
      meant "never record any copy at this quality again": a re-downloaded
      1080p landed on disk and was filed `ignored`, the movie never completed,
      and the searcher re-grabbed it weekly. It also broke the two shipped
      features above, `markFailedAndResearch` worst of all because a `failed`
      row renders no action button.
   3. *Requiring a profile that leaves room above what is held, and refusing
      otherwise.* Sound in principle — measured, a movie on `[2160p, 1080p]`
      holding 1080p searches and stays wanted with no intervention at all. But
      every profile this app creates uses `finish=True` on every rung, so
      `isFinish` is true for any held release and the refusal would reject
      essentially every real restore.
4. It is idempotent: calling it on an already-active movie is a no-op success.
5. The movie appears in the Wanted view afterwards and is picked up by the
   automatic searcher (i.e. it passes the `single()` gate).
6. UI: a "Move back to wanted" control on the movie detail page for movies whose
   status is `done`, with a profile picker defaulting to the default profile.
   It updates in place and reports the outcome.

---

## Affected files

| Path | Change |
|---|---|
| `couchpotato/core/media/movie/searcher.py` | `list_only` bypasses the no-profile gate; `_searchReleases` returns `searched`/`reason` |
| `couchpotato/core/media/movie/_base/main.py` | new `movie.restore_to_wanted` view + event |
| `couchpotato/ui/templates/partials/movie_detail.html` | in-place update for search; new "back to wanted" control |
| `couchpotato/ui/__init__.py` | partial endpoint if the release list needs re-rendering |
| `tests/unit/test_search_releases_list_only.py` | extend: no-profile case |
| `tests/unit/test_restore_to_wanted.py` | new |
| `tests/e2e/movie-detail.spec.ts` | both controls |

## Risks

- **Do not let a list-only search mutate the library.** `single()` calls
  `media.restatus` on several paths; the no-profile bypass must not introduce a
  status change. Assert this in a test.
- **Do not delete anything.** The untitled-movie branch already deletes media;
  the list_only guard there must stay.
- **Do not change shared `restatus` behaviour.** An attempt to solve AC3 there
  affected every media type and every caller for the benefit of one feature.
  The release-status approach above is contained to the movies this action
  touches; `couchpotato/core/media/_base/media/main.py` is untouched by this
  branch.
- Changing the searcher's first gate affects the automatic path too. The
  condition must remain exactly as-is when `list_only` is false — pin with a test
  that a non-list_only search on a profile-less movie still returns early.
