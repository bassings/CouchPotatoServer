# CouchPotato QA Findings

**Test Date:** 2026-02-16
**Version:** v3.0.11 (docker)
**Tester:** QA Automation

---

## Defects

### Critical (P1)

*No critical defects found*

---

### High (P2)

#### DEF-001: Movie Detail Page Shows "Unknown" Title
**Status:** FIXED ✅
**Location:** Movie detail pages (`/movie/{id}/`)
**Description:** All movie detail pages show "Unknown" as the title instead of the actual movie title
**Root Cause:** UI code called `callApiHandler('movie.get', ...)` but API endpoint is `media.get`
**Fix Applied:** Changed to `callApiHandler('media.get', ...)` and fixed response key from `movie` to `media`
**File:** `couchpotato/ui/__init__.py` line 127

---

### Medium (P3)

#### DEF-002: Filter Buttons Don't Trigger Filtering
**Status:** FIXED ✅
**Location:** Wanted page filter buttons (All/Wanted/Done)
**Description:** Clicking filter buttons updates visual state but doesn't actually filter the movie list
**Root Cause:** Button click handlers set `filterStatus` but didn't call `filterMovies()`
**Fix Applied:** Added `filterMovies()` call to each button's @click handler
**File:** `couchpotato/ui/templates/wanted.html`

#### DEF-003: Jackett Sync Description Shows "undefined"
**Status:** FIXED ✅
**Location:** Settings > Searchers > TorrentPotato > Sync from Jackett
**Description:** The help text for the Jackett sync button shows "undefined" instead of a description
**Root Cause:** The button template used `$root.buildDescription()` which doesn't work correctly from within a nested Alpine `x-data` scope
**Fix Applied:** Added `buildDescription()` method to the `buttonField` component that delegates to the parent settingsPanel
**File:** `couchpotato/ui/templates/settings.html`

#### DEF-004: Classic UI Redirects to Login
**Status:** FIXED ✅
**Location:** /old/ route
**Description:** Clicking "Classic UI" in sidebar redirects to a login page instead of the classic interface
**Root Cause:** The authentication cookie was set without a `path` parameter, defaulting to the login path instead of being shared across all routes
**Fix Applied:** Added `path='/'` to the `set_cookie()` and `delete_cookie()` calls to ensure the session cookie is shared across new UI (/), old UI (/old/), and API routes
**File:** `couchpotato/__init__.py`

#### DEF-005: Sister Act 3 Shows Empty Year
**Status:** FIXED ✅
**Location:** Wanted page, movie cards, search results, movie detail
**Description:** "Sister Act 3" displays as "Sister Act 3 ()" with empty parentheses
**Root Cause:** Movie has `year: 0` in database (no release date set), templates didn't handle this case
**Fix Applied:** Updated all templates to show "TBA" instead of empty year when year is 0, null, or empty
**Files:**
- `couchpotato/ui/templates/partials/movie_cards.html`
- `couchpotato/ui/templates/partials/search_results.html`
- `couchpotato/ui/templates/partials/movie_detail.html`

#### DEF-006: Missing Poster + Refresh Option
**Status:** FIXED ✅
**Location:** Wanted page, movie cards
**Description:** Movies without posters showed a basic placeholder; no way to refresh metadata from movie cards
**Fix Applied:**
1. Improved the missing poster placeholder with a gradient background and clearer "No poster" text
2. Added a refresh button to ALL movie cards (appears on hover) that triggers metadata refresh
3. Refresh uses htmx to reload the movie grid after refresh completes
**File:** `couchpotato/ui/templates/partials/movie_cards.html`

---

### Low (P4)

#### DEF-007: The Matrix (2004) Duplicate in Search Results
**Status:** FIXED ✅
**Location:** Add Movie search results
**Description:** Searching "The Matrix" returns multiple results that are hard to differentiate
**Root Cause:** TMDB returns multiple entries for the same title (remakes, re-releases, etc.)
**Fix Applied:** Added additional identifying information to search results:
- Director name (if available)
- IMDB ID with link to IMDb page
- This helps users differentiate between movies with similar titles
**File:** `couchpotato/ui/templates/partials/search_results.html`

---

## Improvements

### IMP-001: Add Movie Count to Available Page
**Priority:** Medium
**Description:** Available page doesn't show filter buttons like Wanted page. Consider adding:
- Status filter buttons
- Movie count in header

### IMP-002: Keyboard Navigation for Movie Cards
**Priority:** Low
**Description:** Add keyboard support for navigating between movie cards (arrow keys, enter to select)

### IMP-003: Loading Skeleton for Movie Grid
**Priority:** Low
**Description:** Show skeleton placeholders while movies are loading instead of just a spinner

### IMP-004: Persist Filter State in URL
**Priority:** Medium
**Description:** Save filter/search state in URL query params so users can bookmark/share filtered views

### IMP-005: Bulk Actions for Movies
**Priority:** Medium
**Description:** Allow selecting multiple movies for bulk operations (delete, change quality, refresh)

### IMP-006: Dark/Light Theme Toggle
**Priority:** Low
**Description:** Currently only dark theme available. Add theme toggle for light mode preference.

---

## Feature Ideas

### FEAT-001: Movie Collections
Allow grouping movies into collections (e.g., "Marvel Movies", "Weekend Watch")

### FEAT-002: Watch History Integration
Track which movies have been watched (integrate with Plex/Jellyfin)

### FEAT-003: Quick Actions on Hover
Show quick action buttons (refresh, delete, etc.) when hovering over movie cards

### FEAT-004: Mobile App / PWA
Add PWA support for installable mobile experience

### FEAT-005: Notifications in UI
Show toast notifications for successful actions (movie added, deleted, etc.)

---

## Test Coverage Gaps

1. ~~**No E2E tests** for new htmx UI~~ ✅ **ADDED:** Playwright E2E tests in `tests/e2e/`
2. ~~**No UI component tests** for Alpine.js components~~ ✅ **ADDED:** Vitest unit tests in `tests/unit/`
3. **Limited error handling tests** for API failures (partially addressed)
4. ~~**No accessibility audit** performed~~ ✅ **ADDED:** axe-core accessibility tests via Playwright
5. ~~**No performance benchmarks** established~~ ✅ **ADDED:** Lighthouse CI configuration

---

## Summary

| Category | Count |
|----------|-------|
| Critical Defects | 0 |
| High Defects | 1 (fixed) |
| Medium Defects | 4 (all fixed) |
| Low Defects | 1 (fixed) |
| Improvements | 6 |
| Feature Ideas | 5 |

**Overall Assessment:** The new htmx UI is functional and well-designed. All reported defects have been fixed:
- DEF-001, DEF-002: Fixed in previous session
- DEF-003 through DEF-007: Fixed in this session

**Test Infrastructure Added:**
- Playwright E2E tests for core user flows
- Vitest unit tests for Alpine.js component logic
- axe-core accessibility tests integrated
- Lighthouse CI configuration for performance monitoring
- GitHub Actions CI updated to run all tests
