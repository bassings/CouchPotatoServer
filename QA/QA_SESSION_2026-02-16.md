# QA Session Notes — 2026-02-16

**Start Time:** 06:43 AEST
**Production URL:** http://homemedia.maeewing.com:5050
**Version:** vdocker:(v3.0.11)

---

## Session Goals
1. Screen inventory of all pages
2. Document user flows
3. Systematic testing of features
4. Document defects and improvements

---

## Screen-by-Screen Walkthrough

### Home / Wanted Page (`/wanted/`)
**Observations:**
- Shows 12 wanted movies
- Grid layout responsive
- Filter buttons: All | Wanted | Done
- Text search filter available
- Movie cards show: poster, title, year, status badge
- Version displayed in sidebar: vdocker:(v3.0.11)

**Issues Found:**
- Filter buttons don't actually filter (FIXED: DEF-002)
- "Sister Act 3 ()" shows empty year
- "Ascendant" missing poster image

**Working Features:**
- Text filter works (e.g., "Matt" shows 3 results)
- Movie count updates correctly
- Click movie → detail page
- Sidebar navigation works

### Available Page (`/available/`)
**Observations:**
- Shows 808 available movies
- Same card layout as Wanted
- No filter buttons (unlike Wanted)
- Only text search available
- All movies show "done" status badge

**Notes:**
- Load time is good despite 808 movies (htmx pagination?)
- Alphabetical sorting

### Suggestions Page (`/suggestions/`)
**Observations:**
- Two tabs: Charts | For You
- Clean empty state with description
- Charts section loads external data

### Add Movie Page (`/add/`)
**Observations:**
- Search box with placeholder text
- Empty state illustration
- Typing triggers search (debounced)

**Search Test - "The Matrix":**
- Returns 3 results:
  1. The Matrix (1999) ✓
  2. The Matrix (2004) ⚠ (suspicious duplicate)
  3. The Matrix Reloaded (2003) ✓
- Each result has quality dropdown
- Quality options: HD, Best, BR-Disk, 2160p, 1080p, 720p, etc.

### Movie Detail Page (`/movie/{id}/`)
**Observations:**
- Initially showed "Unknown" for all movies (BUG - FIXED)
- After fix should show:
  - Poster
  - Title, year, runtime, genres
  - Status badge
  - Plot description
  - Action buttons: Refresh, Trailer, Delete
  - Releases table (if any)

**Action Buttons:**
- Refresh: Triggers metadata refresh
- Trailer: Opens YouTube modal
- Delete: Confirms then removes movie

### Settings Page (`/settings/`)
**Tab: General**
- Server section (username, password, port, HTTPS)
- Updates section (auto-update, check frequency)
- Password field shows masked value

**Tab: Searchers**
- Search Settings collapsible
  - Basics: First search preference
  - Global filters: Preferred, Required, Ignored words
  - NZB: Retention setting
  - Torrents: Minimum seeders
- Provider sections:
  - Usenet — Free: BinSearch
  - Usenet — Account Required: Newznab (2 configured)
  - Torrents — Free: ThePirateBay, TorrentPotato, YTS
  - Torrents — Account Required: AlphaRatio, HDBits, IPTorrents, etc.

**TorrentPotato/Jackett Integration:**
- Jackett URL configured: http://homemedia:9117
- Jackett API Key (masked)
- "Sync Indexers" button present
- Description shows "undefined" (BUG: DEF-003)
- One indexer configured: limetorrents

**Tab: Logs**
- Live log viewer
- Filter by level: All, Errors, Warnings, Info, Debug
- Auto-refresh checkbox
- Manual Refresh and Clear buttons
- Shows HTTP client requests to TMDB

### Setup Wizard (`/wizard/`)
**Observations:**
- 6-step wizard (1-6 progress dots)
- Step 1: Welcome
  - Logo and greeting
  - Overview of 4 setup areas
  - Continue button

### Classic UI (`/old/`)
**Observations:**
- Redirects to login page
- Different auth system than new UI
- Form fields: username, password, remember me

---

## API Testing

### movie.list
```bash
curl "http://homemedia.maeewing.com:5050/api/KEY/movie.list/?status=active"
```
Returns 12 movies with full metadata

### media.get
```bash
curl "http://homemedia.maeewing.com:5050/api/KEY/media.get/?id=MOVIE_ID"
```
Returns single movie details ✓

### movie.get (incorrect)
```bash
curl "http://homemedia.maeewing.com:5050/api/KEY/movie.get/?id=MOVIE_ID"
```
Returns: `{"success": false, "error": "API call doesn't exist"}`
This was the root cause of DEF-001

---

## Fixes Applied This Session

### Fix 1: Movie Detail API Call
**File:** `couchpotato/ui/__init__.py`
**Change:**
```python
# Before
result = callApiHandler('movie.get', id=movie_id)
movie = result.get('movie', result)

# After
result = callApiHandler('media.get', id=movie_id)
movie = result.get('media', result)
```

### Fix 2: Filter Button Click Handlers
**File:** `couchpotato/ui/templates/wanted.html`
**Change:**
```html
<!-- Before -->
<button @click="filterStatus = ''" ...>All</button>

<!-- After -->
<button @click="filterStatus = ''; filterMovies()" ...>All</button>
```
Applied to all three filter buttons.

---

## Outstanding Questions

1. Should Classic UI link be hidden or removed if auth isn't shared?
2. Is the year=0 issue (Sister Act 3) a data import problem?
3. Should duplicates like "The Matrix (2004)" be filtered client-side?
4. Is there a way to refresh/fix broken poster URLs automatically?

---

## Recommendations

1. **Deploy fixes** - Push the two bug fixes to production
2. **Add tests** - Create E2E tests for the fixed functionality
3. **Review data quality** - Audit movies with missing years/posters
4. **Document APIs** - The movie.get vs media.get confusion suggests API docs need updating
5. **Accessibility audit** - Run automated a11y checks on new UI

---

## Session Summary

**Duration:** ~1 hour
**Pages Tested:** 8 unique pages
**Bugs Found:** 7
**Bugs Fixed:** 2
**Tests Needed:** E2E tests for new UI recommended
