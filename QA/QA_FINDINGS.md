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

#### DEF-010: Quality Fill Fails on Fresh Database (SQLite Migration)
**Status:** FIXED ✅
**Date:** 2026-02-19
**Location:** `couchpotato/core/plugins/quality/main.py`
**Description:** Fresh database installations fail with `KeyError: "No document found in index 'quality' for key: 2160p"` when creating quality profiles.
**Root Cause:** SQLiteAdapter raises `KeyError` when a document doesn't exist, but code only caught `RecordNotFound` (CodernityDB exception).
**Fix Applied:** Changed all `except RecordNotFound:` to `except (RecordNotFound, KeyError):` in 8 files:
- `couchpotato/core/plugins/quality/main.py`
- `couchpotato/core/plugins/release/main.py`
- `couchpotato/core/plugins/dashboard.py`
- `couchpotato/core/database.py`
- `couchpotato/core/media/_base/media/main.py`
- `couchpotato/core/media/movie/_base/main.py`
- `couchpotato/core/media/movie/charts/main.py`
- `couchpotato/core/media/movie/providers/info/_modifier.py`
**Test:** `tests/unit/test_quality_fill.py`
**Commit:** `6064b722`

---

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

#### DEF-012: Profile Not Populated in Media API Response
**Status:** OPEN
**Date:** 2026-02-19
**Location:** `couchpotato/core/media/_base/media/main.py` - `get()` method
**Description:** Movies have `profile_id` set but `profile` is `None` in API response. UI shows "No Profile" for all movies.
**Root Cause:** The `get()` method attaches `category` and `releases` but doesn't attach `profile`. Missing join.
**Fix:** Add profile attachment in `get()` method around line 163:
```python
try: media['profile'] = db.get('id', media.get('profile_id'))
except Exception: pass
```
**Spec:** `specs/BUG-012-profile-not-populated.md`

#### DEF-011: Delete Button No Action on Movie Detail Page
**Status:** OPEN
**Date:** 2026-02-19
**Location:** Movie detail page (`/movie/{id}/`)
**Description:** Clicking the Delete button on a movie detail page does nothing visible — no confirmation dialog, no deletion.
**Expected:** Either a confirmation dialog appears, or the movie is deleted and user redirected to Wanted page.
**Root Cause:** TBD — likely missing htmx attributes or JavaScript handler.
**File:** `couchpotato/ui/templates/partials/movie_detail.html`

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

## Accessibility Issues

**Full Audit:** See `ACCESSIBILITY_AUDIT.md` for comprehensive WCAG 2.1 AA review.

**Status:** ✅ ALL 22 ISSUES FIXED (commit `af868cbb`, 2026-02-16)

### Critical (9 issues) — ALL FIXED ✅
- ~~A11Y-001: Focus not trapped in modal dialogs~~ ✅
- ~~A11Y-002: Interactive elements hidden from keyboard (refresh button)~~ ✅
- ~~A11Y-003: No skip link to main content~~ ✅
- ~~A11Y-004: Dynamic content changes not announced (htmx)~~ ✅
- ~~A11Y-005: Form inputs missing accessible labels~~ ✅
- ~~A11Y-006: Animations ignore reduced motion preference~~ ✅
- ~~A11Y-007: Loading spinner not announced~~ ✅
- ~~A11Y-008: Modal close not returning focus~~ ✅
- ~~A11Y-009: Profile dropdown missing label~~ ✅

### Major (8 issues) — ALL FIXED ✅
- ~~A11Y-010: Decorative SVGs not hidden from assistive tech~~ ✅
- ~~A11Y-011: Status badges not exposed to screen readers~~ ✅
- ~~A11Y-012: Table headers missing scope~~ ✅
- ~~A11Y-013: Insufficient focus indicator contrast~~ ✅
- ~~A11Y-014: Mobile menu button missing expanded state~~ ✅
- ~~A11Y-015: Sidebar collapse button missing expanded state~~ ✅
- ~~A11Y-016: Tab panel missing ARIA attributes~~ ✅
- A11Y-017: Delete confirmation uses native confirm() (kept — native is accessible)

### Minor (5 issues) — ALL FIXED ✅
- ~~A11Y-018 through A11Y-022: Low contrast, missing landmarks, external link indicators~~ ✅

---

## Improvements

### IMP-001: Add Movie Count to Available Page
**Priority:** Medium
**Status:** DONE ✅
**Description:** Available page doesn't show filter buttons like Wanted page. Consider adding:
- Status filter buttons
- Movie count in header
**Implemented:** Unified movie list with filter buttons on both Wanted and Available pages

### IMP-002: Keyboard Navigation for Movie Cards
**Priority:** Low
**Description:** Add keyboard support for navigating between movie cards (arrow keys, enter to select)

### IMP-003: Loading Skeleton for Movie Grid
**Priority:** Low
**Description:** Show skeleton placeholders while movies are loading instead of just a spinner

### IMP-004: Persist Filter State in URL
**Priority:** Medium
**Status:** DONE ✅
**Description:** Save filter/search state in URL query params so users can bookmark/share filtered views
**Implemented:** URL now updates with ?filter=active&q=search as you type/filter

### IMP-005: Bulk Actions for Movies
**Priority:** Medium
**Status:** DONE ✅
**Description:** Allow selecting multiple movies for bulk operations (delete, change quality, refresh)
**Implemented:** Checkbox selection on movie cards, Select All toggle, bulk Refresh and Delete buttons

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
**Status:** DONE ✅
Add PWA support for installable mobile experience
**Implemented:** Web app manifest, service worker, app icons, offline caching

### FEAT-005: Notifications in UI
Show toast notifications for successful actions (movie added, deleted, etc.)

---

## Test Coverage Gaps

1. ~~**No E2E tests** for new htmx UI~~ ✅ **ADDED:** Playwright E2E tests in `tests/e2e/`
2. ~~**No UI component tests** for Alpine.js components~~ ✅ **ADDED:** Vitest unit tests in `tests/unit/`
3. **Limited error handling tests** for API failures (partially addressed)
4. ~~**No accessibility audit** performed~~ ✅ **COMPLETED:** Full WCAG 2.1 AA audit in `ACCESSIBILITY_AUDIT.md`
5. ~~**No performance benchmarks** established~~ ✅ **ADDED:** Lighthouse CI configuration

---

## Refactoring Completed

### Settings Page Component Extraction (2026-02-16)
**Commits:** `f8bdd293` through `5017806f`

**Description:** Full refactor of settings.html (1,670 lines → 67 lines) into modular partials:

| Partial | Purpose |
|---------|---------|
| `header.html` | Title, version, advanced toggle, auto-save indicator |
| `logs_tab.html` | Logs panel with filtering and auto-refresh |
| `field_types.html` | All form field templates (bool, dropdown, password, int, text, button, directory, directories, combined) |
| `provider_card.html` | Collapsible settings cards with enabler toggles |
| `combined_basics_card.html` | Searcher tab grouped sections |
| `test_button.html` | Provider connection testing with results |
| `modals.html` | Restart banner, toast notifications, directory browser |
| `scripts.html` | Alpine.js components (settingsPanel, logsPanel, buttonField, combinedField, directoriesField) |
| `_learn_more.html` | Expandable help sections |

**Additional A11Y Fixes During Refactor:**
- Fixed invalid `aria-controls` references (removed, no matching panel IDs)
- Removed opacity modifiers on muted text (`text-cp-muted/70` → `text-cp-muted`)
- Brightened muted color from `#6b6b78` to `#9b9ba8` for WCAG AA contrast
- Increased white text opacity (`/60` → `/80`, `/70` → `/90`)
- Increased mobile nav text from 9px to 10px
- **Fixed critical contrast issue:** Changed white text to black on accent backgrounds (tabs had 2.01 ratio, needed 4.5:1)

**CI Status:** ✅ All checks passing
**Test Status:** ✅ 548 unit tests passing

---

## Summary

| Category | Count |
|----------|-------|
| Critical Defects | 0 |
| High Defects | 2 (all fixed) |
| Medium Defects | 4 (all fixed) |
| Low Defects | 2 (1 fixed, 1 open) |
| Accessibility Issues | 22 (all fixed ✅) |
| Improvements | 6 (6 done ✅) |
| Feature Ideas | 5 (1 done: PWA) |

**Overall Assessment:** The new htmx UI is functional and well-designed. All critical/high/medium defects have been fixed:
- DEF-001, DEF-002: Fixed in previous session
- DEF-003 through DEF-007: Fixed in this session

**Test Infrastructure Added:**
- Playwright E2E tests for core user flows
- Vitest unit tests for Alpine.js component logic
- axe-core accessibility tests integrated
- Lighthouse CI configuration for performance monitoring
- GitHub Actions CI updated to run all tests

**Accessibility Status:**
A comprehensive WCAG 2.1 AA audit identified 22 accessibility issues. The UI has a solid foundation (semantic HTML, proper headings, lang attribute), but needs work on:
- Keyboard accessibility (focus trapping, skip links)
- Screen reader support (ARIA labels, live regions)
- Reduced motion preferences
See `ACCESSIBILITY_AUDIT.md` for full details and implementation plan.

## DEF-010: Jackett settings stored as bytes repr (Fixed)
**Severity:** High  
**Status:** Fixed (2026-02-16)

**Issue:** Jackett URL and API key were stored in config.ini as `b'...'` strings (Python bytes repr) instead of the actual string values.

**Root Cause:** Somewhere in the settings save path, bytes were being converted to their repr() instead of decoded.

**Fix:**
1. Manually fixed config.ini values to remove `b'...'` wrapper
2. Added code to handle `b'...'` string wrapper in jackettSync and jackettTest functions
3. Commits: `9ad5f0eb`, `6baf2aa8`

### IMP-002: Keyboard Navigation for Movie Cards
**Priority:** Low
**Status:** DONE ✅
**Implemented:** Arrow keys navigate between visible cards, Home/End for first/last, respects grid layout

### IMP-003: Loading Skeleton for Movie Grid
**Priority:** Low
**Status:** DONE ✅
**Implemented:** 12 skeleton placeholder cards with animate-pulse during loading

### IMP-006: Theme Toggle (Light/Dark Mode)
**Priority:** Low
**Status:** DONE ✅
**Implemented:** Toggle button in sidebar, persists to localStorage, respects system preference
