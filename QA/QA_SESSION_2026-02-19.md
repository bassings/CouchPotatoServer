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
| Suggestions page loads | ✅ | HTTP 200 |
| Add Movie page loads | ✅ | HTTP 200 |
| Settings page loads | ✅ | HTTP 200 |
| Movie detail page loads | ⏳ | Need movie to test |

### 2. Core User Flows
| Test | Status | Notes |
|------|--------|-------|
| Search for movie | ✅ | API returns 3 results for "Matrix" |
| Add movie to wanted | ⏳ | |
| View movie details | ⏳ | |
| Filter wanted list | ⏳ | |
| Delete movie | ⏳ | |

### 3. Settings
| Test | Status | Notes |
|------|--------|-------|
| Settings tabs load | ✅ | HTTP 200 |
| Test searcher connection | ⏳ | |
| Test downloader connection | ⏳ | |
| Save settings persists | ⏳ | |

### 4. New Features (v3.1.0)
| Test | Status | Notes |
|------|--------|-------|
| SQLite database works | ✅ | All quality profiles created |
| Fresh install creates SQLite | ✅ | database_v2/ created |

---

## Notes

- Container running on port 5051
- Fresh database with SQLite (no CodernityDB migration needed)
- Quality fill bug found and fixed (DEF-010)
- API key: `40cbf8f9a02a4d889d611ac493098a3e`
