# BUG-013: Active movies with releases should appear in Available, not Wanted

## Problem
The Wanted page shows ALL `active` movies. It should only show movies that have
NO releases yet. Movies that have any release (file on disk, seeding, available NZBs,
etc.) should appear in **Available**, not Wanted.

## Correct Logic
- **Wanted:** `status=active` AND has NO releases
- **Available:** `status=active` AND has ANY release (done file, seeding, available NZB, etc.)
- **Done/Library:** `status=done` (separate, not currently shown in either page)

## Current Behaviour
Both Wanted and Available query `status=active`. Available additionally filters by
`release_status=available`. This means:
- Movies with done/seeding releases (files on disk) appear in WANTED ❌
- Available only shows movies with downloadable NZB results ❌

## Fix Required
### 1. API: `media.list` needs a way to filter by "has any release" vs "has no releases"
Add support for `has_releases=true/false` param to `media.list` (or similar).

### 2. UI routes in `couchpotato/ui/__init__.py`
Update `partial_movies()` to pass the right params:
- Wanted page (`with_releases=false`): query movies with NO releases
- Available page (`with_releases=true`): query movies WITH any release

### 3. Template
The Available page currently shows movies where `release_status=available` (NZBs ready to
download). Change it to show all active movies that have any release.

## Implementation Notes

### Option A — API param approach (preferred)
Add `has_releases=true` / `has_releases=false` to `media.list` in
`couchpotato/core/media/_base/media/main.py`:

```python
# In media.list handler:
has_releases = kwargs.get('has_releases')
if has_releases is True:
    # Only return media that have at least one release
elif has_releases is False:
    # Only return media with no releases
```

Then in `ui/__init__.py` `partial_movies()`:
```python
if with_releases:
    params['has_releases'] = True   # Available: has any release
else:
    params['has_releases'] = False  # Wanted: no releases at all
    # Remove release_status filter
```

### Option B — SQLite query (simpler)
In `sqlite_adapter._query_index` for `media_status`, join to check for releases.

## Acceptance Criteria
1. Wanted page only shows movies with zero releases
2. Available page shows all active movies with ANY release (done file, seeding, NZB available)
3. Avatar: Fire and Ash and Gladiator II appear in Available (have releases)
4. Empty-release active movies appear only in Wanted
5. All existing tests pass, ruff clean

## Files to Change
- `couchpotato/core/media/_base/media/main.py` (media.list — add has_releases filter)
- `couchpotato/ui/__init__.py` (partial_movies — update query params)
- `tests/unit/` (new tests for has_releases filter)
