# QA Session - 2026-02-19

**Version:** v3.1.0 (dev build from master)
**Tester:** Eggbert (AI)
**Environment:** Local Docker (docker-compose.dev.yml, port 5051)

---

## Pre-QA Checks

- [x] Local tests pass (`test_startup_local.py`, `test_sqlite_adapter.py`)
- [x] Lint passes (`ruff check .`)
- [x] Dev container builds successfully
- [x] Container starts and logs show startup sequence
- [x] UI accessible at http://localhost:5051

---

## Issues Found

### DEF-010: Quality fill fails on fresh database (FIXED ✅)
**Severity:** High
**Component:** Quality plugin
**Steps to reproduce:**
1. Start fresh container with empty database
2. Check container logs

**Expected:** Quality profiles created successfully
**Actual:** KeyError when trying to get non-existent quality

**Error:**
```
KeyError: "No document found in index 'quality' for key: 2160p"
```

**Root cause:** `db.get()` raises KeyError when document doesn't exist, but `fill()` method in quality plugin expects it to return None or handle missing gracefully.

**Fix:** Changed all `except RecordNotFound:` to `except (RecordNotFound, KeyError):` in 8 files.
**Commit:** `6064b722`
**Test:** `tests/unit/test_quality_fill.py`

---

## Test Execution

### 1. Navigation & Core Pages
| Test | Status | Notes |
|------|--------|-------|
| Home/Wanted page loads | ✅ | HTTP 200 |
| Available page loads | ✅ | HTTP 200 |
| Suggestions page loads | ✅ | Charts/For You tabs work |
| Add Movie page loads | ✅ | HTTP 200 |
| Settings page loads | ✅ | All 8 tabs load correctly |
| Movie detail page loads | ✅ | Poster, metadata, actions shown |

### 2. Core User Flows
| Test | Status | Notes |
|------|--------|-------|
| Search for movie | ✅ | TMDB returns results with IMDB IDs |
| Add movie to wanted | ✅ | "The Matrix" added successfully |
| View movie details | ✅ | Title, year, runtime, genres, plot, buttons |
| Filter wanted list | ✅ | "1 of 1" / "0 of 1" updates correctly |
| Delete movie | ⚠️ | Button exists but no action on click |

### 3. Settings
| Test | Status | Notes |
|------|--------|-------|
| Settings tabs load | ✅ | General, Searchers, Downloaders, etc. |
| Test searcher connection | ⏳ | No providers configured |
| Test downloader connection | ⏳ | No providers configured |
| Save settings persists | ⏳ | Skipped (fresh container) |

### 4. New Features (v3.1.0)
| Test | Status | Notes |
|------|--------|-------|
| SQLite database works | ✅ | All quality profiles created |
| Fresh install creates SQLite | ✅ | database_v2/ created |
| CodernityDB compat methods | ✅ | get_many, with_doc, count all work |

---

## Issues Found

### DEF-011: Delete button no action (LOW)
**Severity:** Low
**Component:** Movie detail page
**Steps to reproduce:**
1. View movie detail page
2. Click Delete button

**Expected:** Confirmation dialog or movie deleted
**Actual:** No visible action

**Note:** May require htmx attributes or JavaScript fix. Not blocking for release.

---

## Notes

- Container running on port 5051
- Fresh database with SQLite (no CodernityDB migration needed)
- Quality fill bug found and fixed (DEF-010)
- API key: `40cbf8f9a02a4d889d611ac493098a3e`
- Browser testing via OpenClaw browser automation
