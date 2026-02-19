# BUG-012: Profile Not Populated in Media API Response

## Problem
Movies returned by `media.list` and `media.get` APIs have `profile_id` set but `profile` is `None`. The UI shows "No Profile" for all movies even though they have valid profiles assigned.

## Evidence
```
profile_id=d4bca9e622bb49cd8f7b0b847597012c  ← Exists in DB
profile=None                                  ← Not populated in response
```

The profile "UHD" exists and is valid, but isn't being joined to the media response.

## Root Cause
In `couchpotato/core/media/_base/media/main.py`, the `get()` method (line 147-167):
- ✅ Attaches `category` (line 162)
- ✅ Attaches `releases` (line 165)
- ❌ **Does NOT attach `profile`**

## Fix Required

**File:** `couchpotato/core/media/_base/media/main.py`

In the `get()` method, after attaching category (around line 163), add:

```python
# Attach profile
try: media['profile'] = db.get('id', media.get('profile_id'))
except Exception: pass
```

## Acceptance Criteria
- [ ] `media.get` returns `profile` object when `profile_id` exists
- [ ] `media.list` returns movies with populated `profile` objects
- [ ] UI shows correct profile name (e.g., "UHD") instead of "No Profile"
- [ ] Test added to verify profile attachment

## Files to Modify
1. `couchpotato/core/media/_base/media/main.py` - Add profile attachment in `get()` method
2. `tests/unit/test_media_profile.py` - Add test (TDD)

## Priority
High - Affects all movie displays in production
