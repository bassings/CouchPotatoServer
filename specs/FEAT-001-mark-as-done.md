# FEAT-001: Mark as Done Button

## Problem
Movies stay in the "Available" section after being downloaded. Users need a way to manually mark a movie as "done" to:
1. Stop CouchPotato from continuing to search for it
2. Keep it in the library for reference
3. Move it out of the active "Wanted" workflow

## Requirements

### 1. Add "Mark as Done" button to Movie Detail Page
**File:** `couchpotato/ui/templates/partials/movie_detail.html`

- Add button next to existing action buttons (Refresh, IMDb, Trailer, Delete)
- Button should only appear when movie status is NOT already "done"
- Button text: "Mark as Done"
- Style: Similar to other action buttons (use existing Tailwind classes)

### 2. API Endpoint for Mark as Done
**File:** `couchpotato/core/media/_base/media/main.py`

Check if `media.done` API endpoint exists. If not, add one:
```python
addApiView('media.done', self.markDone, docs = {
    'desc': 'Mark media as done (stops searching)',
    'params': {
        'id': {'desc': 'Media ID'}
    }
})

def markDone(self, id=None, **kwargs):
    """Mark a media item as done - stops searching, keeps in library."""
    db = get_db()
    media = db.get('id', id)
    if media:
        media['status'] = 'done'
        db.update(media)
        return {'success': True}
    return {'success': False, 'error': 'Media not found'}
```

### 3. htmx Integration
The button should:
- Call the API endpoint via htmx or fetch
- Reload the page or update the status badge after success
- Show loading state while processing

### 4. Update Movie Cards (Optional Enhancement)
**File:** `couchpotato/ui/templates/partials/movie_cards.html`

Consider adding a quick "Mark Done" action to movie cards on hover (like the existing Refresh button).

## Acceptance Criteria
- [ ] "Mark as Done" button visible on movie detail page when status != 'done'
- [ ] Clicking button changes movie status to 'done' in database
- [ ] Status badge updates to show "done" after clicking
- [ ] Movie no longer appears in active search queue
- [ ] Movie still visible in library/done filter

## Files to Modify
1. `couchpotato/ui/templates/partials/movie_detail.html` - Add button
2. `couchpotato/core/media/_base/media/main.py` - Add API endpoint (if missing)
3. `tests/unit/test_mark_done.py` - Add test (TDD)

## Notes
- Check existing `restatus` function - may be able to reuse
- The old UI had this feature, check git history if needed
