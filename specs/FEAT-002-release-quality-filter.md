# FEAT-002: Filter Releases by Profile Quality + Show Downloaded Quality

## Problem
1. Movie detail page shows ALL releases (1057) regardless of profile quality
2. User wants UHD (2160p) but sees 737 x 1080p releases cluttering the view
3. No indication of what quality was actually downloaded
4. Movie stays "active" even after download completes

## Requirements

### 1. Filter Releases to Profile Quality
**File:** `couchpotato/ui/templates/partials/movie_detail.html`

Only show releases that match the movie's profile quality requirements.

Current: Shows all releases
Wanted: Show only releases where `release.quality` is in `profile.qualities`

Example: If profile is "UHD" with qualities `['2160p']`, only show 2160p releases.

### 2. Show Downloaded Quality Badge
**File:** `couchpotato/ui/templates/partials/movie_detail.html` and `movie_cards.html`

When a movie has a release with status `done` or `seeding`:
- Show a badge indicating the downloaded quality (e.g., "Downloaded: 2160p")
- Show on both movie detail page and movie cards

### 3. Display Download Status
Show the active/completed download status:
- `seeding` → "Seeding (2160p)"
- `downloaded` → "Downloaded (2160p)" 
- `done` → "Complete (2160p)"

## Implementation

### Release Filtering (Jinja2)
In movie_detail.html, filter releases before display:
```jinja2
{% set profile_qualities = profile.get('qualities', []) if profile else [] %}
{% set matching_releases = releases|selectattr('quality', 'in', profile_qualities)|list if profile_qualities else releases %}
```

### Downloaded Quality Badge
Find the best completed release:
```jinja2
{% set done_releases = releases|selectattr('status', 'in', ['done', 'seeding', 'downloaded'])|list %}
{% set downloaded_quality = done_releases[0].quality if done_releases else None %}
```

Display badge:
```html
{% if downloaded_quality %}
<span class="badge">Downloaded: {{ downloaded_quality }}</span>
{% endif %}
```

## Acceptance Criteria
- [ ] Release list only shows releases matching profile quality
- [ ] "Downloaded: {quality}" badge shown when release is done/seeding/downloaded
- [ ] Badge visible on movie detail page
- [ ] Badge visible on movie cards (wanted/available pages)
- [ ] Empty state shown if no matching releases found

## Files to Modify
1. `couchpotato/ui/templates/partials/movie_detail.html` - Filter releases, add badge
2. `couchpotato/ui/templates/partials/movie_cards.html` - Add downloaded badge
3. `tests/unit/test_release_filter.py` - Test filtering logic (if applicable)

## Notes
- The actual download IS working correctly (seeding 2160p)
- Profile qualities are already available via the BUG-012 fix

---

## Additional Requirement (from Scott)

### 4. Available Status Logic
**Problem:** Movies show in "Available" if ANY releases exist, even if none match the profile.

**Correct behavior:** 
- Movie should only be "Available" if releases **matching profile quality** exist
- If no matching releases → stay in "Wanted"

**Example:**
- Movie has profile "UHD" (2160p only)
- 737 x 1080p releases found, 0 x 2160p releases
- Current: Shows as "Available" ❌
- Correct: Should stay "Wanted" ✅

**Fix location:** Backend logic that determines availability status, likely in:
- `couchpotato/core/media/_base/media/main.py` - `restatus()` method
- Or searcher logic that sets release/media status

This is a **backend logic fix**, not just UI.
