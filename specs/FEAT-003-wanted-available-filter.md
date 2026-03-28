# FEAT-003: Merge Available into Wanted — Filter Redesign

## Status
Ready for implementation

## Problem

The current navigation has "Available" as a top-level sidebar item alongside "Wanted". This is
confusing because "Available" is not a separate section — it's a sub-state within the Wanted
pipeline. A movie is "Available" when the searcher has found releases for it (or the downloader
has started/completed a download), but the user hasn't confirmed it done yet.

Additionally, the Wanted page filter bar shows: **All / Wanted / Done**. The "Done" filter is
pointless here — done movies are in the Library, not the Wanted list.

## Intended User Flow (for reference)

1. User adds a movie with a desired quality profile → status: **Wanted**
2. Searcher finds releases at the desired quality → status: **Available**
3. Downloader grabs the highest-scored release and downloads it → status still: **Available**
4. User checks the file, optionally selects a different release and re-downloads
5. User clicks "Done" → movie moves to **Library**
6. If not done yet: user can open the movie and hit Refresh to re-search

## Proposed Changes

### 1. Remove "Available" from sidebar navigation

In `base.html`, remove `('available', 'Available', ...)` from `nav_items`.

The sidebar becomes: **Wanted / Library / Classic UI**

### 2. Replace "Done" filter with "Available" in Wanted filter bar

In `wanted.html`, change the filter buttons from:
```
All  |  Wanted  |  Done
```
to:
```
All  |  Wanted  |  Available
```

Filter definitions:
- **All** — all active movies (status=active); everything not done. No change to what loads.
- **Wanted** — active movies with NO releases found and NOT downloading (`data-has-releases="false"`)
- **Available** — active movies that have releases found OR are downloading/downloaded (`data-has-releases="true"`)

### 3. Add `data-has-releases` attribute to movie cards

In `couchpotato/ui/templates/partials/movie_cards.html`, add to the `.poster-card` div:

```html
data-has-releases="{{ 'true' if releases|length > 0 else 'false' }}"
```

`releases` is already computed at the top of the template. Any non-empty releases list means the
searcher (or downloader) has touched this movie — covers Option B (releases found OR downloading/downloaded).

### 4. Update `filterMovies()` JS in `wanted.html`

Change the filter matching logic. Currently:
```js
const matchStatus = !this.filterStatus || status === this.filterStatus;
```

Update to:
```js
const hasReleases = card.dataset.hasReleases === 'true';
let matchStatus;
if (!this.filterStatus) {
  matchStatus = true; // All
} else if (this.filterStatus === 'available') {
  matchStatus = hasReleases; // has releases or downloading
} else if (this.filterStatus === 'wanted') {
  matchStatus = !hasReleases; // no releases yet
} else {
  matchStatus = status === this.filterStatus; // fallback
}
```

Update the filter button for "Available":
```html
<button @click="setFilter('available')"
        :class="filterStatus === 'available' ? 'bg-cp-accent/10 text-cp-accent' : 'bg-white/[0.03] text-cp-muted hover:text-cp-text'"
        class="px-2.5 py-1 rounded-md transition-colors">
  Available
</button>
```

### 5. Update movie grid hx-get on Wanted page

The Wanted page currently has conditional logic for `current_page == 'available'`. Since Available
is no longer a page, simplify the grid to always load `status=active`:

```html
hx-get="{{ new_base }}partial/movies?status=active"
```

### 6. Handle `/available` route

The `/available` URL will still work (route still exists in the backend) but won't be linked from
nav. Add a redirect from `/available` → `/wanted?filter=available` so any bookmarks keep working.

## Files to Change

| File | Change |
|------|--------|
| `couchpotato/ui/templates/base.html` | Remove "available" from nav_items |
| `couchpotato/ui/templates/wanted.html` | Replace Done filter with Available; update filterMovies() JS; simplify hx-get |
| `couchpotato/ui/templates/partials/movie_cards.html` | Add `data-has-releases` attribute |
| `couchpotato/core/web/app.py` (or routes file) | Add redirect: /available → /wanted?filter=available |

## Acceptance Criteria

- [ ] "Available" is removed from the sidebar on desktop, mobile bottom nav, and mobile drawer
- [ ] Wanted page filter bar shows: All / Wanted / Available (no Done)
- [ ] "All" shows every active movie (same as current default load)
- [ ] "Wanted" filter shows only movies with no releases found
- [ ] "Available" filter shows movies that have releases OR are downloading/downloaded
- [ ] Navigating to `/available` redirects to `/wanted?filter=available`
- [ ] Filter state persists in URL (existing IMP-004 behaviour preserved)
- [ ] Movie count updates correctly for each filter
- [ ] No regressions on Library page (unaffected)
- [ ] All existing unit tests pass (`pytest tests/unit/ -q`)
- [ ] Lint passes (`ruff check .`)

## Out of Scope

- Changes to the Library page
- Changes to movie status values in the database
- The classic UI (`/old/`)
