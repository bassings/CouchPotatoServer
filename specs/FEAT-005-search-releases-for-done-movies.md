# FEAT-005: Search for releases on a movie you already have

## Problem

Owner's report:

> this should also be the case for downloaded movies, they are marked as done,
> but I may want to download a better version in the future should one come
> out, if I open the title it should search for releases

Today there is no way to do that. `MovieSearcher.single()` short-circuits:

```python
if not movie['profile_id'] or (movie['status'] in ('done', 'downloaded') and not manual):
    return
```

so a `done` movie is never searched. The only escape hatches are re-adding the
movie (which resets its status) or `movie.searcher.try_next`, which is scoped
to swapping the *current* release rather than showing what exists.

Two things are missing, and they are separable:

1. **No per-movie search API at all.** `movie.searcher.single` is an internal
   *event*; the only API views are `try_next`, `mark_failed` and
   `full_search` (the whole library).
2. **`manual=True` alone is not enough.** Even with the gate bypassed,
   `single()` would still:
   - break out of the quality loop on the has-better-quality check
     (`searcher.py`) — for a movie that already has its best quality, that is
     an immediate break, so nothing is searched at all; and
   - **download** whatever it finds, because the download gate is
     `force_download or not could_not_be_released or always_search`, and for a
     released movie the middle term is true.

   Both are correct for the automatic path and wrong for "show me what's out
   there".

## Fix Required

A **list-only** search: find releases, store them as `available`, change
nothing else.

1. `single()` gains `list_only = False`. When true:
   - the `done`/`downloaded` short-circuit is bypassed (as `manual` does);
   - the has-better-quality break is skipped, so every quality in the profile
     is searched even when a better copy is already held;
   - `release.try_download_result` is **not** called — nothing is snatched;
   - the movie's status is not changed.
2. New API view `movie.searcher.search_releases` (media_id), returning
   how many releases are now available.
3. UI: a **"Search for releases"** button on the movie detail page, shown for
   any movie regardless of status, which calls it and re-renders the detail
   partial so the new releases appear in the existing release table.

## Why a button rather than searching on open

Opening a title would fire a full provider sweep across every quality in the
profile — several seconds and a dozen indexer calls per page view, on a
NAS-hosted app. It also makes an idempotent GET do expensive outbound work,
so any accidental refresh re-runs it. An explicit action keeps the cost where
the user asked for it.

## Acceptance Criteria

- [ ] AC1: `single(movie, list_only=True)` searches a movie whose status is
      `done` — the short-circuit that normally returns early does not fire.
- [ ] AC2: it never calls `release.try_download_result`, for any quality,
      even when the movie is released and a result is found.
- [ ] AC3: it does not break on the has-better-quality check — a movie that
      already holds the profile's top quality is still searched for every
      quality in the profile.
- [ ] AC4: found results are still stored via `release.create_from_search`,
      so they appear in the movie's release list.
- [ ] AC5: the movie's status is unchanged by a list-only search (a `done`
      movie stays `done`; a `downloaded` movie stays in the review gate).
- [ ] AC9: a list-only search DOES bump the movie's `last_edit` (via the
      existing `media.tag('recent', update_edited=True)`). This is the single
      mutation it makes, and it is required rather than incidental:
      `release.cleanDone()` deletes every `available` release for a movie
      whose `last_edit` is older than a week, and a `done` movie's `last_edit`
      is typically months old — so without the bump the results would be swept
      before the user could act on them.
- [ ] AC6: the automatic path is untouched — with `list_only` defaulted false,
      the has-better-quality break and the download call behave exactly as
      before.
- [ ] AC7: `movie.searcher.search_releases` is registered as an API view and
      returns `{'success': True, 'found': <int>}`.
- [ ] AC8: the movie detail template renders the button for a `done` movie.

## Affected Files

- `couchpotato/core/media/movie/searcher.py` — `single()`, new API view
- `couchpotato/ui/templates/partials/movie_detail.html` — the button
- `couchpotato/ui/__init__.py` — partial route if one is needed
- `tests/unit/test_search_releases_list_only.py` — new
- `tests/e2e/` — a UI change, so E2E coverage per CLAUDE.md rule 5
