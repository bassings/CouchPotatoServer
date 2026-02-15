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
**Status:** OPEN
**Location:** Settings > Searchers > TorrentPotato > Sync from Jackett
**Description:** The help text for the Jackett sync button shows "undefined" instead of a description
**Expected:** Should show helpful text about what the sync does
**Severity:** Low visual impact but confusing
**Suggested Fix:** Check settings template for missing description text

#### DEF-004: Classic UI Redirects to Login
**Status:** OPEN (By Design?)
**Location:** /old/ route
**Description:** Clicking "Classic UI" in sidebar redirects to a login page instead of the classic interface
**Analysis:** Classic UI uses separate session authentication from new UI
**Impact:** Users cannot easily switch between UIs
**Suggested Fix:** Share authentication between old and new UI, or remove Classic UI link

#### DEF-005: Sister Act 3 Shows Empty Year
**Status:** OPEN (Data Issue)
**Location:** Wanted page and movie cards
**Description:** "Sister Act 3" displays as "Sister Act 3 ()" with empty parentheses
**Root Cause:** Movie has `year: 0` in database (no release date set)
**Suggested Fix:** Either hide year if 0/empty, or show "TBA" instead

#### DEF-006: Ascendant Missing Poster Image
**Status:** OPEN (Data Issue)
**Location:** Wanted page
**Description:** "Ascendant" movie card shows placeholder instead of poster image
**Root Cause:** Image URL may be broken or movie lacks poster in TMDB
**Suggested Fix:** Add error handling that shows fallback, or trigger metadata refresh

---

### Low (P4)

#### DEF-007: The Matrix (2004) in Search Results
**Status:** OPEN
**Location:** Add Movie search
**Description:** Searching "The Matrix" returns a 2004 result which appears to be incorrect/duplicate
**Analysis:** TMDB may have incorrect entries
**Impact:** Minor confusion for users
**Suggested Fix:** Could filter out obvious duplicates or show more identifying info

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

1. **No E2E tests** for new htmx UI
2. **No UI component tests** for Alpine.js components  
3. **Limited error handling tests** for API failures
4. **No accessibility audit** performed
5. **No performance benchmarks** established

---

## Summary

| Category | Count |
|----------|-------|
| Critical Defects | 0 |
| High Defects | 1 (fixed) |
| Medium Defects | 4 |
| Low Defects | 1 |
| Improvements | 6 |
| Feature Ideas | 5 |

**Overall Assessment:** The new htmx UI is functional and well-designed. Two bugs were found and fixed during this session. Remaining issues are minor and mostly data-related rather than code defects.
